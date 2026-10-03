//! Windows: no console window for the Core.

use std::io;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command};

/// `CREATE_NO_WINDOW`: the Core is a console program, and a release build of
/// the application has no console for it to borrow, so without this flag a
/// console window would open beside the application's own.
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub fn configure(command: &mut Command) {
    command.creation_flags(CREATE_NO_WINDOW);
}

/// What keeps the Core's process tree under this application.
pub struct Tree;

impl Tree {
    pub fn adopt(_child: &Child) -> io::Result<Self> {
        Ok(Tree)
    }

    pub fn terminate(&mut self, child: &mut Child) -> io::Result<()> {
        child.kill()
    }
}
