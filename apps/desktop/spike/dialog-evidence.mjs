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
 * platform says, a screenshot of the dialog's window alone (taken before it
 * is answered), the action taken, and the application's answer. Waits are
 * bounded searches for the dialog; a case that never answers ends at its
 * deadline and is recorded as such.
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

// -- Windows: the dialog's own window, UI Automation from its handle -----

const WINDOWS_NATIVE = String.raw`
using System; using System.Runtime.InteropServices; using System.Text;
public static class Dlg {
  public delegate bool EnumProc(IntPtr w, IntPtr d);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint data; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort vk; public ushort scan; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION u; }
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr d);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr w);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr w, out uint pid);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr w, StringBuilder t, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr w, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr w);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr w);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool on);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr w, uint m, IntPtr a, IntPtr b);
  [DllImport("user32.dll", SetLastError = true)] public static extern uint SendInput(uint n, INPUT[] i, int size);
  public static IntPtr Find(uint target, string title) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((w, d) => {
      uint pid; GetWindowThreadProcessId(w, out pid);
      if (pid != target || !IsWindowVisible(w)) return true;
      var t = new StringBuilder(256); GetWindowText(w, t, t.Capacity);
      if (t.ToString() == title) { found = w; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  public static void Raise(IntPtr w) {
    uint ignored; uint fg = GetWindowThreadProcessId(GetForegroundWindow(), out ignored); uint me = GetCurrentThreadId();
    bool joined = fg != 0 && fg != me && AttachThreadInput(me, fg, true);
    BringWindowToTop(w); SetForegroundWindow(w);
    if (joined) AttachThreadInput(me, fg, false);
  }
  public static uint ForegroundPid() { uint pid; GetWindowThreadProcessId(GetForegroundWindow(), out pid); return pid; }
  public static uint Key(ushort vk) {
    var i = new INPUT[2];
    i[0].type = 1; i[0].u.ki.vk = vk;
    i[1].type = 1; i[1].u.ki.vk = vk; i[1].u.ki.flags = 2;
    return SendInput(2, i, Marshal.SizeOf(typeof(INPUT)));
  }
  public static uint Click(int x, int y) {
    SetCursorPos(x, y);
    var i = new INPUT[2];
    i[0].type = 0; i[0].u.mi.flags = 2;
    i[1].type = 0; i[1].u.mi.flags = 4;
    return SendInput(2, i, Marshal.SizeOf(typeof(INPUT)));
  }
}
`;

