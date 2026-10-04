#!/usr/bin/env node
/**
 * Evidence that the real system folder chooser opens where the application
 * says (T095, SC-017, quickstart §7).
 *
 * The release build — the real dialog, not the test build's double — is
 * launched twice in a row with no workspace argument, each time with a
 * different folder stored as the last one chosen. When the dialog's window
 * exists, that window alone is captured — never the whole screen, which on a
 * person's machine shows whatever else they have open — and on Windows the
 * dialog's address bar is also read through UI Automation. Then the
 * application is ended. Nothing is chosen and no Core starts.
 *
 *   node e2e/chooser-evidence.mjs [--skip-build]
 *
 * Output: `e2e/out/chooser-evidence/` — one screenshot per launch and
 * `evidence.json`. The person reviewing the PR judges the images; this tool
 * only records them.
 */

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESKTOP = path.dirname(HERE);
const OUT = path.join(HERE, "out", "chooser-evidence");
const IDENTIFIER = "ai.comodor.desktop";
const TITLE = "Choose a workspace for Comodor";
/** How long the dialog may take to appear before the launch fails. */
const DIALOG_DEADLINE_S = 60;

function configDir() {
  if (process.platform === "win32") return path.join(process.env.APPDATA, IDENTIFIER);
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", IDENTIFIER);
  }
  return path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config"), IDENTIFIER);
}

function executable() {
  const target = process.env.CARGO_TARGET_DIR
    ? path.resolve(process.env.CARGO_TARGET_DIR) : path.join(DESKTOP, "src-tauri", "target");
  return path.join(target, "release", process.platform === "win32" ? "comodor-desktop.exe" : "comodor-desktop");
}

function buildRelease() {
  const cli = createRequire(import.meta.url).resolve("@tauri-apps/cli/tauri.js");
  const result = spawnSync(process.execPath, [cli, "build", "--no-bundle"], { cwd: DESKTOP, stdio: "inherit" });
  if (result.status !== 0) throw new Error("the release build failed");
}

/** Wait for the dialog, capture its window alone into `shot`; what was read. */
function capture(shot) {
  if (process.platform === "win32") {
    const script = `
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
Add-Type -Namespace Native -Name Dpi -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][Native.Dpi]::SetProcessDPIAware()
$name = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '${TITLE}')
$ends = (Get-Date).AddSeconds(${DIALOG_DEADLINE_S})
$dialog = $null
while (-not $dialog -and (Get-Date) -lt $ends) {
  $dialog = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $name)
}
if (-not $dialog) { Write-Output 'NO-DIALOG'; exit 2 }
$all = $dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($e in $all) { if ($e.Current.Name -like 'Address:*') { Write-Output $e.Current.Name; break } }
# The dialog's own rectangle only.
$r = $dialog.Current.BoundingRectangle
$bmp = New-Object System.Drawing.Bitmap ([int]$r.Width), ([int]$r.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen([int]$r.X, [int]$r.Y, 0, 0, $bmp.Size)
$bmp.Save('${shot.replaceAll("'", "''")}', [System.Drawing.Imaging.ImageFormat]::Png)
`;
    const run = spawnSync("powershell", ["-NoProfile", "-Command", script], { encoding: "utf-8" });
    return { found: run.status === 0, read: run.stdout.trim(), error: run.stderr.trim() };
  }
  if (process.platform === "linux") {
    const found = spawnSync("timeout", [String(DIALOG_DEADLINE_S), "xdotool", "search", "--sync", "--name", TITLE],
                            { encoding: "utf-8" });
    if (found.status !== 0) return { found: false, read: "", error: found.stderr.trim() };
    const id = found.stdout.trim().split(/\s+/)[0];
    const shotRun = spawnSync("import", ["-window", id, shot], { encoding: "utf-8" });
    return { found: true, read: `window ${id}`, error: shotRun.stderr.trim() };
  }
  // macOS: the panel is a second window of the application's process (or of
  // the system's open-and-save panel service), read from the window list.
  const swift = `
import CoreGraphics
import Foundation
let deadline = Date().addingTimeInterval(${DIALOG_DEADLINE_S})
while Date() < deadline {
  let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
  let owners = list.compactMap { $0[kCGWindowOwnerName as String] as? String }
  let ours = list.filter { ($0[kCGWindowOwnerName as String] as? String) == "comodor-desktop" }
  let panel = list.first { (($0[kCGWindowOwnerName as String] as? String) ?? "").contains("Open and Save Panel") }
    ?? (ours.count >= 2 ? ours.min { (($0[kCGWindowNumber as String] as? Int) ?? 0) > (($1[kCGWindowNumber as String] as? Int) ?? 0) } : nil)
  if let panel = panel, let id = panel[kCGWindowNumber as String] as? Int {
    print(id)
    exit(0)
  }
}
exit(2)
`;
  const script = path.join(os.tmpdir(), "comodor-chooser-wait.swift");
  fs.writeFileSync(script, swift);
  const found = spawnSync("swift", [script], { encoding: "utf-8" });
  if (found.status !== 0) return { found: false, read: "", error: found.stderr.trim() };
  const id = found.stdout.trim();
  const shotRun = spawnSync("screencapture", ["-x", "-o", "-l", id, shot], { encoding: "utf-8" });
  return { found: true, read: `window ${id}`, error: shotRun.stderr.trim() };
}

if (!process.argv.includes("--skip-build")) buildRelease();
if (process.platform === "linux" && !process.env.DISPLAY) {
  // Once, under a display (CI has none of its own).
  const wrapped = spawnSync("xvfb-run", ["-a", "-s", "-screen 0 1280x800x24", process.execPath,
                                         fileURLToPath(import.meta.url), "--skip-build"], { stdio: "inherit" });
  process.exit(wrapped.status ?? 1);
}

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });
const prefs = path.join(configDir(), "preferences.json");
const saved = fs.existsSync(prefs) ? fs.readFileSync(prefs) : null;
const launches = [];
try {
  for (const n of [1, 2]) {
    const stored = fs.mkdtempSync(path.join(os.tmpdir(), `comodor-chooser-start-${n}-`));
    fs.mkdirSync(path.dirname(prefs), { recursive: true });
    fs.writeFileSync(prefs, JSON.stringify({ version: 1, last_selected_folder: stored }));
    const app = spawn(executable(), [], { stdio: "ignore" });
    const shot = path.join(OUT, `launch-${n}-${process.platform}.png`);
    const seen = capture(shot);
    app.kill("SIGKILL");
    await new Promise((resolve) => app.once("exit", resolve));
    launches.push({ launch: n, platform: process.platform, startFolder: stored,
                    dialog: seen.found, read: seen.read, screenshot: fs.existsSync(shot) ? path.basename(shot) : null,
                    error: seen.error || undefined });
  }
} finally {
  if (saved) fs.writeFileSync(prefs, saved);
  else fs.rmSync(prefs, { force: true });
}
fs.writeFileSync(path.join(OUT, "evidence.json"), JSON.stringify(launches, null, 2));
console.log(JSON.stringify(launches, null, 2));
const ok = launches.every((launch) => launch.dialog && launch.screenshot);
console.log(ok ? "RECORDED chooser evidence" : "NOT RECORDED chooser evidence");
process.exit(ok ? 0 : 1);
