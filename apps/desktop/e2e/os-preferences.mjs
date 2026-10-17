/**
 * D2 T094: the operating system's reduced-motion preference, set for one
 * scenario's run and restored afterwards. Test only, and only when
 * `COMODOR_E2E_OS_LEVEL=1` (the CI desktop job).
 *
 * Each platform records the original setting, sets reduced motion, reads
 * back the *effective* value, and — in the harness's `finally`, after a
 * pass, a failure or the deadline — restores the original and confirms it by
 * the same read-back:
 *
 * - Windows: client-area animation through `SystemParametersInfo`, with
 *   `SPIF_SENDCHANGE` only, never `SPIF_UPDATEINIFILE`, so nothing is saved
 *   to the profile; read back with `SPI_GETCLIENTAREAANIMATION`.
 * - macOS: `defaults write com.apple.universalaccess reduceMotion`, read back
 *   from `NSWorkspace.shared.accessibilityDisplayShouldReduceMotion` (what
 *   WebKit uses); restored to the original value, or deleted if it was absent.
 * - Linux: `gtk-enable-animations=false` in a per-run GTK `settings.ini`,
 *   under an `XDG_CONFIG_HOME` given to the application only; removed after.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { osLevelEnabled } from "./os-input.mjs";

const unavailable = (reason) => ({ applied: false, outcome: "capability-unavailable", reason });

// -- Windows -------------------------------------------------------------

const WINDOWS_SCRIPT = String.raw`
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class Motion {
  [DllImport("user32.dll", SetLastError = true)] static extern bool SystemParametersInfo(uint action, uint param, ref bool value, uint flags);
  [DllImport("user32.dll", SetLastError = true)] static extern bool SystemParametersInfo(uint action, uint param, IntPtr value, uint flags);
  public static bool Get() { bool on = false; if (!SystemParametersInfo(0x1042, 0, ref on, 0)) throw new Exception("SPI_GETCLIENTAREAANIMATION failed"); return on; }
  // SPIF_SENDCHANGE (2) only: the change is never written to the profile.
  public static void Set(bool on) { if (!SystemParametersInfo(0x1043, 0, (IntPtr)(on ? 1 : 0), 2)) throw new Exception("SPI_SETCLIENTAREAANIMATION failed"); }
}
"@
if ($env:COMODOR_MOTION_SET -ne "") { [Motion]::Set($env:COMODOR_MOTION_SET -eq "on") }
Write-Output ([Motion]::Get())
`;

/** Client-area animation now, optionally after setting it (`on`/`off`). */
function windowsAnimation(set) {
  const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT], { windowsHide: true,
    encoding: "utf-8", timeout: 60_000, env: { ...process.env, COMODOR_MOTION_SET: set ?? "" },
  });
  if (result.status !== 0) return { error: `${result.stdout ?? ""}${result.stderr ?? ""}`.trim() || "PowerShell failed" };
  return { animation: result.stdout.trim().toLowerCase() === "true" };
}

function windowsSet() {
  const original = windowsAnimation();
  if (original.error) return unavailable(`the setting could not be read: ${original.error}`);
  const after = windowsAnimation("off");
  if (after.error) return unavailable(`the setting could not be changed: ${after.error}`);
  if (after.animation !== false) return unavailable("client-area animation stayed on after it was turned off");
  return {
    applied: true, original: { animation: original.animation }, effective: { reducedMotion: true },
    restore: () => {
      const back = windowsAnimation(original.animation ? "on" : "off");
      return back.error ? { ok: false, reason: back.error }
        : { ok: back.animation === original.animation, readBack: { animation: back.animation } };
    },
  };
}

// -- macOS ---------------------------------------------------------------

const MAC_EFFECTIVE = `
import AppKit
print(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? "true" : "false")
`;

let macHelper;

function macEffective() {
  if (!macHelper) {
    macHelper = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "comodor-motion-")), "reduce-motion.swift");
    fs.writeFileSync(macHelper, MAC_EFFECTIVE);
  }
  const result = spawnSync("swift", [macHelper], { encoding: "utf-8", timeout: 180_000 });
  if (result.status !== 0) return { error: `${result.stderr ?? ""}`.trim() || "swift failed" };
  return { reduced: result.stdout.trim() === "true" };
}

function defaults(...args) {
  return spawnSync("defaults", args, { encoding: "utf-8", timeout: 30_000 });
}

function macSet() {
  const read = defaults("read", "com.apple.universalaccess", "reduceMotion");
  const absent = read.status !== 0;
  const originalValue = absent ? undefined : read.stdout.trim();
  const originalEffective = macEffective();
  if (originalEffective.error) return unavailable(`the effective setting could not be read: ${originalEffective.error}`);
  const written = defaults("write", "com.apple.universalaccess", "reduceMotion", "-bool", "true");
  if (written.status !== 0) return unavailable(`the setting could not be written: ${`${written.stderr}`.trim()}`);
  const effective = macEffective();
  const restore = () => {
    const back = absent
      ? defaults("delete", "com.apple.universalaccess", "reduceMotion")
      : defaults("write", "com.apple.universalaccess", "reduceMotion", "-bool", originalValue === "1" ? "true" : "false");
    const now = macEffective();
    if (back.status !== 0 || now.error) return { ok: false, reason: `${back.stderr ?? ""}${now.error ?? ""}`.trim() };
    return { ok: now.reduced === originalEffective.reduced, readBack: { reduced: now.reduced } };
  };
  if (effective.error || effective.reduced !== true) {
    const restored = restore();
    return { ...unavailable("the operating system did not apply the preference (NSWorkspace still reports it off)"),
             restored };
  }
  return { applied: true, original: { value: originalValue ?? null, reduced: originalEffective.reduced },
           effective: { reducedMotion: true }, restore };
}

