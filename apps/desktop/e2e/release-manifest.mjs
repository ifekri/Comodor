#!/usr/bin/env node
/**
 * The release command list, from what the build generated (T085; FR-030,
 * SC-011; contracts/native-bridge.md §One source for the command list).
 *
 * 1. Build the release configuration (no feature, no config override, no
 *    bundle) and keep its generated ACL manifest and capabilities.
 * 2. Assert, matching identifiers to command names from the generated files:
 *    exactly one allow/deny pair per command of `COMMANDS` and nothing for
 *    `e2e_report`; only the `main` capability, for window `main`; `main`
 *    grants exactly the nine allow identifiers (the `core:` minimum recorded
 *    at T003 is empty) and no plugin permission.
 * 3. Build the test configuration into its own target directory, and assert
 *    it differs only by `e2e_report`'s pair and the `e2e-test` capability.
 * 4. Prove step 2 can fail: on a scratch copy whose `main` also grants
 *    `e2e_report`, the same assertions must fail.
 *
 *   node e2e/release-manifest.mjs
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESKTOP = path.dirname(HERE);
const NATIVE = path.join(DESKTOP, "src-tauri");
const GENERATED = path.join(NATIVE, "gen", "schemas");
const TEST_COMMAND = "e2e_report";

/** The nine names, read from the one constant the build reads too. */
function commandsConstant() {
  const source = fs.readFileSync(path.join(NATIVE, "src", "command_names.rs"), "utf-8");
  const list = source.slice(source.indexOf("pub const COMMANDS"));
  const body = list.slice(list.indexOf("= [") + 3, list.indexOf("];"));
  return [...body.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
}

function build(label, extra, targetDir) {
  const cli = createRequire(import.meta.url).resolve("@tauri-apps/cli/tauri.js");
  const env = { ...process.env };
  if (targetDir) env.CARGO_TARGET_DIR = targetDir;
  const result = spawnSync(process.execPath, [cli, "build", "--no-bundle", ...extra],
                           { cwd: DESKTOP, stdio: "inherit", env });
  if (result.status !== 0) throw new Error(`the ${label} build failed (${result.status})`);
  const kept = fs.mkdtempSync(path.join(os.tmpdir(), `comodor-manifest-${label}-`));
  for (const file of ["acl-manifests.json", "capabilities.json"]) {
    fs.copyFileSync(path.join(GENERATED, file), path.join(kept, file));
  }
  return {
    acl: JSON.parse(fs.readFileSync(path.join(kept, "acl-manifests.json"), "utf-8")),
    capabilities: JSON.parse(fs.readFileSync(path.join(kept, "capabilities.json"), "utf-8")),
  };
}

/** The app's own permissions, by the command each one names. */
function appPermissions(acl) {
  const app = acl["__app-acl__"];
  if (!app?.permissions) throw new Error("no __app-acl__ permissions in the manifest");
  const byCommand = new Map();
  for (const [id, permission] of Object.entries(app.permissions)) {
    const allow = permission.commands?.allow ?? [];
    const deny = permission.commands?.deny ?? [];
    for (const command of [...allow, ...deny]) {
      const entry = byCommand.get(command) ?? { allow: [], deny: [] };
      (allow.includes(command) ? entry.allow : entry.deny).push(id);
      byCommand.set(command, entry);
    }
  }
  return byCommand;
}

/** Step 2: the release configuration grants exactly the contract. */
function checkRelease({ acl, capabilities }, commands) {
  const problems = [];
  const permissions = appPermissions(acl);
  for (const command of commands) {
    const entry = permissions.get(command);
    if (!entry || entry.allow.length !== 1 || entry.deny.length !== 1) {
      problems.push(`${command}: expected one allow and one deny, found ${JSON.stringify(entry)}`);
    }
  }
  const extra = [...permissions.keys()].filter((command) => !commands.includes(command));
  if (extra.length) problems.push(`permissions for commands outside COMMANDS: ${extra.join(", ")}`);
  if (permissions.has(TEST_COMMAND)) problems.push(`${TEST_COMMAND} has permissions in a release build`);

  const names = Object.keys(capabilities);
  if (names.length !== 1 || names[0] !== "main") problems.push(`capabilities: ${names.join(", ")}`);
  const main = capabilities["main"];
  if (JSON.stringify(main?.windows) !== JSON.stringify(["main"])) {
    problems.push(`main's windows: ${JSON.stringify(main?.windows)}`);
  }
  const granted = (main?.permissions ?? []).map((p) => (typeof p === "string" ? p : p.identifier));
  const expected = commands.map((command) => permissions.get(command)?.allow[0]).filter(Boolean);
  const missing = expected.filter((id) => !granted.includes(id));
  const unexpected = granted.filter((id) => !expected.includes(id));
  // The `core:` minimum for the IPC channel was measured empty at T003 (e),
  // so any `core:` or plugin permission here is an addition.
  if (missing.length) problems.push(`main lacks: ${missing.join(", ")}`);
  if (unexpected.length) problems.push(`main also grants: ${unexpected.join(", ")}`);
  if (granted.some((id) => id.includes(":"))) problems.push("main grants a core: or plugin permission");
  return problems;
}

/** Step 3: the test build adds only its own command and capability. */
function checkTestBuild(release, test, commands) {
  const problems = [];
  const before = appPermissions(release.acl);
  const after = appPermissions(test.acl);
  const added = [...after.keys()].filter((command) => !before.has(command));
  const removed = [...before.keys()].filter((command) => !after.has(command));
  if (JSON.stringify(added) !== JSON.stringify([TEST_COMMAND])) problems.push(`the test build adds: ${added}`);
  if (removed.length) problems.push(`the test build removes: ${removed}`);
  // The file capabilities are the release's own; the test build's one
  // addition is inline in its `--config` override, which is what grants
  // `e2e_report` (the generated capabilities file lists file capabilities).
  if (JSON.stringify(test.capabilities) !== JSON.stringify(release.capabilities)) {
    problems.push("the test build changes the file capabilities");
  }
  const override = JSON.parse(fs.readFileSync(path.join(NATIVE, "tauri.e2e.conf.json"), "utf-8"));
  const listed = override?.app?.security?.capabilities ?? [];
  const inline = listed.filter((entry) => typeof entry === "object");
  const named = listed.filter((entry) => typeof entry === "string");
  if (JSON.stringify(named) !== JSON.stringify(["main"])) problems.push(`the override names: ${named}`);
  if (inline.length !== 1 || inline[0].identifier !== "e2e-test"
      || JSON.stringify(inline[0].windows) !== JSON.stringify(["main"])) {
    problems.push(`the override's inline capabilities: ${JSON.stringify(inline)}`);
  }
  const allow = after.get(TEST_COMMAND)?.allow ?? [];
  if (JSON.stringify(inline[0]?.permissions) !== JSON.stringify(allow)) {
    problems.push(`e2e-test grants ${JSON.stringify(inline[0]?.permissions)}, expected ${JSON.stringify(allow)}`);
  }
  for (const command of commands) {
    if (JSON.stringify(after.get(command)) !== JSON.stringify(before.get(command))) {
      problems.push(`${command}'s permissions differ in the test build`);
    }
  }
  return problems;
}

const commands = commandsConstant();
if (commands.length !== 9) throw new Error(`COMMANDS has ${commands.length} names`);

const release = build("release", [], undefined);
const releaseProblems = checkRelease(release, commands);

const testTarget = path.join(os.tmpdir(), "comodor-manifest-e2e-target");
const test = build("e2e", ["--features", "e2e", "--config", path.join("src-tauri", "tauri.e2e.conf.json")],
                   testTarget);
const testProblems = checkTestBuild(release, test, commands);

// Step 4: the check catches a capability that grants the test command.
const scratch = structuredClone(release);
const testAllow = appPermissions(test.acl).get(TEST_COMMAND)?.allow[0] ?? "allow-e2e-report";
scratch.capabilities["main"].permissions.push(testAllow);
scratch.acl["__app-acl__"].permissions[testAllow] = test.acl["__app-acl__"].permissions[testAllow];
const caught = checkRelease(scratch, commands);

const report = {
  commands,
  release: releaseProblems,
  testBuild: testProblems,
  scratchCopyCaught: caught,
};
console.log(JSON.stringify(report, null, 2));
const ok = releaseProblems.length === 0 && testProblems.length === 0 && caught.length > 0;
console.log(ok ? "PASS release manifest" : "FAIL release manifest");
process.exit(ok ? 0 : 1);
