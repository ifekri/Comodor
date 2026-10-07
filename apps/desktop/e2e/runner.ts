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
  query(what: "listeners" | "core_pid" | "chooser" | "refused" | "confirmations"): Promise<Data>;
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

/** How long a scenario may run in the page; the harness allows longer. */
const PAGE_DEADLINE_MS = 120_000;

/** Everything the page holds: its storage and its document (SC-009). */
export async function holdings(): Promise<Data> {
  const entries = (store: Storage) => Object.fromEntries(
    Array.from({ length: store.length }, (_, index) => store.key(index)!)
      .map((key) => [key, store.getItem(key)]));
  const databases = typeof indexedDB.databases === "function" ? await indexedDB.databases() : [];
  return {
    localStorage: entries(localStorage),
    sessionStorage: entries(sessionStorage),
    indexedDB: databases.map((database) => database.name ?? ""),
    document: document.documentElement.outerHTML,
  };
}

/** What the page showed, for a failure's report. */
function page(): string {
  return (document.body?.innerHTML ?? "").slice(0, 4000);
}

/** Run the scenario the native side named, then report its verdict. */
export async function runScenario(): Promise<void> {
  const given = window.__COMODOR_E2E__;
  const name = given?.scenario ?? "";
  // One verdict per run. An error anywhere in the page ends the run at once,
  // with what the page showed, rather than leaving it to the deadline.
  let ended = false;
  const verdict = async (result: Data) => {
    if (ended) return;
    ended = true;
    await report({ phase: "result", scenario: name, ...result });
  };
  window.addEventListener("error", (event) => {
    void verdict({ ok: false, error: `page error: ${event.message}`, page: page() });
  });
  window.addEventListener("unhandledrejection", (event) => {
    void verdict({ ok: false, error: `unhandled rejection: ${String(event.reason)}`, page: page() });
  });
  // Ahead of the harness's own deadline, so a stalled run says what the page
  // showed instead of being killed blind. A bound on failure, never a delay.
  setTimeout(() => {
    void verdict({ ok: false, error: "the page did not finish by its deadline", page: page() });
  }, PAGE_DEADLINE_MS);
  const scenario = SCENARIOS[name];
  if (!scenario) {
    await verdict({ ok: false, error: `no scenario named "${name}"` });
    return;
  }
  try {
    const details = await scenario(context(given?.params ?? {}));
    // What the page holds goes with every verdict, so the harness can search
    // it for the credential canary.
    await verdict({ ok: true, details: details ?? {}, held: await holdings() });
  } catch (problem) {
    await verdict({ ok: false, page: page(),
                    error: problem instanceof Error ? `${problem.message}\n${problem.stack ?? ""}`
                                                    : String(problem) });
  }
}

/** A failed expectation inside a scenario. */
export function expect(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

/** Type into a text field as a person does, so React sees the input. */
export function typeInto(element: Element, text: string): void {
  const field = element as HTMLInputElement | HTMLTextAreaElement;
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field) as object, "value")?.set;
  setter?.call(field, text);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

export function pressKey(element: Element, key: string): void {
  element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

/** The first `selector` match whose text includes `text`. */
export function withText(selector: string, text: string, root: ParentNode = document): HTMLElement | null {
  return [...root.querySelectorAll<HTMLElement>(selector)]
    .find((element) => (element.textContent ?? "").includes(text)) ?? null;
}