// -- Linux ---------------------------------------------------------------

function linuxSet(env) {
  const config = fs.mkdtempSync(path.join(os.tmpdir(), "comodor-gtk-"));
  const file = path.join(config, "gtk-3.0", "settings.ini");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, "[Settings]\ngtk-enable-animations=false\n");
  if (!fs.readFileSync(file, "utf-8").includes("gtk-enable-animations=false")) {
    fs.rmSync(config, { recursive: true, force: true });
    return unavailable("the per-run GTK settings could not be written");
  }
  env.XDG_CONFIG_HOME = config;
  return {
    applied: true, original: { xdgConfigHome: process.env.XDG_CONFIG_HOME ?? null }, effective: { reducedMotion: true },
    restore: () => {
      fs.rmSync(config, { recursive: true, force: true });
      return { ok: !fs.existsSync(config), readBack: { removed: !fs.existsSync(config) } };
    },
  };
}

/**
 * Set reduced motion for one run. `env` is the environment the application
 * will be started with (Linux adds its per-run settings there only).
 */
export function setReducedMotion(env) {
  if (!osLevelEnabled()) return { applied: false, outcome: "not-run", reason: "operating-system-level evidence disabled" };
  if (process.platform === "win32") return windowsSet();
  if (process.platform === "darwin") return macSet();
  return linuxSet(env);
}

// -- macOS: the off-to-on transition (D2 follow-up) ----------------------
//
// The `reduced-motion` scenario above sets the preference on; on a runner
// where it was already on, that shows the window honouring it, not a
// change. These pieces let the harness switch it off, then on, each
// confirmed by the effective value, and put the original back exactly: the
// same type and value, or no key at all if there was none.

const MAC_DOMAIN = "com.apple.universalaccess";
const MAC_KEY = "reduceMotion";

/** `defaults read-type` output → the `defaults write` flag that keeps that type, or null. */
export function macTypeFlag(readType) {
  const type = /Type is (\w+)/.exec(readType ?? "")?.[1];
  return { boolean: "-bool", integer: "-int", float: "-float", string: "-string" }[type] ?? null;
}

/** The `defaults` arguments that put `original` back exactly. */
export function macRestoreArguments(original) {
  if (original.absent) return ["delete", MAC_DOMAIN, MAC_KEY];
  const value = original.flag === "-bool" ? (original.value === "1" ? "true" : "false") : original.value;
  return ["write", MAC_DOMAIN, MAC_KEY, original.flag, value];
}

/** Whether `now` is `original` in every part: presence, type, value and effective value. */
export function macRestoredExactly(original, now) {
  if (now.effective !== original.effective) return false;
  if (original.absent) return now.absent === true;
  return now.absent === false && now.flag === original.flag && now.value === original.value;
}

/**
 * What one `defaults read` of the key says: present with its value exactly
 * (only the newline `defaults` appends removed), absent only when `defaults`
 * says the pair does not exist, and an error for any other failure — a
 * timeout, a launch failure, a refusal — so an unreadable setting is never
 * taken for an absent one (and later deleted).
 */
export function macReadOutcome(read) {
  if (read.error) return { error: `defaults read failed: ${read.error.message ?? read.error}` };
  if (read.status === 0) return { absent: false, value: `${read.stdout ?? ""}`.replace(/\n$/, "") };
  const said = `${read.stderr ?? ""}`.trim();
  if (/does not exist/.test(said)) return { absent: true };
  return { error: `defaults read failed (${read.status ?? "no status"}): ${said || "no reason given"}` };
}

/** The setting as it stands: present or absent, its type and value, and the effective value WebKit uses. */
export function macReadMotion() {
  const read = macReadOutcome(defaults("read", MAC_DOMAIN, MAC_KEY));
  if (read.error) return { error: read.error };
  const effective = macEffective();
  if (effective.error) return { error: `the effective setting could not be read: ${effective.error}` };
  if (read.absent) return { absent: true, effective: effective.reduced };
  const type = defaults("read-type", MAC_DOMAIN, MAC_KEY);
  return { absent: false, value: read.value, type: `${type.stdout ?? ""}`.trim(),
           flag: macTypeFlag(type.stdout), effective: effective.reduced };
}

/** Write reduced motion on or off, then read the setting back. */
export function macWriteMotion(on) {
  const written = defaults("write", MAC_DOMAIN, MAC_KEY, "-bool", on ? "true" : "false");
  if (written.status !== 0) return { error: `the setting could not be written: ${`${written.stderr ?? ""}`.trim()}` };
  return macReadMotion();
}

/** Put `original` back exactly, and confirm it by reading everything again. */
export function macRestoreMotion(original) {
  const back = defaults(...macRestoreArguments(original));
  const now = macReadMotion();
  if (back.status !== 0 || now.error) {
    return { ok: false, reason: `${back.stderr ?? ""}${now.error ?? ""}`.trim() || "the restore failed", readBack: now };
  }
  return { ok: macRestoredExactly(original, now), readBack: now };
}
