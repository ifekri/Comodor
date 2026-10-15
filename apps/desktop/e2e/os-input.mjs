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
  const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT], {
    encoding: "utf-8", timeout: 60_000,
    env: { ...process.env, COMODOR_KEY_PID: String(pid), COMODOR_KEY_VKS: vks.join(","), COMODOR_KEY_UPS: ups.join(",") },
  });
  if (result.error) return unavailable(`PowerShell could not run: ${result.error.message}`);
  const said = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  if (result.status === 3) return unavailable(said.replace(/^capability-unavailable:\s*/, ""));
  if (result.status !== 0) return unavailable(`the injection failed: ${said}`);
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
    const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", "exit 0"], { timeout: 60_000 });
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
