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
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const ROOTS = ["packages", "apps"];
const SKIP = new Set(["node_modules", "dist", ".git"]);

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
    name: "no-relative-import-across-packages",
    why: "Reaching into another package by path bypasses its public surface "
       + "and its project reference; import the package name.",
    test: (line) => /from\s+["'](?:\.\.\/){2,}/.test(line),
  },
];

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
        if (rule.test(line)) {
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
