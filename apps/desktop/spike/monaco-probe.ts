/**
 * D3 editor spike 2 (throwaway, never merged): Monaco 0.57.0 in the real
 * WebView, kept loadable under freezePrototype by the spike-1 build transform
 * (vite.config.ts), with the window's CSP unchanged.
 *
 * Questions: does adversarial file content (prototype member names) break it
 * under freezePrototype; does it draw a selection without inline style
 * attributes; can its colours be restored without inline styles (its own
 * blocked rules re-delivered through a constructable stylesheet, which is
 * what a static stylesheet built from the same rules would give).
 */

import * as monaco from "monaco-editor/editor/editor.api";
import "monaco-editor/internal/common/workers";
import "monaco-editor/languages/definitions/typescript/register";
import "monaco-editor/languages/definitions/javascript/register";
import "monaco-editor/languages/definitions/css/register";
import "monaco-editor/languages/definitions/markdown/register";
import "monaco-editor/languages/definitions/shell/register";
import "monaco-editor/languages/definitions/yaml/register";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

import { ADVERSARIAL, KEYWORD, frames, hex, SAMPLE_TS, type ProbeHooks, type Data } from "./common.ts";

function box(id: string, top: number, height: number): HTMLDivElement {
  const host = document.createElement("div");
  host.id = id;
  host.style.position = "fixed";
  host.style.left = "0px";
  host.style.top = `${top}px`;
  host.style.width = "900px";
  host.style.height = `${height}px`;
  host.style.zIndex = "2147483647";
  document.body.appendChild(host);
  return host;
}

function tokenColour(host: HTMLElement, word: string): string | null {
  const span = [...host.querySelectorAll<HTMLElement>(".view-line span span")].find((e) => e.textContent === word);
  return span ? hex(getComputedStyle(span).color) : null;
}

function selectionRects(host: HTMLElement): Data[] {
  return [...host.querySelectorAll<HTMLElement>(".selected-text")].map((e) => {
    const r = e.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), styleAttribute: e.getAttribute("style") };
  });
}

export async function probe(hooks: ProbeHooks): Promise<Data> {
  let workers = 0;
  (self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
    getWorker() { workers += 1; return new EditorWorker(); },
  };
  const results: Data = { editor: "monaco", version: "0.57.0" };
  monaco.editor.defineTheme("comodor-spike", {
    base: "vs-dark", inherit: true,
    rules: [{ token: "keyword", foreground: KEYWORD.slice(1) }, { token: "string", foreground: "7FD39A" }],
    colors: { "editor.background": "#191919" },
  });

  hooks.phase("viewer");
  const host = box("monaco-view", 0, 320);
  const view = monaco.editor.create(host, { value: SAMPLE_TS, language: "typescript", theme: "comodor-spike",
                                            readOnly: true, minimap: { enabled: false }, automaticLayout: false });
  view.layout({ width: 900, height: 320 });
  await frames(3);
  view.setSelection(new monaco.Selection(1, 1, 3, 20));
  view.focus();
  await frames(3);
  results["withoutRecovery"] = { keywordColour: tokenColour(host, "export"), expected: KEYWORD,
                                 selection: selectionRects(host), violations: hooks.violations().length };
  results["shotBefore"] = await hooks.shot("spike-monaco-before-recovery");

  // Re-deliver Monaco's own (blocked) <style> rules through a constructable
  // stylesheet: the colours a static stylesheet of the same rules would give.
  hooks.phase("recovery");
  const text = [...document.querySelectorAll("style")].map((s) => s.textContent ?? "").join("\n");
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(text);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  view.setSelection(new monaco.Selection(1, 1, 3, 21));
  await frames(3);
  const violationsBeforeRecovery = Number((results["withoutRecovery"] as Data)["violations"]);
  results["withRecovery"] = { rulesRecovered: sheet.cssRules.length, keywordColour: tokenColour(host, "export"),
                              background: hex(getComputedStyle(host.querySelector(".monaco-editor") as Element).backgroundColor),
                              selection: selectionRects(host),
                              newViolations: hooks.violations().length - violationsBeforeRecovery };
  results["shotAfter"] = await hooks.shot("spike-monaco-after-recovery");
  // axe-core builds its own elements while it measures: a phase of its own.
  hooks.phase("axe");
  results["axe"] = await hooks.axe("Monaco viewer");
  hooks.phase("recovery-after-axe");

  // Adversarial content under freezePrototype.
  hooks.phase("adversarial");
  const errors: string[] = [];
  const onError = (e: ErrorEvent) => errors.push(String(e.message));
  const onRejection = (e: PromiseRejectionEvent) => { e.preventDefault(); errors.push(`rejection: ${String(e.reason)}`); };
  (window as unknown as { __spikeCapture?: boolean }).__spikeCapture = true;
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  const edit = monaco.editor.create(box("monaco-edit", 330, 160), { value: "", theme: "comodor-spike",
                                                                    minimap: { enabled: false } });
  edit.layout({ width: 900, height: 160 });
  const cases: Data[] = [];
  for (const [name, language] of [["ts", "typescript"], ["js", "javascript"], ["css", "css"], ["md", "markdown"],
                                  ["yaml", "yaml"], ["shell", "shell"]] as const) {
    try {
      const model = monaco.editor.createModel(ADVERSARIAL[name] ?? "", language);
      edit.setModel(model);
      await frames(3);
      edit.focus();
      edit.trigger("spike", "type", { text: " constructor toString __proto__ hasOwnProperty valueOf " });
      edit.trigger("spike", "editor.action.triggerSuggest", {});
      await frames(3);
      edit.trigger("spike", "actions.find", {});
      await frames(3);
      // Word-based suggestions run in the editor worker over the model's words.
      await new Promise((resolve) => setTimeout(resolve, 600));
      cases.push({ language: name, ok: true });
    } catch (problem) {
      cases.push({ language: name, ok: false, error: String(problem) });
    }
  }
  window.removeEventListener("error", onError);
  (window as unknown as { __spikeCapture?: boolean }).__spikeCapture = false;
  window.removeEventListener("unhandledrejection", onRejection);
  results["adversarial"] = { cases, pageErrors: errors, workersConstructed: workers };
  view.dispose();
  edit.dispose();
  return results;
}
