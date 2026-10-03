//! The test build's support (`--features e2e`). Never in a release build
//! (contracts/native-bridge.md §Test build only).
//!
//! - `e2e_report`: the scenario runner's one command. A `checkpoint` hands
//!   the harness something to do (release a hold, kill the Core) and waits for
//!   its reply; a `query` reads what only the native side can see (the Core's
//!   pid, this process's network listeners); the `result` ends the run with
//!   the scenario's verdict.
//! - The recorder: every inbound IPC message and every bridge command's
//!   arguments and return value, as JSON lines, for the credential canary.
//! - Doubles for the folder chooser and the second-launch confirmation.
//!
//! The harness talks to this build over the application's own standard
//! streams: each report is one stdout line starting with `REPORT_PREFIX`, and
//! each checkpoint's reply is one line the harness writes to stdin. Files and
//! switches come through the environment: `COMODOR_E2E_RECORD` (the
//! recorder), `COMODOR_E2E_SCENARIO`, `COMODOR_E2E_PARAMS`,
//! `COMODOR_E2E_CHOOSE` (a JSON list of chooser answers, a path or `null`,
//! taken in order) and `COMODOR_E2E_CONFIRM` (`yes` or `no`).

use std::fs::OpenOptions;
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, AtomicUsize, Ordering};
use std::sync::Mutex;

use serde_json::{json, Value};

/// Marks the harness's lines on stdout, apart from anything else printed.
pub const REPORT_PREFIX: &str = "@@comodor-e2e@@ ";

static WRITE: Mutex<()> = Mutex::new(());
static CHECKPOINT: Mutex<()> = Mutex::new(());
static CORE_PID: AtomicU32 = AtomicU32::new(0);
static CHOICES_TAKEN: AtomicUsize = AtomicUsize::new(0);
/// Every start directory the chooser double was given, in order.
static CHOOSER_STARTS: Mutex<Vec<Option<String>>> = Mutex::new(Vec::new());

fn append(variable: &str, value: &Value) {
    let Some(path) = std::env::var_os(variable) else { return };
    let _held = WRITE.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{value}");
    }
}

fn tell_harness(value: &Value) {
    let _held = WRITE.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{REPORT_PREFIX}{value}");
    let _ = out.flush();
}

/// Record one thing that crossed the bridge, for the canary search.
pub fn record(kind: &str, value: &Value) {
    append("COMODOR_E2E_RECORD", &json!({ "kind": kind, "value": value }));
}

/// The supervisor reports each Core it starts, and 0 when none runs.
pub fn set_core_pid(pid: u32) {
    CORE_PID.store(pid, Ordering::SeqCst);
}

/// The script that tells the page which scenario to run.
pub fn init_script() -> String {
    let scenario = std::env::var("COMODOR_E2E_SCENARIO").unwrap_or_default();
    let params: Value = std::env::var("COMODOR_E2E_PARAMS").ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or(Value::Null);
    format!("window.__COMODOR_E2E__ = {};",
            json!({ "scenario": scenario, "params": params }))
}

/// The chooser double: records the start directory it was given, then
/// answers with the next scripted choice. `None` is a dismissal, and so is
/// running out of choices.
pub fn choose_folder(start: Option<&Path>) -> Option<PathBuf> {
    let index = CHOICES_TAKEN.fetch_add(1, Ordering::SeqCst);
    let start = start.map(|path| path.to_string_lossy().into_owned());
    record("chooser", &json!({ "start": start, "index": index }));
    CHOOSER_STARTS.lock().unwrap_or_else(|poisoned| poisoned.into_inner()).push(start);
    let choices: Vec<Option<String>> = std::env::var("COMODOR_E2E_CHOOSE").ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default();
    choices.into_iter().nth(index).flatten().map(PathBuf::from)
}

/// The second-launch confirmation double: records that it was asked.
pub fn confirm(question: &str) -> bool {
    let answer = std::env::var("COMODOR_E2E_CONFIRM").map(|text| text == "yes")
        .unwrap_or(false);
    record("confirm", &json!({ "question": question, "answer": answer }));
    answer
}

