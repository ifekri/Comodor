//! Linux and macOS: the Core leads its own process group, so one signal
//! reaches it and everything it started. On Linux it also gets a parent-death
//! signal, so it ends with the application even when the application dies
//! abruptly (FR-018). That signal follows the *thread* that started the Core,
//! which is why the supervisor starts every Core from its one long-lived
//! thread.

use std::io;
use std::os::unix::process::CommandExt;
use std::process::{Child, Command};

pub fn configure(command: &mut Command) {
    command.process_group(0);
    #[cfg(target_os = "linux")]
    {
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
}

/// The Core's process group.
pub struct Tree {
    group: libc::pid_t,
}

impl Tree {
    pub fn adopt(child: &Child) -> io::Result<Self> {
        Ok(Tree { group: child.id() as libc::pid_t })
    }

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
