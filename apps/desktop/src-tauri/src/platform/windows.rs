//! Windows: no console window for the Core, and a job object that holds the
//! Core and everything it starts.
//!
//! The job is created with "kill on job close", so when this application's
//! last handle to it closes — including when the application dies abruptly —
//! every process in it ends (FR-018).

use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command};

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

/// `CREATE_NO_WINDOW`: the Core is a console program, and a release build of
/// the application has no console for it to borrow, so without this flag a
/// console window would open beside the application's own.
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub fn configure(command: &mut Command) {
    command.creation_flags(CREATE_NO_WINDOW);
}

/// The Core's job object.
pub struct Tree {
    job: HANDLE,
}

// The handle is only used through the kernel's own synchronisation.
unsafe impl Send for Tree {}
unsafe impl Sync for Tree {}

impl Tree {
    /// Put a just-started Core in a new job. A process the Core starts later
    /// is in the job too.
    pub fn adopt(child: &Child) -> io::Result<Self> {
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if job.is_null() {
                return Err(io::Error::last_os_error());
            }
            let tree = Tree { job };
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let size = std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32;
            if SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                       (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                                       size) == 0 {
                return Err(io::Error::last_os_error());
            }
            if AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE) == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(tree)
        }
    }

    /// End every process in the job, now.
    pub fn terminate(&self) -> io::Result<()> {
        if unsafe { TerminateJobObject(self.job, 1) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}

impl Drop for Tree {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.job) };
    }
}
