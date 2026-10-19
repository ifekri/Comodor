/**
 * D2 (SC-018): the application's real window, captured by the operating
 * system — what the WebView drew, not a rendering of the page elsewhere.
 *
 * - Windows: `PrintWindow` of the main window's client area with its full
 *   rendered content (the WebView2's composition included); if that comes
 *   back blank, the client area's pixels on screen.
 * - macOS: `screencapture -l` of the window by its number in the window list,
 *   without the shadow; the image includes the title bar.
 * - Linux: ImageMagick's `import` of the X window under Xvfb, which has no
 *   window manager: the client area.
 *
 * Each returns `{ ok: true, width, height, method }` or `{ ok: false, reason }`.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const WINDOWS_SCRIPT = String.raw`
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System; using System.Drawing; using System.Runtime.InteropServices; using System.Text;
public static class Shot {
  public delegate bool EnumProc(IntPtr window, IntPtr data);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc proc, IntPtr data);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, StringBuilder text, int size);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr window, out RECT rect);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr window, ref POINT point);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr window, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  // The application's main window: visible, of the process, titled "Comodor".
  public static IntPtr Find(uint target) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((window, data) => {
      uint pid; GetWindowThreadProcessId(window, out pid);
      if (pid != target || !IsWindowVisible(window)) return true;
      var title = new StringBuilder(256);
      GetWindowText(window, title, title.Capacity);
      if (title.ToString() == "Comodor") { found = window; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  // A sampled image with a single colour drew nothing.
  public static bool Blank(Bitmap image) {
    Color first = image.GetPixel(0, 0);
    for (int y = 0; y < image.Height; y += Math.Max(1, image.Height / 24))
      for (int x = 0; x < image.Width; x += Math.Max(1, image.Width / 24))
        if (image.GetPixel(x, y) != first) return false;
    return true;
  }
}
"@
[void][Shot]::SetProcessDPIAware()
$window = [Shot]::Find([uint32]$env:COMODOR_SHOT_PID)
if ($window -eq [IntPtr]::Zero) { Write-Output "no visible window titled Comodor for the application"; exit 3 }
$rect = New-Object Shot+RECT
[void][Shot]::GetClientRect($window, [ref]$rect)
if ($rect.Right -le 0 -or $rect.Bottom -le 0) { Write-Output "the window has no client area"; exit 3 }
$image = New-Object System.Drawing.Bitmap $rect.Right, $rect.Bottom
$graphics = [System.Drawing.Graphics]::FromImage($image)
$hdc = $graphics.GetHdc()
# PW_CLIENTONLY | PW_RENDERFULLCONTENT
$printed = [Shot]::PrintWindow($window, $hdc, 3)
$graphics.ReleaseHdc($hdc)
$method = "PrintWindow"
if (-not $printed -or [Shot]::Blank($image)) {
  $origin = New-Object Shot+POINT
  [void][Shot]::ClientToScreen($window, [ref]$origin)
  $graphics.CopyFromScreen($origin.X, $origin.Y, 0, 0, $image.Size)
  $method = "screen"
}
$graphics.Dispose()
$image.Save($env:COMODOR_SHOT_FILE, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "$($rect.Right) $($rect.Bottom) $method"
`;

function captureWindows(pid, file) {
  const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT], {
    windowsHide: true, encoding: "utf-8", timeout: 120_000,
    env: { ...process.env, COMODOR_SHOT_PID: String(pid), COMODOR_SHOT_FILE: file },
  });
  if (result.error) return { ok: false, reason: `PowerShell could not run: ${result.error.message}` };
  const said = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  if (result.status !== 0) return { ok: false, reason: said || `PowerShell ended with ${result.status}` };
  const [width, height, method] = said.split(/\s+/).slice(-3);
  return { ok: true, width: Number(width), height: Number(height), method };
}

// -- macOS ---------------------------------------------------------------

const MAC_FIND = `
import CoreGraphics
import Foundation
guard CommandLine.arguments.count >= 2, let pid = Int(CommandLine.arguments[1]) else { exit(2) }
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
let ours = list.filter {
  ($0[kCGWindowOwnerPID as String] as? Int) == pid && ($0[kCGWindowLayer as String] as? Int) == 0
}
guard let window = ours.first, let id = window[kCGWindowNumber as String] as? Int else { exit(3) }
print(id)
`;

/** The window's number, once per process: the swift helper takes seconds to start. */
const macWindows = new Map();

function captureMac(pid, file) {
  let id = macWindows.get(pid);
  if (id === undefined) {
    const script = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "comodor-shot-")), "find-window.swift");
    fs.writeFileSync(script, MAC_FIND);
    const found = spawnSync("swift", [script, String(pid)], { encoding: "utf-8", timeout: 180_000 });
    if (found.error) return { ok: false, reason: `swift could not run: ${found.error.message}` };
    if (found.status !== 0) return { ok: false, reason: `no on-screen window of the application (${found.stderr.trim()})` };
    id = found.stdout.trim();
    macWindows.set(pid, id);
  }
  const shot = spawnSync("screencapture", ["-x", "-o", "-l", id, file], { encoding: "utf-8", timeout: 60_000 });
  if (shot.status !== 0 || !fs.existsSync(file)) {
    return { ok: false, reason: `screencapture failed: ${shot.stderr?.trim() || shot.status}` };
  }
  return { ok: true, method: "screencapture", window: id };
}

// -- Linux ---------------------------------------------------------------

function captureLinux(pid, file) {
  const found = spawnSync("timeout", ["20", "xdotool", "search", "--sync", "--onlyvisible", "--pid", String(pid)],
                          { encoding: "utf-8" });
  if (found.error || found.status !== 0) {
    return { ok: false, reason: `xdotool found no window for the application: ${found.error?.message ?? found.stderr}` };
  }
  const id = found.stdout.trim().split(/\s+/)[0];
  const shot = spawnSync("import", ["-window", id, file], { encoding: "utf-8", timeout: 60_000 });
  if (shot.error) return { ok: false, reason: `ImageMagick's import could not run: ${shot.error.message}` };
  if (shot.status !== 0 || !fs.existsSync(file)) return { ok: false, reason: `import failed: ${shot.stderr.trim()}` };
  return { ok: true, method: "import", window: id };
}

export function captureWindow(pid, file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (process.platform === "win32") return captureWindows(pid, file);
  if (process.platform === "darwin") return captureMac(pid, file);
  return captureLinux(pid, file);
}
