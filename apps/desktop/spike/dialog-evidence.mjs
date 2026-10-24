#!/usr/bin/env node
/**
 * D3 spike (throwaway, never merged; spike/README.md): the real three-button
 * native message dialog, answered from outside the application.
 *
 * The test build (built by `e2e/harness.mjs`) is launched once per case with
 * `COMODOR_SPIKE_DIALOG=1`: it shows "2 files have unsaved changes." with the
 * buttons Save / Discard / Cancel (`YesNoCancelCustom`), parented to the
 * window, and prints the button it received. For every case this records the
 * labels and roles read from the dialog through the platform's accessibility
 * interface, which button the dialog marks default or cancel where the
 * platform says, a screenshot of the dialog's window alone, the action taken,
 * and the application's answer. Nothing here waits by elapsed time for a
 * result: waits are bounded searches for the dialog, and a case that never
 * answers ends at its deadline and is recorded as such.
 *
 *   node spike/dialog-evidence.mjs
 *
 * Output: `e2e/out/spike-dialog/` — `evidence.json` and one screenshot per
 * case.
 */

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESKTOP = path.dirname(HERE);
const OUT = path.join(DESKTOP, "e2e", "out", "spike-dialog");
const TITLE = "Comodor spike: unsaved changes";
const PREFIX = "@@comodor-spike-dialog@@ ";
const DIALOG_DEADLINE_S = 60;
const ANSWER_DEADLINE_MS = 90_000;

const CASES = ["press-Save", "press-Discard", "press-Cancel", "escape", "enter", "close"];

if (process.platform === "linux" && !process.env.DISPLAY) {
  const wrapped = spawnSync("dbus-run-session", ["--", "xvfb-run", "-a", "-s", "-screen 0 1600x1000x24",
                                                 process.execPath, fileURLToPath(import.meta.url)],
                            { stdio: "inherit" });
  process.exit(wrapped.status ?? 1);
}

function executable() {
  const target = process.env.CARGO_TARGET_DIR
    ? path.resolve(process.env.CARGO_TARGET_DIR) : path.join(DESKTOP, "src-tauri", "target");
  return path.join(target, "release", process.platform === "win32" ? "comodor-desktop.exe" : "comodor-desktop");
}

function json(text) {
  try { return JSON.parse(text.trim().split("\n").pop() ?? ""); } catch { return { unparsed: text.slice(-600) }; }
}

// -- Windows: UI Automation ----------------------------------------------

function windowsAct(action, shot) {
  const press = action.startsWith("press-") ? action.slice("press-".length) : "";
  const script = `
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
Add-Type -Namespace Native -Name Dpi -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr w);'
[void][Native.Dpi]::SetProcessDPIAware()
$A = [System.Windows.Automation.AutomationElement]
$name = New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, '${TITLE}')
$ends = (Get-Date).AddSeconds(${DIALOG_DEADLINE_S})
$dialog = $null
while (-not $dialog -and (Get-Date) -lt $ends) { $dialog = $A::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $name) }
if (-not $dialog) { @{ found = $false } | ConvertTo-Json -Compress; exit 0 }
$isButton = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$buttons = @($dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants, $isButton) | ForEach-Object {
  @{ name = $_.Current.Name; focused = $_.Current.HasKeyboardFocus; automationId = $_.Current.AutomationId } })
$r = $dialog.Current.BoundingRectangle
$bmp = New-Object System.Drawing.Bitmap ([int]$r.Width), ([int]$r.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen([int]$r.X, [int]$r.Y, 0, 0, $bmp.Size)
$bmp.Save('${shot.replaceAll("'", "''")}', [System.Drawing.Imaging.ImageFormat]::Png)
$acted = "none"
$handle = [System.IntPtr]$dialog.Current.NativeWindowHandle
switch ('${action}') {
  'escape' { [void][Native.Dpi]::SetForegroundWindow($handle); $dialog.SetFocus(); [System.Windows.Forms.SendKeys]::SendWait("{ESC}"); $acted = "Escape sent (SendKeys) to the focused dialog" }
  'enter'  { [void][Native.Dpi]::SetForegroundWindow($handle); $dialog.SetFocus(); [System.Windows.Forms.SendKeys]::SendWait("{ENTER}"); $acted = "Enter sent (SendKeys) to the focused dialog" }
  'close'  {
    $pattern = $null
    if ($dialog.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$pattern)) { $pattern.Close(); $acted = "WindowPattern.Close" }
    else { [void][Native.Dpi]::SetForegroundWindow($handle); [System.Windows.Forms.SendKeys]::SendWait("%{F4}"); $acted = "Alt+F4 sent (no WindowPattern)" }
  }
  default {
    $want = New-Object System.Windows.Automation.AndCondition($isButton, (New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, '${press}')))
    $button = $dialog.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $want)
    if ($button) { $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); $acted = "InvokePattern on the button named '${press}'" }
    else { $acted = "no button named '${press}'" }
  }
}
@{ found = $true; buttons = $buttons; bounds = "$($r.Width)x$($r.Height)"; acted = $acted; className = $dialog.Current.ClassName } | ConvertTo-Json -Compress -Depth 4
`;
  const run = spawnSync("powershell", ["-NoProfile", "-Command", script], { encoding: "utf-8" });
  return { ...json(run.stdout), stderr: run.stderr.trim().slice(-600) || undefined };
}

