#!/usr/bin/env node
/**
 * The credential canary across every flow (T086; FR-028, FR-032, SC-009).
 *
 * Each flow runs with a unique `api_key` in its Core's home, and the harness
 * searches everything the run left — every IPC message and bridge command,
 * every Core's arguments, what the page held, the application's output, log
 * and preferences — for it. Any occurrence fails the flow.
 *
 *   node e2e/canary-full.mjs [--skip-build]
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** The flows of T086, by the scenarios that run them. */
export const FLOWS = [
  "ready",                     // the ready window
  "conversation",              // a conversation, a form, a mode change
  "boundary",                  // the adversarial text
  "reload",                    // a reload during a held turn
  "crash",                     // crashes and restarts through the sequenced double
  "unconfigured",              // "Check again" from an unconfigured home
  "lifetime-quit-now",         // "Closing…" with a forced stop
  "lifetime-second-confirmed", // a second launch
];

const here = path.dirname(fileURLToPath(import.meta.url));
const run = spawnSync(process.execPath,
                      [path.join(here, "harness.mjs"), "--canary", ...process.argv.slice(2), ...FLOWS],
                      { stdio: "inherit" });
process.exit(run.status ?? 1);