function windowsAct(pid, action, shot) {
  const press = action.startsWith("press-") ? action.slice("press-".length) : "";
  const script = `
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
Add-Type -TypeDefinition @"
${WINDOWS_NATIVE}
"@
[void][Dlg]::SetProcessDPIAware()
$ends = (Get-Date).AddSeconds(${DIALOG_DEADLINE_S})
$hwnd = [IntPtr]::Zero
while ($hwnd -eq [IntPtr]::Zero -and (Get-Date) -lt $ends) { $hwnd = [Dlg]::Find(${pid}, '${TITLE}'); if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 200 } }
if ($hwnd -eq [IntPtr]::Zero) { @{ found = $false } | ConvertTo-Json -Compress; exit 0 }
$rect = New-Object Dlg+RECT
[void][Dlg]::GetWindowRect($hwnd, [ref]$rect)
$w = $rect.R - $rect.L; $h = $rect.B - $rect.T
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.L, $rect.T, 0, 0, $bmp.Size)
$bmp.Save('${shot.replaceAll("'", "''")}', [System.Drawing.Imaging.ImageFormat]::Png)
$A = [System.Windows.Automation.AutomationElement]
$root = $A::FromHandle($hwnd)
$all = @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition))
$elements = @($all | ForEach-Object { $b = $_.Current.BoundingRectangle
  @{ type = $_.Current.ControlType.ProgrammaticName; name = $_.Current.Name; focused = $_.Current.HasKeyboardFocus;
     x = [int]($b.X + $b.Width / 2); y = [int]($b.Y + $b.Height / 2) } })
$buttons = @($elements | Where-Object { $_.type -eq 'ControlType.Button' })
[Dlg]::Raise($hwnd)
$foreground = [Dlg]::ForegroundPid()
$acted = "none"
switch ('${action}') {
  'escape' { $sent = [Dlg]::Key(0x1B); $acted = "Escape by SendInput after raising the dialog (sent $sent events)" }
  'enter'  { $sent = [Dlg]::Key(0x0D); $acted = "Return by SendInput after raising the dialog (sent $sent events)" }
  'close'  { [void][Dlg]::PostMessage($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero); $acted = "WM_CLOSE posted to the dialog's window" }
  default {
    $target = $all | Where-Object { $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $_.Current.Name -eq '${press}' } | Select-Object -First 1
    if ($target) {
      $b = $target.Current.BoundingRectangle
      $sent = [Dlg]::Click([int]($b.X + $b.Width / 2), [int]($b.Y + $b.Height / 2))
      $acted = "pointer click (SendInput) at the centre of the button named '${press}' (sent $sent events)"
    } else { $acted = "no button named '${press}' in the dialog's UI Automation tree" }
  }
}
@{ found = $true; hwnd = $hwnd.ToInt64(); size = "$($w)x$($h)"; elements = $elements; buttons = $buttons;
   foregroundIsApp = ($foreground -eq ${pid}); acted = $acted } | ConvertTo-Json -Compress -Depth 5
`;
  const run = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], { encoding: "utf-8" });
  return { ...json(run.stdout), stderr: run.stderr.trim().slice(-600) || undefined };
}

// -- Linux: AT-SPI, xdotool, ImageMagick ---------------------------------

const ATSPI = String.raw`
import json, sys, threading, time
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
PID, ACTION, ENDS = int(sys.argv[1]), sys.argv[2], time.monotonic() + float(sys.argv[3])
LABELS = {"Save", "Discard", "Cancel"}

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

def label(node):
    return (node.get_name() or "").replace("_", "")

def search():
    apps = []
    for app in children(Atspi.get_desktop(0)):
        try:
            pid = app.get_process_id()
        except Exception:
            continue
        apps.append([pid, app.get_name()])
        if pid != PID:
            continue
        for window in children(app):
            buttons = [n for n in walk(window) if n.get_role() == Atspi.Role.PUSH_BUTTON and label(n) in LABELS]
            if len(buttons) >= 2:
                return window, buttons, apps
    return None, [], apps

window, buttons, apps = None, [], []
while time.monotonic() < ENDS and window is None:
    window, buttons, apps = search()
    if window is None:
        threading.Event().wait(0.25)
if window is None:
    print(json.dumps({"found": False, "applications": apps}))
    sys.exit(0)

def centre(node):
    try:
        e = node.get_extents(Atspi.CoordType.SCREEN)
        return {"x": e.x + e.width // 2, "y": e.y + e.height // 2}
    except Exception:
        return None

listed = []
for b in buttons:
    states = b.get_state_set()
    listed.append({"name": label(b), "focused": states.contains(Atspi.StateType.FOCUSED),
                   "default": states.contains(Atspi.StateType.DEFAULT), "centre": centre(b)})
acted = "none"
if ACTION.startswith("press-"):
    want = ACTION[len("press-"):]
    match = [b for b in buttons if label(b) == want]
    if match:
        action = match[0].get_action_iface()
        names = [action.get_action_name(i) for i in range(action.get_n_actions())] if action else []
        if names:
            index = names.index("click") if "click" in names else 0
            action.do_action(index)
            acted = "AT-SPI action '%s' on the button named '%s'" % (names[index], want)
        else:
            acted = "the button named '%s' has no AT-SPI action" % want
    else:
        acted = "no button named '%s'" % want
print(json.dumps({"found": True, "window": {"role": window.get_role_name(), "name": window.get_name()},
                  "buttons": listed, "acted": acted}))
`;

