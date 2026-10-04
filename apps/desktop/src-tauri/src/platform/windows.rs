//! Windows: no console window for the Core, and a job object that holds the
//! Core and everything it starts.
//!
//! The job is created with "kill on job close", so when this application's
//! last handle to it closes — including when the application dies abruptly —
//! every process in it ends (FR-018). The Core starts suspended and runs only
//! once it is in the job: a process it starts, however early, is in the job
//! too, because job membership is inherited and never retroactive.

use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command};

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

/// `CREATE_NO_WINDOW`: the Core is a console program, and a release build of
/// the application has no console for it to borrow, so without this flag a
/// console window would open beside the application's own.
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// `CREATE_SUSPENDED`: the Core's first thread waits until it is resumed.
const CREATE_SUSPENDED: u32 = 0x0000_0004;

pub fn configure(command: &mut Command) {
    command.creation_flags(CREATE_NO_WINDOW);
}

/// The Core is started suspended; `Tree::adopt` resumes it once it is in its
/// job.
pub fn start_suspended(command: &mut Command) {
    command.creation_flags(CREATE_NO_WINDOW | CREATE_SUSPENDED);
}

/// Resume every thread of the suspended process `pid` (a new process has
/// one: the first).
fn resume(pid: u32) -> io::Result<()> {
    use windows_sys::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if snapshot == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let mut entry: THREADENTRY32 = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;
        let mut resumed = 0;
        let mut more = Thread32First(snapshot, &mut entry) != 0;
        while more {
            if entry.th32OwnerProcessID == pid {
                let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                if !thread.is_null() {
                    if ResumeThread(thread) != u32::MAX {
                        resumed += 1;
                    }
                    CloseHandle(thread);
                }
            }
            more = Thread32Next(snapshot, &mut entry) != 0;
        }
        CloseHandle(snapshot);
        if resumed == 0 {
            return Err(io::Error::other("the Core's first thread could not be resumed"));
        }
        Ok(())
    }
}

/// The Core's job object.
pub struct Tree {
    job: HANDLE,
}

// The handle is only used through the kernel's own synchronisation.
unsafe impl Send for Tree {}
unsafe impl Sync for Tree {}

impl Tree {
    /// Put a just-started, suspended Core in a new job, then let it run. A
    /// process the Core starts is in the job too.
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
            resume(child.id())?;
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
