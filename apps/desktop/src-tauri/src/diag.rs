//! The Core's stderr, kept as a bounded tail (data-model.md §4, FR-006).
//!
//! At most `MAX_LINES` lines and `MAX_BYTES` bytes, dropping the oldest
//! first. It is read on its own thread for the Core's whole life, so the Core
//! never blocks writing diagnostics, and it is only ever text: nothing here
//! parses it as protocol.

use std::collections::VecDeque;
use std::io::Read;
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

pub const MAX_LINES: usize = 200;
pub const MAX_BYTES: usize = 64 * 1024;

#[derive(Default, Debug)]
pub struct DiagnosticTail {
    lines: VecDeque<String>,
    bytes: usize,
}

impl DiagnosticTail {
    pub fn new() -> Self {
        Self::default()
    }

    /// Keep one line, dropping the oldest until both bounds hold.
    pub fn push(&mut self, line: &str) {
        // A line costs its bytes plus the newline that joins it to the next.
        let line = cut(line, MAX_BYTES - 1);
        self.bytes += line.len() + 1;
        self.lines.push_back(line.to_string());
        while self.lines.len() > MAX_LINES || self.bytes > MAX_BYTES + 1 {
            let dropped = self.lines.pop_front().expect("over a bound means not empty");
            self.bytes -= dropped.len() + 1;
        }
    }

    /// The tail as plain text, one line per line.
    pub fn text(&self) -> String {
        Vec::from(self.lines.clone()).join("\n")
    }

    pub fn clear(&mut self) {
        self.lines.clear();
        self.bytes = 0;
    }
}

/// Read `stream` to its end on a thread of its own, into `tail`.
pub fn read_into(stream: impl Read + Send + 'static, tail: Arc<Mutex<DiagnosticTail>>)
                 -> JoinHandle<()> {
    std::thread::Builder::new()
        .name("core-stderr".into())
        .spawn(move || read_lines(stream, &tail))
        .expect("start the stderr reader")
}

/// Split into lines without ever holding more than one bounded line: the rest
/// of an overlong line is read and dropped.
fn read_lines(mut stream: impl Read, tail: &Mutex<DiagnosticTail>) {
    let mut line: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 8192];
    let keep = |line: &mut Vec<u8>| {
        if line.last() == Some(&b'\r') {
            line.pop();
        }
        let text = String::from_utf8_lossy(line).into_owned();
        tail.lock().unwrap_or_else(|poisoned| poisoned.into_inner()).push(&text);
        line.clear();
    };
    loop {
        let read = match stream.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(read) => read,
        };
        for &byte in &chunk[..read] {
            if byte == b'\n' {
                keep(&mut line);
            } else if line.len() < MAX_BYTES {
                line.push(byte);
            }
        }
    }
    if !line.is_empty() {
        keep(&mut line);
    }
}

/// At most `limit` bytes of `text`, cut on a character boundary.
fn cut(text: &str, limit: usize) -> &str {
    if text.len() <= limit {
        return text;
    }
    let mut end = limit;
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    &text[..end]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn size(text: &str) -> usize {
        text.len()
    }

    #[test]
    fn at_most_two_hundred_lines_dropping_the_oldest_first() {
        let mut tail = DiagnosticTail::new();
        for n in 0..250 {
            tail.push(&format!("line {n}"));
        }
        let text = tail.text();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), MAX_LINES);
        assert_eq!(lines[0], "line 50");
        assert_eq!(lines[199], "line 249");
    }

    #[test]
    fn at_most_sixty_four_kib_dropping_the_oldest_first() {
        let mut tail = DiagnosticTail::new();
        let long = "x".repeat(1000);
        for n in 0..150 {
            tail.push(&format!("{n:03} {long}"));
        }
        let text = tail.text();
        assert!(size(&text) <= MAX_BYTES, "{} bytes", size(&text));
        assert!(text.lines().last().unwrap().starts_with("149 "));
        assert!(!text.contains("000 "), "the oldest went first");
        assert!(text.lines().count() >= 60, "only as much as needed was dropped");
    }

    #[test]
    fn one_line_longer_than_the_bound_is_cut_to_fit() {
        let mut tail = DiagnosticTail::new();
        tail.push("first");
        tail.push(&"é".repeat(MAX_BYTES));
        let text = tail.text();
        assert!(size(&text) <= MAX_BYTES);
        assert!(text.starts_with('é'), "cut on a character boundary");
    }

    #[test]
    fn it_is_text_never_protocol() {
        let mut tail = DiagnosticTail::new();
        let line = r#"{"version":2,"type":"response","id":"native:hello","result":{}}"#;
        tail.push(line);
        assert_eq!(tail.text(), line);
    }

    #[test]
    fn the_reader_keeps_up_with_a_flood_and_tolerates_any_bytes() {
        let mut flood = Vec::new();
        for n in 0..400 {
            flood.extend_from_slice(format!("noise {n} {}\r\n", "y".repeat(300)).as_bytes());
        }
        flood.extend_from_slice(b"bad \xff\xfe bytes\n");
        flood.extend_from_slice(&vec![b'z'; MAX_BYTES * 3]);
        flood.extend_from_slice(b"\nlast line");
        let tail = Arc::new(Mutex::new(DiagnosticTail::new()));
        read_into(std::io::Cursor::new(flood), tail.clone()).join().unwrap();
        let text = tail.lock().unwrap().text();
        assert!(size(&text) <= MAX_BYTES);
        assert!(text.lines().count() <= MAX_LINES);
        assert!(text.ends_with("last line"), "the final unterminated line is kept");
        assert!(!text.contains('\r'));
    }
}
