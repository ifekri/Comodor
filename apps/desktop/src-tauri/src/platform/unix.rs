//! Linux and macOS: the Core leads its own process group, so one signal
//! reaches it and everything it started. On Linux it also gets a parent-death
//! signal (`linux.rs`).

use std::io;
use std::process::{Child, Command};

pub fn configure(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.process_group(0);
    #[cfg(target_os = "linux")]
    super::linux::arm_parent_death(command);
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