// -- Linux: AT-SPI, xdotool, ImageMagick ---------------------------------

const ATSPI = String.raw`
import json, sys, threading, time
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
PID, TITLE, ACTION, ENDS = int(sys.argv[1]), sys.argv[2], sys.argv[3], time.monotonic() + float(sys.argv[4])

def children(node):
    for index in range(node.get_child_count()):
        child = node.get_child_at_index(index)
        if child is not None:
            yield child

def walk(node, depth=0):
    yield node
    if depth < 40:
        for child in children(node):
            yield from walk(child, depth + 1)

def dialog():
    for app in children(Atspi.get_desktop(0)):
        try:
            if app.get_process_id() != PID:
                continue
        except Exception:
            continue
        for window in children(app):
            if window.get_name() == TITLE:
                return window
    return None

found = None
while time.monotonic() < ENDS and found is None:
    found = dialog()
    if found is None:
        threading.Event().wait(0.25)
if found is None:
    print(json.dumps({"found": False}))
    sys.exit(0)
buttons = []
for node in walk(found):
    if node.get_role() == Atspi.Role.PUSH_BUTTON:
        states = node.get_state_set()
        buttons.append({"name": node.get_name(), "focused": states.contains(Atspi.StateType.FOCUSED),
                        "default": states.contains(Atspi.StateType.DEFAULT), "node": node})
acted = "none"
if ACTION.startswith("press-"):
    want = ACTION[len("press-"):]
    match = [b for b in buttons if b["name"].replace("_", "") == want]
    if match:
        action = match[0]["node"].get_action_iface()
        names = [action.get_action_name(i) for i in range(action.get_n_actions())]
        index = names.index("click") if "click" in names else 0
        action.do_action(index)
        acted = "AT-SPI action '%s' on the button named '%s'" % (names[index] if names else "?", want)
    else:
        acted = "no button named '%s'" % want
print(json.dumps({"found": True, "role": found.get_role_name(), "acted": acted,
                  "buttons": [{k: v for k, v in b.items() if k != "node"} for b in buttons]}))
`;

function linuxAct(pid, action, shot) {
  const located = spawnSync("timeout", [String(DIALOG_DEADLINE_S), "xdotool", "search", "--sync", "--onlyvisible",
                                        "--name", TITLE], { encoding: "utf-8" });
  const id = located.stdout.trim().split(/\s+/)[0];
  const captured = id ? spawnSync("import", ["-window", id, shot], { encoding: "utf-8" }) : null;
  const script = path.join(os.tmpdir(), "comodor-spike-dialog-atspi.py");
  fs.writeFileSync(script, ATSPI);
  // Read the dialog (and press a button for press-* cases) through AT-SPI.
  const read = spawnSync("/usr/bin/python3", [script, String(pid), TITLE, action.startsWith("press-") ? action : "read",
                                              String(DIALOG_DEADLINE_S)], { encoding: "utf-8" });
  const seen = { ...json(read.stdout), xwindow: id || null, captureError: captured?.stderr.trim() || undefined,
                 atspiStderr: read.stderr.trim().slice(-400) || undefined };
  if (!id || action.startsWith("press-")) return seen;
  if (action === "close") {
    return { ...seen, acted: "not applicable: Xvfb runs no window manager, so nothing can deliver a close request" };
  }
  const focus = spawnSync("xdotool", ["windowfocus", "--sync", id], { encoding: "utf-8" });
  const key = spawnSync("xdotool", ["key", "--clearmodifiers", action === "escape" ? "Escape" : "Return"],
                        { encoding: "utf-8" });
  return { ...seen, acted: `${action === "escape" ? "Escape" : "Return"} sent by xdotool (XTEST) after windowfocus`,
           focusStatus: focus.status, keyStatus: key.status, keyStderr: key.stderr.trim() || undefined };
}

