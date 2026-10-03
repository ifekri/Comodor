/**
 * The rules for the TypeScript side that a type checker cannot state.
 *
 * Not a replacement for ESLint, and not an argument that one is unnecessary
 * forever. It is what this phase needs, with no dependency: five rules that
 * each exist because breaking them would undo something the architecture is
 * built on. Adding a linter with a plugin ecosystem is a decision worth
 * making deliberately, and a foundation phase is the wrong time to make it.
 *
 *   node tools/lint-frontend.mjs
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const ROOTS = ["packages", "apps"];
// `target` and `gen` are the desktop application's Rust build output and
// tauri-build's generated schemas: neither is TypeScript anyone wrote.
const SKIP = new Set(["node_modules", "dist", ".git", "target", "gen"]);

/** Where a fixed delay may never stand in for an observed state (FR-035). */
const DESKTOP_TESTS = [join("apps", "desktop", "test"), join("apps", "desktop", "e2e")];

/** Files that are written by a generator and are not ours to style. */
const GENERATED = /generated\.ts$/;

const rules = [
  {
    name: "no-any",
    why: "`any` turns off the checking the protocol relies on; `unknown` and a "
       + "narrowing check say the same thing without the hole.",
    test: (line) => /(:|<)\s*any\b/.test(line) && !/eslint|@ts-/.test(line),
  },
  {
    name: "no-console",
    why: "A library that prints owns the terminal it was imported into. "
       + "Return the text, or take a callback.",
    test: (line) => /\bconsole\.(log|info|warn|error|debug)\s*\(/.test(line),
    // The TUI is an application and may write to the screen it owns.
    skipIn: (path) => path.startsWith(`apps${sep}`),
  },
  {
    name: "no-colour-literals",
    why: "A colour outside the token package cannot be remapped by a second "
       + "renderer, which is the whole reason tokens exist.",
    // Prose is exempt. A comment explaining why colours do not belong in a
    // component is not itself a colour in a component, and a rule that
    // cannot tell the difference gets suppressed rather than obeyed.
    test: (line) => !comment(line) && /#[0-9a-fA-F]{6}\b/.test(line),
    skipIn: (path) => path.includes(join("design-tokens", "")),
  },
  {
    name: "no-todo-without-an-owner",
    why: "A bare TODO is a note nobody is going to act on. Say who or when, "
       + "or open an issue and reference it.",
    test: (line) => /\b(TODO|FIXME)\b(?!\s*\()/.test(line),
  },
  {
    name: "no-import-out-of-its-package",
    why: "Reaching into another package by path bypasses its public surface "
       + "and its project reference; import the package name.",
    // Not a count of `../`. A test three directories deep inside a package
    // legitimately reaches its own `src` that way, and counting flagged it.
    // What matters is whether the resolved path is still under the package
    // root — the directory holding the nearest `package.json`.
    test: (line, file) => {
      const specifier = /from\s+["']([^"']+)["']/.exec(line)?.[1];
      return Boolean(specifier) && escapesItsPackage(file, specifier);
    },
  },
];

function escapesItsPackage(file, specifier) {
  if (!specifier.startsWith(".")) return false;
  const root = packageRoot(dirname(file));
  if (!root) return false;
  const target = resolve(dirname(file), specifier);
  return !target.startsWith(root + sep) && target !== root;
}

function packageRoot(directory) {
  let at = directory;
  for (;;) {
    try {
      statSync(join(at, "package.json"));
      return at;
    } catch { /* keep walking up */ }
    const up = dirname(at);
    if (up === at || at.length <= ROOT.length) return "";
    at = up;
  }
}

rules.push({
  name: "no-fixed-delay",
  why: "A test that waits a fixed time is a race made rarer, not a race "
     + "fixed. Wait on what the code relies on — a process exit, a line, a "
     + "DOM change, an injected clock — and give the wait a named failure "
     + "deadline, never a literal delay.",
  test: (line) => !comment(line)
    && (/\bsetTimeout\s*\(.*,\s*\d+\s*\)/.test(line)
        || /\b(?:Bun\.)?sleep(?:Sync)?\s*\(\s*\d/.test(line)),
  skipIn: (path) => !DESKTOP_TESTS.some((root) => path.startsWith(root + sep)),
});

const fileRules = [
  {
    name: "ends-with-a-newline",
    why: "A file without one produces a diff on the last line every time it "
       + "is touched by something that adds one.",
    test: (text) => text.length > 0 && !text.endsWith("\n"),
  },
  {
    name: "no-crlf",
    why: "Mixed line endings turn a one-line change into a whole-file diff.",
    test: (text) => text.includes("\r\n"),
  },
];

/** Whether a line is prose rather than code. */
function comment(line) {
  return /^\s*(\/\/|\*|\/\*)/.test(line);
}

function* walk(directory) {
  for (const entry of readdirSync(directory)) {
    if (SKIP.has(entry)) continue;
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (/\.(ts|tsx|mts)$/.test(entry)) yield path;
    // The desktop's scenario harnesses are plain Node modules, and they are
    // exactly where a fixed delay would hide a race.
    else if (/\.mjs$/.test(entry)
             && path.includes(join("apps", "desktop", "e2e"))) yield path;
  }
}

const problems = [];
for (const top of ROOTS) {
  let exists = true;
  try {
    statSync(join(ROOT, top));
  } catch {
    exists = false;
  }
  if (!exists) continue;

  for (const path of walk(join(ROOT, top))) {
    const shown = relative(ROOT, path);
    if (GENERATED.test(shown)) continue;
    const text = readFileSync(path, "utf8");

    for (const rule of fileRules) {
      if (rule.test(text)) {
        problems.push({ file: shown, line: 0, rule: rule.name, why: rule.why });
      }
    }
    const lines = text.split("\n");
    for (const [index, line] of lines.entries()) {
      for (const rule of rules) {
        if (rule.skipIn?.(shown)) continue;
        if (rule.test(line, path)) {
          problems.push({
            file: shown, line: index + 1, rule: rule.name, why: rule.why,
            text: line.trim(),
          });
        }
      }
    }
  }
}

if (problems.length === 0) {
  console.log("frontend lint: clean");
  process.exit(0);
}

for (const problem of problems) {
  const at = problem.line ? `:${problem.line}` : "";
  console.error(`${problem.file}${at}  ${problem.rule}`);
  if (problem.text) console.error(`    ${problem.text}`);
  console.error(`    ${problem.why}`);
}
console.error(`\n${problems.length} problem(s)`);
process.exit(1);
