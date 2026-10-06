#!/usr/bin/env node
/**
 * Evidence that the real system folder chooser opens where the application
 * says (T095, SC-017, quickstart §7).
 *
 * The release build — the real dialog, not the test build's double — is
 * launched twice in a row with no workspace argument, each time with a
 * different folder stored as the last one chosen. When the dialog's window
 * exists, that window alone is captured — never the whole screen, which on a
 * person's machine shows whatever else they have open. Where the platform
 * lets a tool read the dialog itself, the folder it opened at is observed
 * and compared with the stored one: on Windows the address bar, through UI
 * Automation; on macOS the panel's column browser (the selected folder in
 * each column, from the disk's root) and its location pop-up, through the
 * Accessibility API; on Linux the GTK dialog's own location entry (Ctrl+L
 * shows it filled with the folder the dialog is in), copied and read back
 * with `xclip`, with a second screenshot of the entry. The path bar alone
 * shows only the last folders' names, not the whole path. The stored folder written beforehand is the request,
 * never the observation. Then the application is ended. Nothing is chosen
 * and no Core starts.
 *
 *   node e2e/chooser-evidence.mjs [--skip-build]
 *
 * Output: `e2e/out/chooser-evidence/` — one screenshot per launch and
 * `evidence.json`. A dialog that opened anywhere else fails the run; a
 * platform where the folder could not be observed is said so, and its
 * screenshots remain the only evidence.
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

/**
 * macOS: read the open panel of process `pid` through the Accessibility API.
 * The folder is taken from what the panel itself reports, in order: the file
 * URL of the selected row in its browser (a URL is the whole path); else
 * the menu of its location pop-up, which lists the folder and each parent up
 * to the disk (opened and cancelled — after the screenshot — to read it);
 * else the selected folder of each browser column. Every read is kept, raw.
 * Reads repeat until two agree, so a panel still filling in is not taken
 * half-way.
 */
