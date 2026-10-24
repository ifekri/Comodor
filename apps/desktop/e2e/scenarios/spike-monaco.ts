/**
 * D3 spike (throwaway, never merged): Monaco in the real WebView under the
 * window's unchanged Content Security Policy. See spike/README.md.
 *
 * Every `securitypolicyviolation` is recorded from before Monaco is loaded.
 * The scenario passes when the probe ran to the end; the measurements are
 * the result, whatever they show.
 */

import type { Scenario } from "../runner.ts";
import type { ProbeHooks, Violation } from "../../spike/monaco-probe.ts";

type Data = Record<string, unknown>;

export const spikeMonaco: Scenario = async (context) => {
  await context.element("main");
  const violations: Violation[] = [];
  let phase = "import";
  let policy: string | null = null;
  document.addEventListener("securitypolicyviolation", (event) => {
    policy ??= event.originalPolicy;
    violations.push({
      directive: event.violatedDirective, effective: event.effectiveDirective, blocked: event.blockedURI,
      sample: event.sample, source: event.sourceFile, line: event.lineNumber, disposition: event.disposition, phase,
    });
  });
  const importStarted = context.now();
  const { probe } = await import("../../spike/monaco-probe.ts");
  const importMs = Math.round(context.now() - importStarted);

  const gate = await context.checkpoint("os-level");
  const hooks: ProbeHooks = {
    violations: () => violations,
    phase: (name) => { phase = name; },
    policy: () => policy,
    shot: (name) => context.checkpoint("screenshot", { name }),
    pressQ: async () => {
      const preflight = gate["preflight"] as { ok: boolean } | undefined;
      if (!preflight?.ok) return { notRun: gate["preflight"] ?? null };
      await context.checkpoint("focus-window");
      return context.checkpoint("press-keys", { key: { key: "q" } as unknown as Data });
    },
  };
  const results = await probe(hooks);
  const byDirective: Record<string, number> = {};
  for (const violation of violations) {
    const key = `${violation.phase}: ${violation.effective || violation.directive}`;
    byDirective[key] = (byDirective[key] ?? 0) + 1;
  }
  return {
    importMs, policy, violationCount: violations.length, byDirective,
    violations: violations.slice(0, 60), ...results,
  };
};

/**
 * D3 spike: keeps the page open, doing nothing, while the native spike dialog
 * is answered from outside (spike/dialog-evidence.mjs). It never reports by
 * itself; the runner's own page deadline bounds it.
 */
export const spikeIdle: Scenario = () => new Promise<never>(() => undefined);
