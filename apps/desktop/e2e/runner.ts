/**
 * The in-application scenario runner (test build only, T015).
 *
 * The native test build hands the page its scenario in
 * `window.__COMODOR_E2E__` before any script runs. The runner drives the real
 * window with DOM events, waits on the DOM itself (`MutationObserver`), and
 * ends the run with one `e2e_report` result. It has no timeouts: a scenario
 * that never finishes is ended by the harness's failure deadline.
 */

import { invoke } from "@tauri-apps/api/core";

import { SCENARIOS } from "./scenarios/index.ts";

type Data = Record<string, unknown>;

declare global {
  interface Window {
    __COMODOR_E2E__?: { scenario: string; params: Data | null };
  }
}

export interface ScenarioContext {
  readonly params: Data;
  /** Hand the harness something to do, and wait for its reply. */
  checkpoint(name: string, data?: Data): Promise<Data>;
  /** Ask the native test build what only it can see. */
  query(what: "listeners" | "core_pid" | "chooser"): Promise<Data>;
  /** Resolve once `find` returns something, re-checking on every DOM change. */
  waitFor<T>(find: () => T | null | undefined | false): Promise<T>;
  /** The element matching `selector`, once there is one. */
  element(selector: string): Promise<HTMLElement>;
  /** Milliseconds since the page started, from the page's own clock. */
  now(): number;
}

export type Scenario = (context: ScenarioContext) => Promise<Data | void>;

function report(result: Data): Promise<Data> {
  return invoke<Data>("e2e_report", { result });
}

function waitFor<T>(find: () => T | null | undefined | false): Promise<T> {
  return new Promise<T>((resolve) => {
    const found = find();
    if (found) {
      resolve(found);
      return;
    }
    const observer = new MutationObserver(() => {
      const value = find();
      if (value) {
        observer.disconnect();
        resolve(value);
      }
    });
    observer.observe(document, {
      subtree: true, childList: true, attributes: true, characterData: true,
    });
  });
}

const context = (params: Data): ScenarioContext => ({
  params,
  checkpoint: (name, data = {}) => report({ phase: "checkpoint", name, data }),
  query: (what) => report({ phase: "query", what }),
  waitFor,
  element: (selector) => waitFor(() => document.querySelector<HTMLElement>(selector)),
  now: () => performance.now(),
});

/** Run the scenario the native side named, then report its verdict. */
export async function runScenario(): Promise<void> {
  const given = window.__COMODOR_E2E__;
  const name = given?.scenario ?? "";
  const scenario = SCENARIOS[name];
  if (!scenario) {
    await report({ phase: "result", scenario: name, ok: false,
                   error: `no scenario named "${name}"` });
    return;
  }
  try {
    const details = await scenario(context(given?.params ?? {}));
    await report({ phase: "result", scenario: name, ok: true, details: details ?? {} });
  } catch (problem) {
    await report({ phase: "result", scenario: name, ok: false,
                   error: problem instanceof Error ? `${problem.message}\n${problem.stack ?? ""}`
                                                   : String(problem) });
  }
}

/** A failed expectation inside a scenario. */
export function expect(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}
