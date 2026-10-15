/**
 * D2 T093: keys delivered by the operating system to the application's own
 * window, for the `key-delivery` scenario. Test only, and only when
 * `COMODOR_E2E_OS_LEVEL=1` (set by the CI desktop job): a local run never
 * types into whatever window a person has in front.
 *
 * Every injection is targeted: Windows checks, immediately before each
 * `SendInput`, that the foreground window belongs to the application's pid;
 * macOS posts to the application's pid (`CGEventPostToPid`); Linux focuses
 * the application's window on the harness's own Xvfb display and checks the
 * focus before each key. Anything the runner cannot do is reported as
 * `capability-unavailable` with its reason, never as a product failure.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export function osLevelEnabled() {
  return process.env.COMODOR_E2E_OS_LEVEL === "1";
}

const unavailable = (reason) => ({ ok: false, outcome: "capability-unavailable", reason });

/** One key: `key` ("q", "k", "F6", "Escape", "Tab"), with the primary modifier and Shift. */
function check(spec) {
  const known = ["q", "k", "F6", "Escape", "Tab"];
  return known.includes(spec?.key) ? null : `unknown key ${JSON.stringify(spec)}`;
}

// -- Windows -------------------------------------------------------------

const WINDOWS_VK = { q: 0x51, k: 0x4b, F6: 0x75, Escape: 0x1b, Tab: 0x09 };

const WINDOWS_SCRIPT = String.raw`
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class Keys {
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint data; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort vk; public ushort scan; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION u; }
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
  [DllImport("user32.dll", SetLastError = true)] public static extern uint SendInput(uint count, INPUT[] inputs, int size);
  public static uint Foreground() { uint pid; GetWindowThreadProcessId(GetForegroundWindow(), out pid); return pid; }
  public static uint Send(ushort[] vks, bool[] ups) {
    var inputs = new INPUT[vks.Length];
    for (int i = 0; i < vks.Length; i++) { inputs[i].type = 1; inputs[i].u.ki.vk = vks[i]; inputs[i].u.ki.flags = ups[i] ? 2u : 0u; }
    return SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
  }
}
"@
$target = [uint32]$env:COMODOR_KEY_PID
$foreground = [Keys]::Foreground()
if ($foreground -ne $target) { Write-Output "capability-unavailable: the foreground window belongs to process $foreground, not the application ($target)"; exit 3 }
$vks = [uint16[]]($env:COMODOR_KEY_VKS -split ",")
$ups = [bool[]]($env:COMODOR_KEY_UPS -split "," | ForEach-Object { $_ -eq "1" })
$sent = [Keys]::Send($vks, $ups)
if ($sent -ne $vks.Length) { Write-Output "capability-unavailable: SendInput sent $sent of $($vks.Length) events"; exit 3 }
Write-Output "sent"
`;

function pressWindows(pid, spec) {
  const modifiers = [...(spec.mod ? [0x11] : []), ...(spec.shift ? [0x10] : [])];
  const vks = [...modifiers, WINDOWS_VK[spec.key], WINDOWS_VK[spec.key], ...modifiers.toReversed()];
  const ups = [...modifiers.map(() => 0), 0, 1, ...modifiers.map(() => 1)];
  const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT], { windowsHide: true,
    encoding: "utf-8", timeout: 60_000,
    env: { ...process.env, COMODOR_KEY_PID: String(pid), COMODOR_KEY_VKS: vks.join(","), COMODOR_KEY_UPS: ups.join(",") },
  });
  if (result.error) return unavailable(`PowerShell could not run: ${result.error.message}`);
  const said = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  if (result.status === 3) return unavailable(said.replace(/^capability-unavailable:\s*/, ""));
  if (result.status !== 0) return unavailable(`the injection failed: ${said}`);
  return { ok: true };
}

/**
 * Windows refuses `SetForegroundWindow` to a process that did not receive the
 * last input event, so the application's own `set_focus` stays in the
 * background on a runner nobody types at. Unless the application is already
 * in front, this process sends an input event through `SendInput` (a pointer
 * move of zero, which makes it the one that received the last input), then
 * brings the application's window forward; it reads the foreground window's
 * process back either way.
 */