function observePanel(pid) {
  const swift = `
import AppKit
import ApplicationServices
import Foundation

func value(_ e: AXUIElement, _ name: String) -> AnyObject? {
  var v: AnyObject?
  return AXUIElementCopyAttributeValue(e, name as CFString, &v) == .success ? v : nil
}
func attributes(_ e: AXUIElement) -> [String] {
  var names: CFArray?
  return AXUIElementCopyAttributeNames(e, &names) == .success ? (names as? [String] ?? []) : []
}
func kids(_ e: AXUIElement) -> [AXUIElement] { value(e, kAXChildrenAttribute as String) as? [AXUIElement] ?? [] }
func role(_ e: AXUIElement) -> String { value(e, kAXRoleAttribute as String) as? String ?? "" }
func first(_ e: AXUIElement, _ wanted: String, _ depth: Int = 0) -> AXUIElement? {
  if role(e) == wanted { return e }
  if depth > 40 { return nil }
  for k in kids(e) { if let found = first(k, wanted, depth + 1) { return found } }
  return nil
}
func all(_ e: AXUIElement, _ depth: Int = 0, into out: inout [AXUIElement], where keep: (AXUIElement) -> Bool) {
  if keep(e) { out.append(e) }
  if depth > 40 { return }
  for k in kids(e) { all(k, depth + 1, into: &out, where: keep) }
}
// A row's name: its text, not an icon's description.
func label(_ e: AXUIElement) -> String? {
  if ["AXStaticText", "AXTextField"].contains(role(e)),
     let s = value(e, kAXValueAttribute as String) as? String, !s.isEmpty { return s }
  for k in kids(e) { if let s = label(k) { return s } }
  return nil
}
// A path the element reports itself: a file URL or a path.
func path(_ e: AXUIElement) -> String? {
  for name in ["AXURL", "AXDocument", "AXFilename"] {
    guard let v = value(e, name) else { continue }
    if let url = v as? URL, url.isFileURL { return url.path }
    if let s = v as? String {
      if s.hasPrefix("file://"), let url = URL(string: s) { return url.path }
      if s.hasPrefix("/") { return s }
    }
  }
  return nil
}
func isSelected(_ e: AXUIElement) -> Bool { (value(e, kAXSelectedAttribute as String) as? Bool) == true }

struct Seen: Equatable {
  var urls: [String]; var selected: [String]; var popups: [String]; var leafAttributes: [String]
}
func panel(_ pid: pid_t) -> (AXUIElement, AXUIElement)? {
  let app = AXUIElementCreateApplication(pid)
  for window in value(app, kAXWindowsAttribute as String) as? [AXUIElement] ?? [] {
    if let browser = first(window, "AXBrowser") { return (window, browser) }
  }
  return nil
}
func read(_ window: AXUIElement, _ browser: AXUIElement) -> Seen {
  var chosen: [AXUIElement] = []
  all(browser, into: &chosen, where: isSelected)
  let urls = chosen.compactMap { row -> String? in
    path(row) ?? kids(row).lazy.compactMap(path).first
  }
  var popups: [AXUIElement] = []
  all(window, into: &popups, where: { role($0) == "AXPopUpButton" })
  return Seen(urls: urls, selected: chosen.compactMap(label),
              popups: popups.compactMap { value($0, kAXValueAttribute as String) as? String },
              leafAttributes: chosen.last.map(attributes) ?? [])
}
// The location pop-up's menu: the folder, then each parent, down to the disk.
func menuChain(_ window: AXUIElement, _ leaf: String) -> [String] {
  var popups: [AXUIElement] = []
  all(window, into: &popups, where: { role($0) == "AXPopUpButton" })
  guard let popup = popups.first(where: { (value($0, kAXValueAttribute as String) as? String) == leaf }),
        AXUIElementPerformAction(popup, kAXPressAction as CFString) == .success else { return [] }
  var items: [AXUIElement] = []
  for _ in 0..<40 where items.isEmpty {
    usleep(100_000)
    all(popup, into: &items, where: { role($0) == "AXMenuItem" })
  }
  let titles = items.map { value($0, kAXTitleAttribute as String) as? String ?? "" }
  if let menu = first(popup, "AXMenu") { AXUIElementPerformAction(menu, kAXCancelAction as CFString) }
  return titles
}
func emit(_ object: [String: Any], _ code: Int32) -> Never {
  let data = try! JSONSerialization.data(withJSONObject: object)
  print(String(data: data, encoding: .utf8)!)
  exit(code)
}

guard AXIsProcessTrusted() else { emit(["error": "this process is not trusted for Accessibility"], 3) }
let application = pid_t(CommandLine.arguments[1])!
let volume = (try? URL(fileURLWithPath: "/").resourceValues(forKeys: [.volumeNameKey]))?.volumeName ?? ""
let deadline = Date().addingTimeInterval(${DIALOG_DEADLINE_S})
var last: Seen? = nil
while Date() < deadline {
  if let found = panel(application) {
    let (window, browser) = found
    let seen = read(window, browser)
    if !seen.popups.isEmpty, seen == last {
      var report: [String: Any] = ["urls": seen.urls, "selected": seen.selected, "popups": seen.popups,
                                   "leafAttributes": seen.leafAttributes, "volume": volume]
      let leaf = seen.selected.last ?? seen.popups[0]
      if let url = seen.urls.first(where: { ($0 as NSString).lastPathComponent == leaf }) {
        report["path"] = url
        report["method"] = "the selected row's file URL"
      } else {
        let chain = menuChain(window, leaf)
        report["menu"] = chain
        let parents = Array(chain.prefix(while: { !$0.isEmpty }))
        if let disk = parents.firstIndex(of: volume), disk > 0 {
          report["path"] = "/" + parents[..<disk].reversed().joined(separator: "/")
          report["method"] = "the location pop-up's menu, from the folder down to the disk"
        } else {
          report["error"] = "neither a file URL nor a menu down to the disk was read"
        }
      }
      emit(report, 0)
    }
    last = seen
  }
  usleep(250_000)
}
emit(["error": "the panel's browser was not read twice alike", "selected": last?.selected ?? [],
      "popups": last?.popups ?? []], 4)
`;
  const script = path.join(os.tmpdir(), "comodor-chooser-observe.swift");
  fs.writeFileSync(script, swift);
  const run = spawnSync("swift", [script, String(pid)], { encoding: "utf-8" });
  try {
    return JSON.parse(run.stdout.trim().split("\n").pop() ?? "");
  } catch {
    return { error: `the observer gave no answer (${run.status}): ${run.stderr.trim().slice(-400)}` };
  }
}

