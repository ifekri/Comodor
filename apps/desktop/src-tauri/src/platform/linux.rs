//! Linux: the Core gets a parent-death signal, so it ends with the
//! application even when the application dies abruptly (FR-018).
//!
//! The signal follows the *thread* that started the Core, which is why the
//! supervisor starts every Core from its one long-lived thread.

use std::io;
use std::os::unix::process::CommandExt;
use std::process::Command;

pub fn arm_parent_death(command: &mut Command) {
    let parent = std::process::id() as libc::pid_t;
    unsafe {
        command.pre_exec(move || {
            // Only async-signal-safe calls between fork and exec.
            if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) != 0 {
                return Err(io::Error::last_os_error());
            }
            // The parent may have died before the signal was armed.
            if libc::getppid() != parent {
                libc::_exit(1);
            }
            Ok(())
        });
    }
}