/// The scenario runner's one command. A checkpoint blocks until the harness
/// replies, so the command runs off the main thread.
#[tauri::command(async)]
pub fn e2e_report(app: tauri::AppHandle, result: Value) -> Result<Value, String> {
    match result.get("phase").and_then(Value::as_str) {
        Some("checkpoint") => {
            let _one_at_a_time = CHECKPOINT.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
            tell_harness(&result);
            let mut reply = String::new();
            std::io::stdin().lock().read_line(&mut reply)
                .map_err(|problem| format!("the harness did not reply: {problem}"))?;
            if reply.trim().is_empty() {
                return Err("the harness closed its channel".into());
            }
            serde_json::from_str(reply.trim()).map_err(|problem| problem.to_string())
        }
        Some("query") => match result.get("what").and_then(Value::as_str) {
            Some("listeners") => Ok(json!({ "listeners": network_listeners() })),
            Some("core_pid") => Ok(json!({ "pid": CORE_PID.load(Ordering::SeqCst) })),
            Some("chooser") => Ok(json!({
                "starts": *CHOOSER_STARTS.lock().unwrap_or_else(|poisoned| poisoned.into_inner()),
            })),
            Some(other) => Err(format!("unknown query {other}")),
            None => Err("a query names what it wants".into()),
        },
        Some("result") => {
            tell_harness(&result);
            let passed = result.get("ok").and_then(Value::as_bool).unwrap_or(false);
            app.exit(if passed { 0 } else { 1 });
            Ok(json!({}))
        }
        _ => Err("a report has a phase: checkpoint, query or result".into()),
    }
}

/// The TCP listening and bound UDP sockets this process owns (FR-010).
pub fn network_listeners() -> Vec<String> {
    listeners::of_this_process()
}

#[cfg(windows)]
mod listeners {
    use windows_sys::Win32::Foundation::{ERROR_INSUFFICIENT_BUFFER, NO_ERROR};
    use windows_sys::Win32::NetworkManagement::IpHelper::{
        GetExtendedTcpTable, GetExtendedUdpTable, MIB_TCP6ROW_OWNER_PID,
        MIB_TCPROW_OWNER_PID, MIB_UDP6ROW_OWNER_PID, MIB_UDPROW_OWNER_PID,
        TCP_TABLE_OWNER_PID_LISTENER, UDP_TABLE_OWNER_PID,
    };
    use windows_sys::Win32::Networking::WinSock::{AF_INET, AF_INET6};

    /// The table, in a `u32` buffer so its rows (all `u32`-aligned) are
    /// read from aligned memory.
    fn table(read: impl Fn(*mut core::ffi::c_void, *mut u32) -> u32) -> Option<Vec<u32>> {
        let mut size = 0u32;
        let first = read(core::ptr::null_mut(), &mut size);
        if first != ERROR_INSUFFICIENT_BUFFER && first != NO_ERROR {
            return None;
        }
        let mut buffer = vec![0u32; size as usize / 4 + 4];
        size = (buffer.len() * 4) as u32;
        let second = read(buffer.as_mut_ptr().cast(), &mut size);
        (second == NO_ERROR).then_some(buffer)
    }

    /// MIB_*TABLE_OWNER_PID: a `u32` count, then the rows.
    fn rows<T>(buffer: &[u32]) -> &[T] {
        assert_eq!(core::mem::align_of::<T>(), 4);
        let count = buffer[0] as usize;
        assert!(4 + count * core::mem::size_of::<T>() <= buffer.len() * 4);
        unsafe { core::slice::from_raw_parts(buffer.as_ptr().add(1).cast::<T>(), count) }
    }