// -- macOS: Accessibility, CoreGraphics ----------------------------------

function macAct(pid, action, shot) {
  const press = action.startsWith("press-") ? action.slice("press-".length) : "";
  const swift = `
import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
func value(_ e: AXUIElement, _ name: String) -> AnyObject? {
  var v: AnyObject?
  return AXUIElementCopyAttributeValue(e, name as CFString, &v) == .success ? v : nil
}
func kids(_ e: AXUIElement) -> [AXUIElement] { value(e, kAXChildrenAttribute as String) as? [AXUIElement] ?? [] }
func role(_ e: AXUIElement) -> String { value(e, kAXRoleAttribute as String) as? String ?? "" }
func title(_ e: AXUIElement) -> String { value(e, kAXTitleAttribute as String) as? String ?? "" }
func all(_ e: AXUIElement, _ depth: Int = 0, _ keep: (AXUIElement) -> Bool) -> [AXUIElement] {
  var out: [AXUIElement] = keep(e) ? [e] : []
  if depth < 30 { for k in kids(e) { out += all(k, depth + 1, keep) } }
  return out
}
func emit(_ o: [String: Any]) -> Never {
  print(String(data: try! JSONSerialization.data(withJSONObject: o), encoding: .utf8)!); exit(0)
}
guard AXIsProcessTrusted() else { emit(["found": false, "error": "not trusted for Accessibility"]) }
let pid = pid_t(${pid})
let app = AXUIElementCreateApplication(pid)
let deadline = Date().addingTimeInterval(${DIALOG_DEADLINE_S})
var holder: AXUIElement? = nil
var buttons: [AXUIElement] = []
while Date() < deadline {
  for w in value(app, kAXWindowsAttribute as String) as? [AXUIElement] ?? [] {
    let found = all(w) { role($0) == "AXButton" && ["Save", "Discard", "Cancel"].contains(title($0)) }
    if found.count >= 2 { holder = w; buttons = found; break }
  }
  if holder != nil { break }
  usleep(200_000)
}
guard let window = holder else { emit(["found": false]) }
let sheets = all(window) { role($0) == "AXSheet" }
let container = sheets.first ?? window
let defaultButton = (value(container, kAXDefaultButtonAttribute as String)).map { title($0 as! AXUIElement) } ?? ""
let cancelButton = (value(container, kAXCancelButtonAttribute as String)).map { title($0 as! AXUIElement) } ?? ""
let listed = buttons.map { ["name": title($0), "focused": (value($0, kAXFocusedAttribute as String) as? Bool) ?? false] as [String: Any] }
// The window that holds the alert, captured alone (a sheet is drawn with its window).
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
let ours = list.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) }
let ids = ours.compactMap { $0[kCGWindowNumber as String] as? Int }
var acted = "none"
let action = "${action}"
func key(_ code: CGKeyCode) {
  NSRunningApplication(processIdentifier: pid)?.activate(options: [])
  usleep(300_000)
  let src = CGEventSource(stateID: .hidSystemState)
  CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)?.post(tap: .cghidEventTap)
  CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)?.post(tap: .cghidEventTap)
}
var shotIds = ids.map(String.init)
if action == "escape" { acted = "Escape posted (CGEvent, HID tap) after activating the application" }
else if action == "enter" { acted = "Return posted (CGEvent, HID tap) after activating the application" }
else if action == "close" { acted = "not applicable: the alert is a sheet with no close control" }
else if let b = buttons.first(where: { title($0) == "${press}" }) {
  acted = AXUIElementPerformAction(b, kAXPressAction as CFString) == .success ? "AXPress on the button titled '${press}'" : "AXPress failed"
} else { acted = "no button titled '${press}'" }
emit(["found": true, "container": role(container), "buttons": listed, "defaultButton": defaultButton,
      "cancelButton": cancelButton, "windowIds": shotIds, "acted": acted,
      "postKey": action == "escape" ? 53 : action == "enter" ? 36 : -1])
`;
  const script = path.join(os.tmpdir(), "comodor-spike-dialog.swift");
  fs.writeFileSync(script, swift);
  // First pass: read and (for press-*) act; for keys, the screenshot comes first.
  const run = spawnSync("swift", [script], { encoding: "utf-8" });
  const seen = { ...json(run.stdout), stderr: run.stderr.trim().slice(-400) || undefined };
  const firstId = seen.windowIds?.[0];
  if (firstId) {
    const shotRun = spawnSync("screencapture", ["-x", "-o", "-l", firstId, shot], { encoding: "utf-8" });
    seen.captureError = shotRun.stderr.trim() || undefined;
  }
  if (seen.found && (action === "escape" || action === "enter")) {
    const code = action === "escape" ? 53 : 36;
    const post = `
import AppKit
import CoreGraphics
NSRunningApplication(processIdentifier: ${pid})?.activate(options: [])
usleep(300_000)
let src = CGEventSource(stateID: .hidSystemState)
CGEvent(keyboardEventSource: src, virtualKey: ${code}, keyDown: true)?.post(tap: .cghidEventTap)
CGEvent(keyboardEventSource: src, virtualKey: ${code}, keyDown: false)?.post(tap: .cghidEventTap)
`;
    const keyScript = path.join(os.tmpdir(), "comodor-spike-key.swift");
    fs.writeFileSync(keyScript, post);
    const keyed = spawnSync("swift", [keyScript], { encoding: "utf-8" });
    seen.keyStatus = keyed.status;
  }
  return seen;
}

