import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Test build only (D2, research R12): `axe-core` bundles a colour library
 * that adds its methods to a class prototype by plain assignment, `toString`
 * among them. Under Tauri's `freezePrototype`, `Object.prototype.toString` is
 * read-only, and assigning a property of that name on an object that inherits
 * it throws in strict code. The window keeps `freezePrototype`; this rewrites
 * that one assignment into the `Object.defineProperty` it means — the same
 * writable, enumerable, configurable property — and fails the build if the
 * pinned `axe-core` no longer has it exactly once. No rule changes.
 */
function axeUnderFrozenPrototypes(): Plugin {
  const assignment =
    /_Color\.prototype\[name\] = (function\(\) \{[\s\S]*?return func\.apply\(void 0, \[ this \]\.concat\(args\)\);\s*\});/g;
  return {
    name: "comodor-axe-under-frozen-prototypes",
    transform(code, id) {
      if (!/[\\/]axe-core[\\/]axe\.js$/.test(id)) return null;
      const found = code.match(assignment)?.length ?? 0;
      if (found !== 1) throw new Error(`axe-core: expected one prototype assignment to rewrite, found ${found}`);
      return code.replace(assignment, "Object.defineProperty(_Color.prototype, name, "
        + "{ configurable: true, enumerable: true, writable: true, value: $1 });");
    },
  };
}

/**
 * D3 editor spike 2 (throwaway, never merged): the spike-1 transform that
 * keeps Monaco 0.57.0 loadable under freezePrototype — four
 * `X.toString = toString` namespace assignments and Monarch's keyword table
 * (`result[e] = true`, whose TypeScript/JavaScript lists contain
 * `constructor`) rewritten into `Object.defineProperty`. CodeMirror 6 is not
 * transformed.
 */
function monacoUnderFrozenPrototypes(): Plugin {
  const assignment = /\b([A-Za-z_$][\w$]*)\.toString = toString;/g;
  return {
    name: "comodor-spike-monaco-under-frozen-prototypes",
    transform(code, id) {
      if (!/[\\/]monaco-editor[\\/]/.test(id)) return null;
      let out = code;
      if (/[\\/]monarch[\\/]monarchCompile\.js$/.test(id)) {
        const write = "        result[e] = true;";
        if (out.split(write).length !== 2) throw new Error("spike: Monarch's keyword-table write was not found exactly once");
        out = out.replace(write, "        Object.defineProperty(result, e, "
          + "{ configurable: true, enumerable: true, writable: true, value: true });");
      }
      out = out.replace(assignment, "Object.defineProperty($1, \"toString\", "
        + "{ configurable: true, enumerable: true, writable: true, value: toString });");
      return out === code ? null : out;
    },
  };
}

// The window's content is served from the application bundle only: no
// development server in a test or release build, no remote origin, and no
// inline script (the Content Security Policy in src-tauri/tauri.conf.json
// refuses it). `--mode e2e` adds the scenario runner; any other mode leaves
// it out entirely.
export default defineConfig(({ mode }) => ({
  plugins: mode === "e2e" ? [react(), axeUnderFrozenPrototypes(), monacoUnderFrozenPrototypes()] : [react()],
  clearScreen: false,
  server: { port: 5173, strictPort: true, host: "127.0.0.1" },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
  },
}));