function linuxAct(pid, action, shot) {
  const located = spawnSync("timeout", [String(DIALOG_DEADLINE_S), "xdotool", "search", "--sync", "--onlyvisible",
                                        "--name", TITLE], { encoding: "utf-8" });
  const id = located.stdout.trim().split(/\s+/)[0];
  const captured = id ? spawnSync("import", ["-window", id, shot], { encoding: "utf-8" }) : null;
  const script = path.join(os.tmpdir(), "comodor-spike-dialog-atspi.py");
  fs.writeFileSync(script, ATSPI);
  const read = spawnSync("/usr/bin/python3", [script, String(pid), action.startsWith("press-") ? action : "read",
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

const MAC_SWIFT = `
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
let args = CommandLine.arguments
let pid = pid_t(args[1])!
let mode = args[2]
let wanted = args.count > 3 ? args[3] : ""
guard AXIsProcessTrusted() else { emit(["found": false, "error": "not trusted for Accessibility"]) }
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
if mode == "read" {
  let sheets = all(window) { role($0) == "AXSheet" }
  let container = sheets.first ?? window
  func named(_ attribute: String) -> String {
    guard let v = value(container, attribute) else { return "" }
    return title(v as! AXUIElement)
  }
  let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
  let ids = list.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) }.compactMap { $0[kCGWindowNumber as String] as? Int }
  emit(["found": true, "container": role(container), "windowRole": role(window),
        "buttons": buttons.map { ["name": title($0), "focused": (value($0, kAXFocusedAttribute as String) as? Bool) ?? false] as [String: Any] },
        "defaultButton": named(kAXDefaultButtonAttribute as String), "cancelButton": named(kAXCancelButtonAttribute as String),
        "windowIds": ids.map(String.init)])
}
if mode == "press" {
  guard let b = buttons.first(where: { title($0) == wanted }) else { emit(["acted": "no button titled " + wanted]) }
  let ok = AXUIElementPerformAction(b, kAXPressAction as CFString) == .success
  emit(["acted": ok ? "AXPress on the button titled " + wanted : "AXPress failed"])
}
let code: CGKeyCode = mode == "escape" ? 53 : 36
NSRunningApplication(processIdentifier: pid)?.activate(options: [])
let src = CGEventSource(stateID: .hidSystemState)
CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)?.post(tap: .cghidEventTap)
CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)?.post(tap: .cghidEventTap)
emit(["acted": (mode == "escape" ? "Escape" : "Return") + " posted (CGEvent, HID tap) after activating the application"])
`;

function macAct(pid, action, shot) {
  const script = path.join(os.tmpdir(), "comodor-spike-dialog.swift");
  fs.writeFileSync(script, MAC_SWIFT);
  // Read and capture first, then act: an answered dialog is gone before it can be captured.
  const read = spawnSync("swift", [script, String(pid), "read"], { encoding: "utf-8" });
  const seen = { ...json(read.stdout), stderr: read.stderr.trim().slice(-400) || undefined };
  const firstId = seen.windowIds?.[0];
  if (firstId) {
    const shotRun = spawnSync("screencapture", ["-x", "-o", "-l", firstId, shot], { encoding: "utf-8" });
    seen.captureError = shotRun.stderr.trim() || undefined;
  }
  if (!seen.found) return seen;
  if (action === "close") return { ...seen, acted: "not applicable: the alert has no close control" };
  const mode = action.startsWith("press-") ? "press" : action;
  const acted = spawnSync("swift", [script, String(pid), mode, action.replace(/^press-/, "")], { encoding: "utf-8" });
  return { ...seen, ...json(acted.stdout), actStderr: acted.stderr.trim().slice(-300) || undefined };
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
  if (process.platform === "win32") seen = windowsAct(app.pid, action, shot);
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