    pub fn of_this_process() -> Vec<String> {
        let me = std::process::id();
        let mut found = Vec::new();
        for (family, name) in [(AF_INET, "tcp4"), (AF_INET6, "tcp6")] {
            let Some(buffer) = table(|ptr, size| unsafe {
                GetExtendedTcpTable(ptr, size, 0, family as u32,
                                    TCP_TABLE_OWNER_PID_LISTENER, 0)
            }) else { continue };
            if family == AF_INET {
                for row in rows::<MIB_TCPROW_OWNER_PID>(&buffer) {
                    if row.dwOwningPid == me {
                        found.push(format!("{name} listen port {}", u16::from_be(row.dwLocalPort as u16)));
                    }
                }
            } else {
                for row in rows::<MIB_TCP6ROW_OWNER_PID>(&buffer) {
                    if row.dwOwningPid == me {
                        found.push(format!("{name} listen port {}", u16::from_be(row.dwLocalPort as u16)));
                    }
                }
            }
        }
        for (family, name) in [(AF_INET, "udp4"), (AF_INET6, "udp6")] {
            let Some(buffer) = table(|ptr, size| unsafe {
                GetExtendedUdpTable(ptr, size, 0, family as u32, UDP_TABLE_OWNER_PID, 0)
            }) else { continue };
            if family == AF_INET {
                for row in rows::<MIB_UDPROW_OWNER_PID>(&buffer) {
                    if row.dwOwningPid == me {
                        found.push(format!("{name} bound port {}", u16::from_be(row.dwLocalPort as u16)));
                    }
                }
            } else {
                for row in rows::<MIB_UDP6ROW_OWNER_PID>(&buffer) {
                    if row.dwOwningPid == me {
                        found.push(format!("{name} bound port {}", u16::from_be(row.dwLocalPort as u16)));
                    }
                }
            }
        }
        found
    }
}

#[cfg(target_os = "linux")]
mod listeners {
    use std::collections::HashSet;

    fn own_socket_inodes() -> HashSet<String> {
        let mut inodes = HashSet::new();
        if let Ok(entries) = std::fs::read_dir("/proc/self/fd") {
            for entry in entries.flatten() {
                if let Ok(target) = std::fs::read_link(entry.path()) {
                    let text = target.to_string_lossy().into_owned();
                    if let Some(inode) = text.strip_prefix("socket:[").and_then(|t| t.strip_suffix(']')) {
                        inodes.insert(inode.to_string());
                    }
                }
            }
        }
        inodes
    }

    pub fn of_this_process() -> Vec<String> {
        let mine = own_socket_inodes();
        let mut found = Vec::new();
        for (file, listening_only) in [("tcp", true), ("tcp6", true), ("udp", false), ("udp6", false)] {
            let Ok(text) = std::fs::read_to_string(format!("/proc/net/{file}")) else { continue };
            for line in text.lines().skip(1) {
                let fields: Vec<&str> = line.split_whitespace().collect();
                if fields.len() < 10 {
                    continue;
                }
                // TCP state 0A is LISTEN; any UDP socket of ours is bound.
                if listening_only && fields[3] != "0A" {
                    continue;
                }
                if mine.contains(fields[9]) {
                    found.push(format!("{file} {}", fields[1]));
                }
            }
        }
        found
    }
}

#[cfg(target_os = "macos")]
mod listeners {
    pub fn of_this_process() -> Vec<String> {
        let pid = std::process::id().to_string();
        let output = std::process::Command::new("lsof")
            .args(["-nP", "-a", "-p", &pid, "-i"])
            .output();
        let Ok(output) = output else {
            return vec!["lsof could not be run".into()];
        };
        String::from_utf8_lossy(&output.stdout).lines().skip(1)
            .filter(|line| line.contains("(LISTEN)") || line.contains(" UDP "))
            .map(str::to_string)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The report sees a listener when there is one, so an empty report
    /// means there is none (FR-010).
    #[test]
    fn the_listener_report_sees_this_process_listening() {
        let tcp = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let udp = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
        let tcp_port = tcp.local_addr().unwrap().port();
        let udp_port = udp.local_addr().unwrap().port();
        let during = network_listeners();
        let names = |port: u16| during.iter().any(|entry| {
            entry.contains(&format!("port {port}"))
                || entry.contains(&format!(":{port:04X}"))
                || entry.contains(&format!(":{port} "))
                || entry.ends_with(&format!(":{port}"))
        });
        assert!(names(tcp_port), "TCP {tcp_port} in {during:?}");
        assert!(names(udp_port), "UDP {udp_port} in {during:?}");
        drop((tcp, udp));
    }
}
