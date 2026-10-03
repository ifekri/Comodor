//! Linux and macOS.

use std::io;
use std::process::{Child, Command};

pub fn configure(_command: &mut Command) {}

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