/**
 * Linux: the folder the GTK dialog is in, from its own location entry.
 * Ctrl+L shows the entry filled with that folder; it is selected, copied
 * and read back from the clipboard, until an absolute path comes back. Then
 * the entry is captured too (`entryShot`). Nothing is chosen: the
 * application is ended afterwards with the dialog still open.
 */
function observeGtk(windowId, entryShot) {
  const run = (command, args) => spawnSync(command, args, { encoding: "utf-8", timeout: 10_000 });
  // Without a window manager the keyboard follows the pointer.
  run("xdotool", ["mousemove", "--window", windowId, "40", "40"]);
  run("xdotool", ["windowfocus", windowId]);
  run("xdotool", ["key", "--clearmodifiers", "ctrl+l"]);
  const ends = Date.now() + DIALOG_DEADLINE_S * 1000;
  let text = "";
  while (!text.startsWith("/") && Date.now() < ends) {
    run("xdotool", ["key", "--clearmodifiers", "ctrl+a", "ctrl+c"]);
    const read = run("xclip", ["-o", "-selection", "clipboard"]);
    text = read.status === 0 ? read.stdout.trim() : "";
  }
  run("import", ["-window", windowId, entryShot]);
  if (!text.startsWith("/")) {
    return { method: "the location entry (Ctrl+L), through the clipboard", error: `read ${JSON.stringify(text)}` };
  }
  return { method: "the location entry (Ctrl+L), through the clipboard", entry: text,
           path: text.replace(/\/+$/, "") || "/",
           entryScreenshot: fs.existsSync(entryShot) ? path.basename(entryShot) : null };
}

/** Is `observed` the folder `stored` names, however it is spelled? */
function sameFolder(observed, stored) {
  try {
    const a = fs.realpathSync.native(observed);
    const b = fs.realpathSync.native(stored);
    return process.platform === "win32" ? a.toLowerCase() === b.toLowerCase() : a === b;
  } catch {
    return false;
  }
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
    // Only once it is mapped: a window found before then has no image yet.
    const found = spawnSync("timeout", [String(DIALOG_DEADLINE_S), "xdotool", "search", "--sync", "--onlyvisible",
                                        "--name", TITLE], { encoding: "utf-8" });
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
    // The folder the dialog itself shows, where the platform lets it be read.
    let observed = null;
    let observation;
    if (seen.found && process.platform === "win32" && seen.read.startsWith("Address: ")) {
      observed = seen.read.slice("Address: ".length);
      observation = { how: "the dialog's address bar (UI Automation)" };
    } else if (seen.found && process.platform === "darwin") {
      observation = { how: "the panel's column browser (Accessibility)", ...observePanel(app.pid) };
      observed = observation.path ?? null;
    } else if (seen.found && process.platform === "linux") {
      const windowId = seen.read.replace(/^window /, "");
      observation = { how: "the GTK dialog's location entry",
                      ...observeGtk(windowId, path.join(OUT, `launch-${n}-${process.platform}-entry.png`)) };
      observed = observation.path ?? null;
    } else {
      observation = { how: "not read on this platform: the screenshot's path bar is the evidence" };
    }
    app.kill("SIGKILL");
    await new Promise((resolve) => app.once("exit", resolve));
    launches.push({ launch: n, platform: process.platform, requested: stored, dialog: seen.found,
                    read: seen.read, observed, observation,
                    matches: observed === null ? null : sameFolder(observed, stored),
                    screenshot: fs.existsSync(shot) ? path.basename(shot) : null,
                    error: seen.error || undefined });
  }
} finally {
  if (saved) fs.writeFileSync(prefs, saved);
  else fs.rmSync(prefs, { force: true });
}
fs.writeFileSync(path.join(OUT, "evidence.json"), JSON.stringify(launches, null, 2));
console.log(JSON.stringify(launches, null, 2));
// A dialog that opened elsewhere is a failure; one whose folder could not be
// read is said so, and not passed off as observed.
const ok = launches.every((launch) => launch.dialog && launch.screenshot && launch.matches !== false);
const observedAll = launches.every((launch) => launch.matches === true);
console.log(!ok ? "NOT RECORDED chooser evidence"
  : observedAll ? "RECORDED chooser evidence: the start folder observed on every launch"
  : "RECORDED chooser evidence: screenshots only, the start folder NOT OBSERVED");
process.exit(ok ? 0 : 1);