const WINDOWS_FOCUS_SCRIPT = String.raw`
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class Focus {
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint data; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort vk; public ushort scan; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION u; }
  public delegate bool EnumProc(IntPtr window, IntPtr data);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc proc, IntPtr data);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr window);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
  [DllImport("user32.dll", SetLastError = true)] public static extern uint SendInput(uint count, INPUT[] inputs, int size);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, System.Text.StringBuilder text, int size);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint attach, uint to, bool on);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  // The application's main window: visible, of the process, titled "Comodor".
  public static IntPtr Find(uint target) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((window, data) => {
      uint pid; GetWindowThreadProcessId(window, out pid);
      if (pid != target || !IsWindowVisible(window)) return true;
      var title = new System.Text.StringBuilder(256);
      GetWindowText(window, title, title.Capacity);
      if (title.ToString() == "Comodor") { found = window; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  // Join the foreground thread's input for the call, as Windows asks of a
  // process that is not in the foreground, then leave it again.
  public static void Raise(IntPtr window) {
    uint ignored;
    uint foreground = GetWindowThreadProcessId(GetForegroundWindow(), out ignored);
    uint mine = GetCurrentThreadId();
    bool joined = foreground != 0 && foreground != mine && AttachThreadInput(mine, foreground, true);
    BringWindowToTop(window);
    SetForegroundWindow(window);
    if (joined) AttachThreadInput(mine, foreground, false);
  }
  public static uint Foreground() { uint pid; GetWindowThreadProcessId(GetForegroundWindow(), out pid); return pid; }
  // An input event that means nothing to any window: the pointer moved by
  // zero. (A lone Alt would put the window in front into its menu mode.)
  public static uint Nudge() {
    var inputs = new INPUT[1];
    inputs[0].type = 0; inputs[0].u.mi.flags = 1u;
    return SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
  }
}
"@
$target = [uint32]$env:COMODOR_KEY_PID
$window = [Focus]::Find($target)
if ($window -eq [IntPtr]::Zero) { Write-Output "capability-unavailable: no visible window titled Comodor in process $target"; exit 3 }
if ([Focus]::Foreground() -ne $target) {
  if ([Focus]::Nudge() -ne 1) { Write-Output "capability-unavailable: SendInput could not send an input event"; exit 3 }
  if ([Focus]::IsIconic($window)) { [void][Focus]::ShowWindow($window, 9) }
  [Focus]::Raise($window)
}
$foreground = [Focus]::Foreground()
if ($foreground -ne $target) { Write-Output "capability-unavailable: the foreground window belongs to process $foreground, not the application ($target)"; exit 3 }
Write-Output "focused"
`;

/** Bring the application with `pid` to the foreground (Windows), and confirm it. */
export function focusWindows(pid) {
  const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", WINDOWS_FOCUS_SCRIPT], { windowsHide: true,
    encoding: "utf-8", timeout: 60_000, env: { ...process.env, COMODOR_KEY_PID: String(pid) },
  });
  if (result.error) return unavailable(`PowerShell could not run: ${result.error.message}`);
  const said = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  if (result.status === 3) return unavailable(said.replace(/^capability-unavailable:\s*/, ""));
  if (result.status !== 0) return unavailable(`focusing failed: ${said}`);
  return { ok: true };
}

// -- macOS ---------------------------------------------------------------

const MAC_KEYCODE = { q: 12, k: 40, F6: 97, Escape: 53, Tab: 48 };

const MAC_SCRIPT = `
import ApplicationServices
import CoreGraphics
import Foundation

let arguments = CommandLine.arguments
guard AXIsProcessTrusted() else {
  print("capability-unavailable: this process is not trusted for Accessibility"); exit(3)
}
if #available(macOS 10.15, *) {
  guard CGPreflightPostEventAccess() else {
    print("capability-unavailable: this process has no access to post keyboard events"); exit(3)
  }
}
guard arguments.count >= 3, let pid = pid_t(arguments[1]), let code = CGKeyCode(arguments[2]) else {
  print("usage: press-key <pid> <keycode> [cmd] [shift]"); exit(2)
}
var flags = CGEventFlags()
if arguments.contains("cmd") { flags.insert(.maskCommand) }
if arguments.contains("shift") { flags.insert(.maskShift) }
guard let down = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true),
      let up = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false) else {
  print("capability-unavailable: no keyboard event could be made"); exit(3)
}
down.flags = flags
up.flags = flags
down.postToPid(pid)
up.postToPid(pid)
print("sent")
`;