// -- the cases -----------------------------------------------------------

async function runCase(action) {
  const shot = path.join(OUT, `${action}-${process.platform}.png`);
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "comodor-spike-dialog-"));
  // The test build's own data folder, so no real profile is touched.
  const env = { ...process.env, COMODOR_SPIKE_DIALOG: "1", COMODOR_E2E_SCENARIO: "spike-idle",
                COMODOR_DESKTOP_DATA_DIR: data };
  const app = spawn(executable(), [], { env, stdio: ["ignore", "pipe", "pipe"] });
  let answer = null;
  const ended = new Promise((resolve) => {
    createInterface({ input: app.stdout }).on("line", (line) => {
      if (line.startsWith(PREFIX)) answer = JSON.parse(line.slice(PREFIX.length));
    });
    app.once("exit", (code, signal) => resolve({ code, signal }));
  });
  const stderr = [];
  app.stderr.on("data", (chunk) => stderr.push(String(chunk)));
  let seen;
  if (process.platform === "win32") seen = windowsAct(action, shot);
  else if (process.platform === "darwin") seen = macAct(app.pid, action, shot);
  else seen = linuxAct(app.pid, action, shot);
  const deadline = new Promise((resolve) => {
    const timer = setTimeout(() => resolve("deadline"), ANSWER_DEADLINE_MS);
    ended.then(() => clearTimeout(timer));
  });
  const outcome = await Promise.race([ended, deadline]);
  if (outcome === "deadline") {
    app.kill("SIGKILL");
    await ended;
  }
  return { case: action, platform: process.platform, dialog: seen, answer,
           exit: outcome === "deadline" ? "killed at the deadline (no answer)" : outcome,
           screenshot: fs.existsSync(shot) ? path.basename(shot) : null,
           stderr: stderr.join("").trim().slice(-800) || undefined };
}

if (!fs.existsSync(executable())) {
  console.error(`no test build at ${executable()}: run e2e/harness.mjs first`);
  process.exit(1);
}
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });
const results = [];
for (const action of CASES) {
  const result = await runCase(action);
  console.log(JSON.stringify(result));
  results.push(result);
}
fs.writeFileSync(path.join(OUT, "evidence.json"), JSON.stringify(results, null, 2));
// Recorded, not judged: the evidence is the result. Exit 0 so every
// platform's record is kept; the report reads evidence.json.
console.log(`RECORDED ${results.length} dialog cases on ${process.platform}`);
