#!/usr/bin/env bun
/**
 * Build the production TUI artifact: the bundled renderer the Python package
 * ships and `comodor` launches.
 *
 * One command, run from anywhere:
 *
 *     bun tools/build-tui-distribution.ts
 *
 * Output: `src/comodor/tui/dist/` — one entry bundle, its assets, a
 * `manifest.json` naming them, and the *matching* platform native package for
 * the machine that built it. `comodor doctor --rebuild-native` adds the other
 * platforms' native packages from that machine's registry cache, so the wheel
 * a release ships renders everywhere, not only where it was built.
 *
 * The bundle is generated. Never hand-edit anything in `src/comodor/tui/dist/`.
 */

import { copyFileSync, cpSync, existsSync, mkdirSync, readdirSync,
         readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const ROOT = resolve(import.meta.dir, "..");
const ENTRY = join(ROOT, "apps", "tui", "src", "main.tsx");
const OUT = join(ROOT, "src", "comodor", "tui", "dist");

/** Every OpenTUI platform backend the loader may ask for at runtime. */
const NATIVE_PACKAGES = [
  "@opentui/core-win32-x64",
  "@opentui/core-win32-arm64",
  "@opentui/core-linux-x64",
  "@opentui/core-linux-arm64",
  "@opentui/core-linux-x64-musl",
  "@opentui/core-linux-arm64-musl",
  "@opentui/core-darwin-x64",
  "@opentui/core-darwin-arm64",
] as const;

/** The platform native package for the machine doing this build. */
function thisPlatformsPackage(): string {
  const platform = process.platform;
  const arch = process.arch;
  if (platform === "win32") return `@opentui/core-win32-${arch}`;
  if (platform === "darwin") return `@opentui/core-darwin-${arch}`;
  if (platform === "linux") return `@opentui/core-linux-${arch}`;
  throw new Error(`no OpenTUI native package is known for ${platform}/${arch}`);
}

/**
 * The native package for one platform, wherever it has to come from.
 *
 * npm installs only the current platform's optional dependency, so a release
 * built on one machine needs the others fetched deliberately: `npm pack`
 * at exactly the version the lockfile pins, then untarred into the build's
 * node_modules. Build-time network use only — runtime never fetches.
 */
function fetchNativePackage(name: string, version: string): void {
  const target = join(ROOT, "node_modules", ...name.split("/"));
  if (existsSync(target)) return;
  const tmp = join(ROOT, "node_modules", ".cache", "comodor-native");
  mkdirSync(tmp, { recursive: true });
  const pack = spawnSync("npm", ["pack", `${name}@${version}`,
                                 "--pack-destination", tmp],
                         { cwd: ROOT, stdio: "inherit" });
  if (pack.status !== 0) throw new Error(`npm pack ${name} failed`);
  const tarball = join(tmp, readdirSync(tmp).find((f) => f.startsWith(
    name.split("/")[1])) ?? "");
  const untar = spawnSync("tar", ["-xzf", tarball, "-C", tmp],
                          { stdio: "inherit" });
  if (untar.status !== 0) throw new Error(`untar ${name} failed`);
  mkdirSync(join(ROOT, "node_modules", "@opentui"), { recursive: true });
  cpSync(join(tmp, "package"), target, { recursive: true });
}

function sha256(path: string): string {
  return createHash("sha256").update(
    require("node:fs").readFileSync(path)).digest("hex");
}

async function main(): Promise<void> {
  if (!existsSync(ENTRY)) {
    throw new Error(`no TUI entry at ${ENTRY} — run from the repository`);
  }

  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });

  const externals: string[] = [];
  for (const name of NATIVE_PACKAGES) externals.push("--external", name);
  const build = spawnSync(
    process.execPath,
    ["build", ENTRY, "--outdir", OUT, "--target", "bun", ...externals],
    { cwd: ROOT, stdio: "inherit" });
  if (build.status !== 0) {
    throw new Error(`bun build failed with status ${build.status}`);
  }

  // The native backend for the platform building this artifact. With
  // `--platforms all` (the release build) every platform's backend joins,
  // fetched at the lockfile's pinned version so the bundle and the backends
  // are one revision.
  const all = process.argv.includes("--platforms")
    && process.argv[process.argv.indexOf("--platforms") + 1] === "all";
  const nativeName = thisPlatformsPackage();
  const wanted = all ? [...NATIVE_PACKAGES] : [nativeName];
  const lockVersion = (JSON.parse(readFileSync(
    join(ROOT, "package-lock.json"), "utf-8")) as
    { packages: Record<string, { version?: string }> })
    .packages["node_modules/@opentui/core"]?.version;
  if (all && !lockVersion) {
    throw new Error("cannot pin native backends: no @opentui/core version in "
                    + "package-lock.json — run `npm ci` first");
  }
  for (const name of wanted) {
    if (!existsSync(join(ROOT, "node_modules", ...name.split("/")))) {
      fetchNativePackage(name, lockVersion ?? "");
    }
    const nativeSrc = join(ROOT, "node_modules", ...name.split("/"));
    const nativeOut = join(OUT, "node_modules", ...name.split("/"));
    mkdirSync(join(OUT, "node_modules", "@opentui"), { recursive: true });
    cpSync(nativeSrc, nativeOut, { recursive: true });
  }

  // The bundle must be identical on every OS that builds it: a Windows build
  // that writes CRLF and a Linux build that writes LF would disagree on the
  // same source, which is exactly what the staleness check exists to catch.
  // Only the text is normalized — a .wasm under that rule is not normalized,
  // it is corrupted.
  for (const name of readdirSync(OUT).filter((name) =>
      statSync(join(OUT, name)).isFile()
      && /\.(js|scm)$/.test(name))) {
    const path = join(OUT, name);
    const raw = require("node:fs").readFileSync(path);
    const normalized = Buffer.from(
      raw.toString("binary").replace(/\r\n/g, "\n"), "binary");
    if (!normalized.equals(raw)) writeFileSync(path, normalized);
  }

  // The manifest is the contract: `comodor doctor` verifies every file it
  // names, and the packaging tests refuse a wheel that does not carry all of
  // it. The hash is what proves the bundle on disk is the bundle built.
  const files = readdirSync(OUT)
    .filter((name) => statSync(join(OUT, name)).isFile())
    .sort();
  const entry = files.find((name) => name === "main.js");
  if (!entry) throw new Error("the build produced no main.js");
  // No timestamps, no commit: the manifest is the integrity contract, and
  // anything in it that changes when the source did not would make every
  // later build "stale" by definition. Freshness is the CI job's to prove by
  // rebuilding and comparing, not a field's to claim.
  const natives = readdirSync(join(OUT, "node_modules", "@opentui")).sort();
  const manifest = {
    entry,
    native: nativeName,
    natives,
    files,
    sha256: Object.fromEntries(files.map((name) => [name, sha256(join(OUT, name))])),
  };
  writeFileSync(join(OUT, "manifest.json"),
                `${JSON.stringify(manifest, null, 2)}\n`);

  console.log(`production TUI artifact written to ${OUT}`);
  console.log(`  ${files.length} files + native backend ${nativeName}`);
}

await main();
