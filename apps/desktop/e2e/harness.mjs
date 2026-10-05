#!/usr/bin/env node
/**
 * The scenario harness (T016): builds the test build once, then launches the
 * application once per scenario against an offline Core home and a scripted
 * Core, answers the page's checkpoints, and collects what the run left.
 *
 *   node e2e/harness.mjs [--skip-build] [scenario …]
 *
 * With no scenario named, every scenario in `setups.mjs` runs. Results and
 * collected files go to `COMODOR_E2E_ARTIFACTS` (default `e2e/out`).
 *
 * The application reports on its stdout, one line per report after
 * `REPORT_PREFIX`; the harness answers each checkpoint with one line on the
 * application's stdin. Nothing here waits by elapsed time: a scenario that
 * never reports is ended at its failure deadline and fails.
 */

import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { createInterface } from "node:readline";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SETUPS } from "./setups.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESKTOP = path.dirname(HERE);
const NATIVE = path.join(DESKTOP, "src-tauri");
const FIXTURES = path.join(NATIVE, "tests", "fixtures");
const REPO = path.resolve(DESKTOP, "..", "..");
const REPORT_PREFIX = "@@comodor-e2e@@ ";
/** How long a scenario may go without its result before it fails. */
const FAILURE_DEADLINE_MS = 180_000;
const PYTHON = process.env.COMODOR_PYTHON
  ?? (process.platform === "win32" ? "python" : "python3");
const ARTIFACTS = path.resolve(process.env.COMODOR_E2E_ARTIFACTS ?? path.join(HERE, "out"));

// On Linux the window needs a display and the single-instance plugin a D-Bus
// session: run this whole harness inside both, once.
if (process.platform === "linux" && !process.env.COMODOR_E2E_WRAPPED) {
  const wrapped = spawnSync("dbus-run-session", [
    "--", "xvfb-run", "-a", process.execPath, fileURLToPath(import.meta.url),
    ...process.argv.slice(2),
  ], { stdio: "inherit", env: { ...process.env, COMODOR_E2E_WRAPPED: "1" } });
  process.exit(wrapped.status ?? 1);
}

function targetDir() {
  return process.env.CARGO_TARGET_DIR
    ? path.resolve(process.env.CARGO_TARGET_DIR)
    : path.join(NATIVE, "target");
}

function executable() {
  const name = process.platform === "win32" ? "comodor-desktop.exe" : "comodor-desktop";
  return path.join(targetDir(), "release", name);
}

function build() {
  const cli = createRequire(import.meta.url).resolve("@tauri-apps/cli/tauri.js");
  const result = spawnSync(process.execPath, [
    cli, "build", "--no-bundle", "--features", "e2e",
    "--config", path.join("src-tauri", "tauri.e2e.conf.json"),
  ], { cwd: DESKTOP, stdio: "inherit" });
  if (result.status !== 0) throw new Error(`the test build failed (${result.status})`);
}

function writeCoreHome(home, setup) {
  const config = {
    agent: { mode: "act", loop: false },
    learning: { enabled: false },
    mcp: { enabled: false },
    cron: { enabled: false },
    skills: { enabled: false },
  };
  if (setup.configured !== false) {
    config.provider = "fake";
    config.model = "fake-1";
    config.providers = {
      fake: { name: "fake", kind: "fake", base_url: "offline",
              api_key: setup.apiKey ?? "test", model: "fake-1", label: "Fake" },
    };
  }
  fs.writeFileSync(path.join(home, "config.json"), JSON.stringify(config));
}

function holdAddress(root, name) {
  return process.platform === "win32"
    ? `\\\\.\\pipe\\comodor-e2e-${name}-${process.pid}`
    // A Unix socket path is limited to about 100 bytes: a short one in /tmp.
    : `/tmp/comodor-e2e-hold-${process.pid}-${name}.sock`;
}

/** Release a fixture's hold point, through the same library that opened it. */
function releaseHold(address) {
  const family = process.platform === "win32" ? "AF_PIPE" : "AF_UNIX";
  const result = spawnSync(PYTHON, ["-c",
    "import sys\nfrom multiprocessing.connection import Client\n"
    + "with Client(sys.argv[1], family=sys.argv[2]) as c: c.send_bytes(b'release')",
    address, family], { encoding: "utf-8" });
  if (result.status !== 0) throw new Error(`releasing the hold failed: ${result.stderr}`);
}

/** `$workspace`, `$stored` and `$inner` in a setup value, at any depth. */
function resolve(value, places) {
  if (typeof value === "string" && value in places) return places[value];
  if (Array.isArray(value)) return value.map((item) => resolve(item, places));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, resolve(item, places)]));
  }
  return value;
}

