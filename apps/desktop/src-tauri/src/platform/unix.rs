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

/// Nothing to hold back here: the group exists from the first instruction.
pub fn start_suspended(_command: &mut Command) {}

/// The Core's process group, and the watchdog that ends it if the
/// application dies (`watchdog.rs`).
pub struct Tree {
    group: libc::pid_t,
    watchdog: std::sync::Mutex<Option<Child>>,
}

impl Tree {
    pub fn adopt(child: &Child) -> io::Result<Self> {
        let group = child.id() as libc::pid_t;
        let watchdog = super::watchdog::start(group);
        // On Linux the parent-death signal still ends the Core itself, so the
        // watchdog is best effort there. On macOS nothing else would end a
        // Core that ignores EOF: no Core runs without one, and the caller
        // ends the Core it just started.
        #[cfg(target_os = "macos")]
        let watchdog = watchdog
            .map_err(|problem| io::Error::other(format!("the Core's watchdog could not start: {problem}")))?;
        #[cfg(not(target_os = "macos"))]
        let watchdog = watchdog.ok();
        #[cfg(target_os = "macos")]
        let watchdog = Some(watchdog);
        Ok(Tree { group, watchdog: std::sync::Mutex::new(watchdog) })
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