let macHelper;

function pressMac(pid, spec) {
  if (!macHelper) {
    macHelper = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "comodor-keys-")), "press-key.swift");
    fs.writeFileSync(macHelper, MAC_SCRIPT);
  }
  const args = [macHelper, String(pid), String(MAC_KEYCODE[spec.key]), ...(spec.mod ? ["cmd"] : []),
                ...(spec.shift ? ["shift"] : [])];
  const result = spawnSync("swift", args, { encoding: "utf-8", timeout: 180_000 });
  if (result.error) return unavailable(`swift could not run: ${result.error.message}`);
  const said = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  if (result.status === 3) return unavailable(said.replace(/^capability-unavailable:\s*/, ""));
  if (result.status !== 0) return unavailable(`the injection failed: ${said}`);
  return { ok: true };
}

// -- Linux ---------------------------------------------------------------

const XDOTOOL_KEY = { q: "q", k: "k", F6: "F6", Escape: "Escape", Tab: "Tab" };

function xdotool(...args) {
  return spawnSync("timeout", ["20", "xdotool", ...args], { encoding: "utf-8" });
}

/** The application's visible window on this display, given focus without a window manager. */
export function focusLinux(pid) {
  if (!process.env.DISPLAY) return unavailable("no DISPLAY: the harness's Xvfb is not running");
  const found = xdotool("search", "--sync", "--onlyvisible", "--pid", String(pid));
  if (found.error || found.status !== 0) {
    return unavailable(`xdotool found no window for the application: ${found.error?.message ?? found.stderr}`);
  }
  const window = found.stdout.trim().split("\n").filter(Boolean).at(-1);
  // windowfocus sets the input focus itself (XSetInputFocus): Xvfb has no
  // window manager, so windowactivate cannot be used.
  const focused = xdotool("windowfocus", "--sync", window);
  if (focused.status !== 0) return unavailable(`xdotool could not focus the window: ${focused.stderr}`);
  return { ok: true, window };
}

function pressLinux(pid, spec) {
  const target = focusLinux(pid);
  if (!target.ok) return target;
  const now = xdotool("getwindowfocus");
  const focus = now.stdout.trim();
  if (focus !== target.window) {
    const owner = xdotool("getwindowpid", focus).stdout.trim();
    if (owner !== String(pid)) {
      return unavailable(`the input focus is on window ${focus} (process ${owner || "unknown"}), not the application`);
    }
  }
  const name = [...(spec.mod ? ["ctrl"] : []), ...(spec.shift ? ["shift"] : []), XDOTOOL_KEY[spec.key]].join("+");
  const sent = xdotool("key", name);
  if (sent.status !== 0) return unavailable(`xdotool could not send ${name}: ${sent.stderr}`);
  return { ok: true };
}

// -- The harness's entry points ----------------------------------------------

/** Preflight what a platform needs, without sending anything. */
export function preflight() {
  if (!osLevelEnabled()) return { ok: false, outcome: "not-run", reason: "operating-system-level evidence disabled" };
  if (process.platform === "win32") {
    const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", "exit 0"], { windowsHide: true, timeout: 60_000 });
    return result.status === 0 ? { ok: true } : unavailable("PowerShell is not available");
  }
  if (process.platform === "darwin") {
    const result = spawnSync("swift", ["--version"], { encoding: "utf-8", timeout: 120_000 });
    return result.status === 0 ? { ok: true } : unavailable("swift is not available");
  }
  const result = spawnSync("xdotool", ["version"], { encoding: "utf-8" });
  if (result.error || result.status !== 0) return unavailable("xdotool is not installed");
  return process.env.DISPLAY ? { ok: true } : unavailable("no DISPLAY: the harness's Xvfb is not running");
}

/** Deliver one key to the application with `pid`, the way a person's keyboard does. */
export function pressKey(pid, spec) {
  if (!osLevelEnabled()) return { ok: false, outcome: "not-run", reason: "operating-system-level evidence disabled" };
  const problem = check(spec);
  if (problem) return { ok: false, outcome: "harness-error", reason: problem };
  if (process.platform === "win32") return pressWindows(pid, spec);
  if (process.platform === "darwin") return pressMac(pid, spec);
  return pressLinux(pid, spec);
}