/** Answer one checkpoint from the page. */
function answer(checkpoint, run) {
  switch (checkpoint.name) {
    case "release-hold":
      releaseHold(run.hold);
      return { ok: true };
    case "kill-core": {
      const pid = Number(checkpoint.data?.pid);
      if (!pid) return { ok: false, error: "no Core pid" };
      process.kill(pid, "SIGKILL");
      return { ok: true };
    }
    // The lifetime cases (T074).
    case "remember-core": {
      const pid = Number(checkpoint.data?.pid);
      if (!pid) return { ok: false, error: "no Core pid" };
      run.cores.push(pid);
      return { ok: true };
    }
    case "configure-provider":
      // What `comodor setup` leaves behind: the offline provider, configured.
      writeCoreHome(run.home, { ...run.setup, configured: true, apiKey: run.apiKey });
      return { ok: true };
    case "close-window":
    case "quit":
      // Done by the test build once the page has this reply.
      return { ok: true, act: checkpoint.name };
    case "kill-app":
      run.killed = true;
      run.app.kill("SIGKILL");
      return { ok: true };
    case "second-launch": {
      const target = resolve(checkpoint.data?.path ?? "", run.places);
      const second = spawnSync(executable(), target ? [target] : [], {
        env: run.env, stdio: "ignore", timeout: FAILURE_DEADLINE_MS,
      });
      return { ok: true, code: second.status, signal: second.signal };
    }
    default:
      return { ok: false, error: `unknown checkpoint ${checkpoint.name}` };
  }
}

/**
 * Where the canary is. It must be in the Core's home (or the search proves
 * nothing) and nowhere else: not in any recorded IPC message or command, not
 * in anything the page held, not in the Core's arguments, the application's
 * output, its log or its preferences.
 */
function searchCanary(canary, places) {
  const leaks = [];
  const contains = (text) => typeof text === "string" && text.includes(canary);
  const file = (label, at) => {
    if (fs.existsSync(at) && contains(fs.readFileSync(at, "utf-8"))) leaks.push(label);
    return fs.existsSync(at);
  };
  const planted = fs.existsSync(places.home) && contains(fs.readFileSync(places.home, "utf-8"));
  // The record holds every IPC message, every command and every Core's
  // arguments; the fixture also writes its own arguments when it can.
  const searched = file("the bridge record", places.record);
  file("the Core's own record of its arguments", places.argv);
  if (fs.existsSync(places.data)) {
    for (const entry of fs.readdirSync(places.data, { recursive: true })) {
      const at = path.join(places.data, String(entry));
      if (fs.statSync(at).isFile()) file(`the application's ${entry}`, at);
    }
  }
  if (contains(places.result)) leaks.push("the page's holdings or the scenario's result");
  if (contains(places.output)) leaks.push("the application's output");
  return { planted, searched, leaks };
}

/** How often a process that is not ours is checked for: between checks only. */
const CHECK_EVERY_MS = 50;

/**
 * Wait for process `pid` to be gone, by the failure deadline. Node has no
 * way to wait on a process it did not start, so this checks, then waits for
 * the next check, until it is gone.
 */
async function gone(pid) {
  const ends = Date.now() + FAILURE_DEADLINE_MS;
  while (Date.now() < ends) {
    try {
      process.kill(pid, 0);
    } catch {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, CHECK_EVERY_MS));
  }
  return false;
}

function copyIfPresent(from, to) {
  if (fs.existsSync(from)) fs.cpSync(from, to, { recursive: true });
}

