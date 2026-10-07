//! Linux and macOS: the Core leads its own process group, so one signal
//! reaches it and everything it started. On Linux it also gets a parent-death
//! signal (`linux.rs`). And it runs only once its watchdog (`watchdog.rs`) is
//! watching: between fork and exec it tells its pid and waits for leave to
//! run, so no instruction of its own — nothing it could start — comes before
//! the guard.

use std::fs::File;
use std::io::{self, Read, Write};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::process::CommandExt;
use std::process::{Child, Command};

pub fn configure(command: &mut Command) {
    command.process_group(0);
    #[cfg(target_os = "linux")]
    super::linux::arm_parent_death(command);
}

/// A pipe whose ends close on exec, so no other program inherits them.
fn pipe() -> io::Result<(OwnedFd, OwnedFd)> {
    let mut fds = [0; 2];
    unsafe {
        #[cfg(target_os = "linux")]
        if libc::pipe2(fds.as_mut_ptr(), libc::O_CLOEXEC) != 0 {
            return Err(io::Error::last_os_error());
        }
        #[cfg(not(target_os = "linux"))]
        {
            if libc::pipe(fds.as_mut_ptr()) != 0 {
                return Err(io::Error::last_os_error());
            }
            for fd in fds {
                libc::fcntl(fd, libc::F_SETFD, libc::FD_CLOEXEC);
            }
        }
        Ok((OwnedFd::from_raw_fd(fds[0]), OwnedFd::from_raw_fd(fds[1])))
    }
}

/// Start the Core, held before exec until its watchdog is watching, and
/// return it with its process tree.
///
/// `spawn` returns only once the child has exec'd or failed, so the leave to
/// run comes from a helper thread: it learns the Core's pid from the child,
/// starts the watchdog for that group, and once it watches, lets the Core
/// run. The spawn itself stays on the calling (supervisor) thread, which the
/// Linux parent-death signal follows. A watchdog that cannot start closes
/// the leave unwritten, and the held child ends without ever running.
pub fn spawn(mut command: Command) -> io::Result<(Child, Tree)> {
    let (told_read, told_write) = pipe()?;
    let (leave_read, leave_write) = pipe()?;
    let (told, ours_told, leave, ours_leave) =
        (told_write.as_raw_fd(), told_read.as_raw_fd(), leave_read.as_raw_fd(), leave_write.as_raw_fd());
    unsafe {
        command.pre_exec(move || {
            // Only async-signal-safe calls between fork and exec. The child's
            // copies of the helper's ends go first, so it alone holds them.
            libc::close(ours_told);
            libc::close(ours_leave);
            let pid = libc::getpid().to_ne_bytes();
            if libc::write(told, pid.as_ptr().cast(), pid.len()) != pid.len() as isize {
                return Err(io::Error::last_os_error());
            }
            let mut go = 0u8;
            if libc::read(leave, (&mut go as *mut u8).cast(), 1) != 1 {
                return Err(io::Error::from_raw_os_error(libc::ECANCELED));
            }
            Ok(())
        });
    }
    let helper = std::thread::Builder::new().name("core-watchdog".into()).spawn(move || {
        let mut told = File::from(told_read);
        let mut pid = [0u8; std::mem::size_of::<libc::pid_t>()];
        told.read_exact(&mut pid)?;
        let watchdog = super::watchdog::start(libc::pid_t::from_ne_bytes(pid))?;
        File::from(leave_write).write_all(b"g")?;
        Ok::<Child, io::Error>(watchdog)
    })?;
    let spawned = command.spawn();
    // The child has its own copies, or is gone: the helper sees an end now.
    drop(told_write);
    drop(leave_read);
    let watchdog = helper.join().unwrap_or_else(|_| Err(io::Error::other("the watchdog helper panicked")));
    match (spawned, watchdog) {
        (Ok(child), Ok(watchdog)) => {
            let group = child.id() as libc::pid_t;
            Ok((child, Tree { group, watchdog: std::sync::Mutex::new(Some(watchdog)) }))
        }
        // No Core runs unguarded: on macOS nothing else ends a Core that
        // ignores EOF, and on Linux the parent-death signal reaches the Core
        // alone, not what it started. (Linux's `pidfd_open` is in every kernel
        // Tauri's WebKitGTK runs on, so this fails only when resources are
        // exhausted.)
        (spawned, Err(problem)) => {
            if let Ok(mut child) = spawned {
                let _ = child.kill();
                let _ = child.wait();
            }
            Err(io::Error::other(format!("the Core's watchdog could not start: {problem}")))
        }
        (Err(problem), Ok(mut watchdog)) => {
            let _ = watchdog.kill();
            let _ = watchdog.wait();
            Err(problem)
        }
    }
}

/// The Core's process group, and the watchdog that ends it if the
/// application dies (`watchdog.rs`).
pub struct Tree {
    group: libc::pid_t,
    watchdog: std::sync::Mutex<Option<Child>>,
}

impl Tree {
    /// Signal the whole group to end, now.
    pub fn terminate(&self) -> io::Result<()> {
        if unsafe { libc::kill(-self.group, libc::SIGKILL) } != 0 {
            let error = io::Error::last_os_error();
            // No process left in the group is not a failure to stop it.
            if error.raw_os_error() != Some(libc::ESRCH) {
                return Err(error);
            }
        }
        Ok(())
    }
}

impl Drop for Tree {
    /// The Core is gone with this handle: so is its watchdog, reaped.
    fn drop(&mut self) {
        let watchdog = self.watchdog.get_mut().unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(mut watchdog) = watchdog.take() {
            let _ = watchdog.kill();
            let _ = watchdog.wait();
        }
    }
}
