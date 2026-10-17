/**
 * The test build's bridge record: one JSON line per command and per message
 * the window received, appended as the run goes.
 */

import fs from "node:fs";

/**
 * The record's entries. A process still writing (a second launch) or stopped
 * mid-write leaves its last line unfinished — no newline after it — and that
 * line is not yet an entry; every finished line must parse.
 */
export function recordLines(text) {
  const lines = text.split("\n");
  lines.pop();
  return lines.filter(Boolean).map((line) => JSON.parse(line));
}

export function recordEntries(record) {
  return fs.existsSync(record) ? recordLines(fs.readFileSync(record, "utf-8")) : [];
}