async function runScenario(name) {
  const setup = SETUPS[name];
  if (!setup) return { scenario: name, ok: false, error: "no setup for this scenario" };
  if (setup.platforms && !setup.platforms.includes(process.platform)) {
    return { scenario: name, ok: true, notApplicable: `not applicable on ${process.platform}` };
  }
  // Its real path: the Core reports its workspace resolved (`/private/var`
  // on macOS, long names on Windows), and the window shows that report.
  const root = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), "comodor-e2e-")));
  const home = path.join(root, "home");
  const workspace = path.join(root, "workspace");
  const data = path.join(root, "desktop-data");
  const stored = path.join(root, "stored");
  for (const directory of [home, workspace, data, stored]) fs.mkdirSync(directory);
  // SC-009: a credential nothing else could contain, by the run.
  const canary = setup.canary || CANARY_ALL ? `CANARY-${randomUUID()}` : undefined;
  writeCoreHome(home, canary ? { ...setup, apiKey: canary } : setup);
  // A folder inside a project: the Core works in the project's root.
  const inner = path.join(workspace, "inner");
  if (setup.workspaceArgument === "inner") {
    fs.mkdirSync(path.join(workspace, ".git"));
    fs.mkdirSync(inner);
  }
  const places = { $workspace: workspace, $stored: stored, $inner: inner };

  if (setup.lastSelectedFolder !== undefined) {
    fs.writeFileSync(path.join(data, "preferences.json"), JSON.stringify({
      version: 1, last_selected_folder: resolve(setup.lastSelectedFolder, places),
    }));
  }

  const [fixture, argument] = setup.core ?? ["scripted_core.py", "echo"];
  const fixturePath = path.join(FIXTURES, fixture);
  if (/\s/.test(fixturePath)) {
    return { scenario: name, ok: false,
             error: `COMODOR_ARGS is split on whitespace; move the checkout: ${fixturePath}` };
  }
  const coreArgs = setup.realCore ? "-m comodor" : `${fixturePath} ${argument}`;
  const run = { hold: setup.hold ? holdAddress(root, name) : undefined, cores: [], places, home, setup,
                apiKey: canary ?? setup.apiKey };
  const record = path.join(root, "record.jsonl");
  const env = {
    ...process.env,
    COMODOR_HOME: home,
    COMODOR_BIN: PYTHON,
    COMODOR_ARGS: coreArgs,
    PYTHONPATH: path.join(REPO, "src"),
    PYTHONIOENCODING: "utf-8",
    COMODOR_DESKTOP_DATA_DIR: data,
    COMODOR_E2E_SCENARIO: name,
    COMODOR_E2E_PARAMS: JSON.stringify(resolve(setup.params ?? {}, places)),
    COMODOR_E2E_RECORD: record,
    COMODOR_E2E_CHOOSE: JSON.stringify(resolve(setup.choose ?? [], places)),
    COMODOR_E2E_CONFIRM: setup.confirm ? "yes" : "no",
  };
  if (run.hold) {
    env.COMODOR_TEST_HOLD = run.hold;
    // A socket left by an earlier, killed run would refuse the bind.
    if (process.platform !== "win32") fs.rmSync(run.hold, { force: true });
  }
  const argv = path.join(root, "argv.json");
  if (canary) env.COMODOR_TEST_ARGV_FILE = argv;
  const childPid = path.join(root, "child.pid");
  if (setup.childPid) env.COMODOR_TEST_CHILD_PID_FILE = childPid;
  if (setup.sequence) {
    // The double keeps its counter beside this file.
    env.COMODOR_TEST_SEQUENCE = path.join(root, "sequence.json");
    fs.writeFileSync(env.COMODOR_TEST_SEQUENCE, JSON.stringify(setup.sequence));
  }

  const args = setup.workspaceArgument === "inner" ? [inner] : setup.workspaceArgument ? [workspace] : [];
  const started = Date.now();
  const app = spawn(executable(), args, { env, stdio: ["pipe", "pipe", "pipe"] });
  run.app = app;
  run.env = env;
  const output = [];
  app.stderr.on("data", (chunk) => output.push(chunk.toString()));
  // A reply racing the application's end fails to write; its exit decides.
  app.stdin.on("error", () => {});

  const outcome = await new Promise((resolve) => {
    let result;
    const deadline = setTimeout(() => {
      app.kill("SIGKILL");
      resolve({ ok: false, error: `no result within the failure deadline (${FAILURE_DEADLINE_MS} ms)` });
    }, FAILURE_DEADLINE_MS);
    createInterface({ input: app.stdout }).on("line", (line) => {
      output.push(`${line}\n`);
      if (!line.startsWith(REPORT_PREFIX)) return;
      const report = JSON.parse(line.slice(REPORT_PREFIX.length));
      if (report.phase === "checkpoint") {
        let reply;
        try {
          reply = answer(report, run);
        } catch (problem) {
          reply = { ok: false, error: String(problem) };
        }
        // A killed application takes no reply.
        if (!run.killed) app.stdin.write(`${JSON.stringify(reply)}\n`);
      } else if (report.phase === "result") {
        result = report;
      }
    });
    app.on("error", (problem) => {
      clearTimeout(deadline);
      resolve({ ok: false, error: `the application did not start: ${problem.message}` });
    });
    app.on("exit", (code, signal) => {
      clearTimeout(deadline);
      if (setup.lifetime && !result) {
        // The application ended the way the case ends it: by closing, by
        // quitting, or killed by the harness.
        const ended = run.killed ? signal !== null || code !== 0 : code === 0;
        resolve(ended ? { ok: true, exitCode: code, signal }
                      : { ok: false, error: `the application ended badly (${code ?? signal})` });
      } else if (!result) {
        resolve({ ok: false, error: `the application exited (${code ?? signal}) without a result` });
      } else {
        resolve({ ...result, exitCode: code, ok: result.ok === true && code === 0 });
      }
    });
  });

  const kept = path.join(ARTIFACTS, name);
  fs.rmSync(kept, { recursive: true, force: true });
  fs.mkdirSync(kept, { recursive: true });
  copyIfPresent(record, path.join(kept, "record.jsonl"));
  copyIfPresent(data, path.join(kept, "desktop-data"));
  fs.writeFileSync(path.join(kept, "output.txt"), output.join(""));
  const summary = { scenario: name, elapsedMs: Date.now() - started, ...outcome };
  // The double's child must go with it.
  const childCounts = setup.childPid === true
    || (Array.isArray(setup.childPid) && setup.childPid.includes(process.platform));
  if (childCounts && fs.existsSync(childPid)) run.cores.push(Number(fs.readFileSync(childPid, "utf-8")));
  // SC-007: no Core outlives the application, whatever ended it.
  if (run.cores.length > 0) {
    const left = [];
    for (const pid of run.cores) if (!(await gone(pid))) left.push(pid);
    summary.coresLeft = left;
    if (left.length > 0 && summary.ok) {
      summary.ok = false;
      summary.error = `a Core outlived the application: ${left.join(", ")}`;
    }
  } else if (setup.lifetime && summary.ok) {
    summary.ok = false;
    summary.error = "the case never named its Core";
  }
  // OD-2: the log says whether the stop was forced.
  if (setup.forced !== undefined && summary.ok) {
    const log = path.join(data, "comodor-desktop.log");
    const forced = fs.existsSync(log) && fs.readFileSync(log, "utf-8").includes("stopped before it finished");
    if (forced !== setup.forced) {
      summary.ok = false;
      summary.error = `the stop was ${forced ? "" : "not "}forced, which this case does not expect`;
    }
  }
  if (canary) {
    const found = searchCanary(canary, {
      home: path.join(home, "config.json"), record, argv, data,
      result: JSON.stringify(outcome), output: output.join(""),
    });
    summary.canary = found;
    if (summary.ok && (!found.planted || found.leaks.length > 0 || !found.searched)) {
      summary.ok = false;
      summary.error = found.planted
        ? `the credential reached: ${found.leaks.join(", ") || "(nothing searched)"}`
        : "the credential was never planted in the Core's home";
    }
  }
  // SC-001: from the process start to the page's ready moment.
  if (setup.maxReadyMs !== undefined && summary.ok) {
    const readyAt = Number(summary.details?.readyAt);
    summary.readyMs = Math.round(readyAt - started);
    if (!Number.isFinite(summary.readyMs) || summary.readyMs > setup.maxReadyMs) {
      summary.ok = false;
      summary.error = `ready after ${summary.readyMs} ms; the bound is ${setup.maxReadyMs} ms`;
    }
  }
  fs.writeFileSync(path.join(kept, "result.json"), JSON.stringify(summary, null, 2));
  // Best effort: on Windows the Core may still be ending (its job closes
  // with the application) and holds its working folder until it has.
  try {
    fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  } catch (problem) {
    console.error(`left ${root} behind: ${problem.message}`);
  }
  return summary;
}

