/**
 * D3 editor spike 2 (throwaway, never merged): CodeMirror 6 and Monaco in the
 * real WebView, CSP and freezePrototype unchanged. Every
 * `securitypolicyviolation` is recorded from before the editor loads. A
 * scenario passes when its probe ran to the end; the measurements are the
 * result, whatever they show.
 */

import { accessibilityViolations, type Scenario, type ScenarioContext } from "../runner.ts";
import type { Data, ProbeHooks } from "../../spike/common.ts";

interface Violation { directive: string; blocked: string; sample: string; source: string; line: number; phase: string }

async function run(context: ScenarioContext, load: () => Promise<{ probe: (hooks: ProbeHooks) => Promise<Data> }>): Promise<Data> {
  await context.element("main");
  const violations: Violation[] = [];
  let phase = "import";
  let policy: string | null = null;
  document.addEventListener("securitypolicyviolation", (event) => {
    policy ??= event.originalPolicy;
    violations.push({ directive: event.effectiveDirective || event.violatedDirective, blocked: event.blockedURI,
                      sample: event.sample, source: event.sourceFile, line: event.lineNumber, phase });
  });
  const importStarted = context.now();
  const { probe } = await load();
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
    axe: async (where) => {
      const found = await accessibilityViolations();
      return { where, count: found.length, violations: found };
    },
  };
  const results = await probe(hooks);
  const byDirective: Record<string, number> = {};
  for (const v of violations) byDirective[`${v.phase}: ${v.directive}`] = (byDirective[`${v.phase}: ${v.directive}`] ?? 0) + 1;
  return { importMs, policy, violationCount: violations.length, byDirective, violations: violations.slice(0, 40), ...results };
}

export const spikeCm6: Scenario = (context) => run(context, () => import("../../spike/cm6-probe.ts"));
export const spikeMonaco: Scenario = (context) => run(context, () => import("../../spike/monaco-probe.ts"));
