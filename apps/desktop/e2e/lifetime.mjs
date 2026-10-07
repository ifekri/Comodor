#!/usr/bin/env node
/**
 * The lifetime harness (T074): every case that ends the application itself
 * — a close, a quit mid-turn, "Quit now", a kill, and second launches —
 * through the scenario harness, which waits for every named Core to be gone.
 *
 *   node e2e/lifetime.mjs [--skip-build]
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SETUPS } from "./setups.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const cases = Object.keys(SETUPS).filter((name) => SETUPS[name].lifetime);
const run = spawnSync(process.execPath, [path.join(here, "harness.mjs"), ...process.argv.slice(2), ...cases],
                      { stdio: "inherit" });
process.exit(run.status ?? 1);