const argv = process.argv.slice(2);
const skipBuild = argv.includes("--skip-build");
// Every scenario of this run gets a unique credential and the full search.
const CANARY_ALL = argv.includes("--canary");
const named = argv.filter((arg) => !arg.startsWith("--"));
// The lifetime cases end the application themselves; `npm run lifetime`
// runs them (lifetime.mjs), and a plain run leaves them out.
const scenarios = named.length ? named
  : Object.keys(SETUPS).filter((name) => !SETUPS[name].lifetime);

if (!skipBuild) build();
if (!fs.existsSync(executable())) {
  console.error(`no test build at ${executable()}`);
  process.exit(1);
}
fs.mkdirSync(ARTIFACTS, { recursive: true });

let failed = 0;
for (const name of scenarios) {
  const summary = await runScenario(name);
  const verdict = summary.notApplicable ? "N/A " : summary.ok ? "PASS" : "FAIL";
  const ready = summary.readyMs === undefined ? "" : `, ready in ${summary.readyMs} ms`;
  console.log(`${verdict} ${name} (${summary.elapsedMs ?? 0} ms${ready})${summary.ok ? "" : `: ${summary.error ?? "see result.json"}`}`);
  if (!summary.ok) failed += 1;
}
fs.writeFileSync(path.join(ARTIFACTS, "summary.json"),
                 JSON.stringify({ scenarios, failed }, null, 2));
process.exit(failed ? 1 : 0);
