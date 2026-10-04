//! Linux and macOS: a watchdog that ends the Core's whole process group when
//! the application dies (FR-018).
//!
//! The parent-death signal (Linux) reaches the Core alone, and macOS has no
//! such signal at all, so a Core that ignores EOF — or anything it started —
//! could outlive an application that was killed outright. With every Core the
//! application starts a small process: this same executable, run with
//! `WATCHDOG_FLAG`, in a process group of its own. It waits, without polling,
//! for the application or the Core to exit — `kqueue` on macOS, `pidfd` on
//! Linux — then signals the Core's whole group and exits. Whichever it sees
//! first: on Linux the parent-death signal ends the Core in the same instant
//! the application dies, so "the Core went first" cannot be read as "the
//! application is fine"; and when the Core does exit on its own, the
//! application ends its leftovers at that moment anyway, so signalling them
//! here is the same act. The application ends the watchdog when the Core is
//! gone.

use std::ffi::OsString;
use std::io;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::OnceLock;

/// The argument that makes this executable a watchdog instead of the window.
pub const WATCHDOG_FLAG: &str = "--comodor-watchdog";

static PROGRAM: OnceLock<PathBuf> = OnceLock::new();

/// The executable that runs the watchdog: this one, unless set (tests start
/// the application's binary from a test harness).
pub fn set_program(program: PathBuf) {
    let _ = PROGRAM.set(program);
}

fn program() -> io::Result<PathBuf> {
    match PROGRAM.get() {
        Some(program) => Ok(program.clone()),
        None => std::env::current_exe(),
    }
}

/// Start the watchdog for the Core leading process group `group`.
pub fn start(group: libc::pid_t) -> io::Result<Child> {
    use std::os::unix::process::CommandExt;
    let application = std::process::id().to_string();
    Command::new(program()?)
        .args([WATCHDOG_FLAG, &application, &group.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        // Its own group: a signal to the application's group, or to the
        // Core's, does not take the watchdog with it.
        .process_group(0)
        .spawn()
}

/// When this process was started as a watchdog, watch, and return the exit
/// code; otherwise `None`, and the application starts as usual.
pub fn main_if_watchdog(args: &[OsString]) -> Option<i32> {
    if args.get(1).map(|arg| arg == WATCHDOG_FLAG) != Some(true) {
        return None;
    }
    let number = |at: usize| args.get(at)?.to_str()?.parse::<libc::pid_t>().ok();
    let (Some(application), Some(group)) = (number(2), number(3)) else { return Some(2) };
    Some(watch(application, group))
}

fn end_group(group: libc::pid_t) {
    unsafe { libc::kill(-group, libc::SIGKILL) };
}

/// Wait until the application or the Core exits, then end the Core's group.
#[cfg(target_os = "macos")]
fn watch(application: libc::pid_t, group: libc::pid_t) -> i32 {
    unsafe {
        let queue = libc::kqueue();
        if queue < 0 {
            return 1;
        }
        let watch_for = |pid: libc::pid_t| libc::kevent {
            ident: pid as libc::uintptr_t,
            filter: libc::EVFILT_PROC,
            flags: libc::EV_ADD | libc::EV_ONESHOT,
            fflags: libc::NOTE_EXIT,
            data: 0,
            udata: std::ptr::null_mut(),
        };
        // An application already gone cannot be registered: end the group.
        let changes = [watch_for(application)];
        if libc::kevent(queue, changes.as_ptr(), 1, std::ptr::null_mut(), 0, std::ptr::null()) < 0 {
            end_group(group);
            return 0;
        }
        let core = [watch_for(group)];
        if libc::kevent(queue, core.as_ptr(), 1, std::ptr::null_mut(), 0, std::ptr::null()) < 0 {
            end_group(group); // the Core is gone already: only leftovers remain
            return 0;
        }
        let mut seen: libc::kevent = std::mem::zeroed();
        loop {
            let got = libc::kevent(queue, std::ptr::null(), 0, &mut seen, 1, std::ptr::null());
            if got < 0 && io::Error::last_os_error().kind() == io::ErrorKind::Interrupted {
                continue;
            }
            end_group(group);
            return 0;
        }
    }
}

/// Wait until the application or the Core exits, then end the Core's group.
#[cfg(target_os = "linux")]
fn watch(application: libc::pid_t, group: libc::pid_t) -> i32 {
    unsafe {
        let open = |pid: libc::pid_t| libc::syscall(libc::SYS_pidfd_open, pid, 0) as libc::c_int;
        let app = open(application);
        if app < 0 {
            // No such process: the application is gone already.
            if io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH) {
                end_group(group);
                return 0;
            }
            return 1;
        }
        let core = open(group);
        if core < 0 {
            end_group(group); // the Core is gone already: only leftovers remain
            return 0;
        }
        let mut fds = [
            libc::pollfd { fd: app, events: libc::POLLIN, revents: 0 },
            libc::pollfd { fd: core, events: libc::POLLIN, revents: 0 },
        ];
        loop {
            let got = libc::poll(fds.as_mut_ptr(), 2, -1);
            if got < 0 && io::Error::last_os_error().kind() == io::ErrorKind::Interrupted {
                continue;
            }
            end_group(group);
            return 0;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_flag_makes_a_watchdog() {
        let args = |items: &[&str]| items.iter().map(OsString::from).collect::<Vec<_>>();
        assert_eq!(main_if_watchdog(&args(&["comodor-desktop"])), None);
        assert_eq!(main_if_watchdog(&args(&["comodor-desktop", "/some/workspace"])), None);
        assert_eq!(main_if_watchdog(&args(&["comodor-desktop", WATCHDOG_FLAG, "x"])), Some(2));
    }
}
