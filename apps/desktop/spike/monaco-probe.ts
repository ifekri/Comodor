/**
 * D3 spike (throwaway, never merged): Monaco under the window's unchanged
 * Content Security Policy, in the real WebView. See spike/README.md.
 *
 * Imported only by the `spike-monaco` scenario, so Monaco is in the test
 * build's bundle as a separate chunk and nowhere else.
 */

import * as monaco from "monaco-editor/editor/editor.api";
// The editor core with its contributions (find, folding, hover, …) and the
// codicon font: no language service and no language worker.
import "monaco-editor/internal/common/workers";
import "monaco-editor/languages/definitions/typescript/register";
import "monaco-editor/languages/definitions/javascript/register";
import "monaco-editor/languages/definitions/css/register";
import "monaco-editor/languages/definitions/markdown/register";
import "monaco-editor/languages/definitions/shell/register";
import "monaco-editor/languages/definitions/yaml/register";
// The base editor worker, as Vite bundles a worker: a separate file from 'self'.
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

type Data = Record<string, unknown>;

export interface Violation {
  directive: string;
  effective: string;
  blocked: string;
  sample: string;
  source: string;
  line: number;
  disposition: string;
  phase: string;
}

export interface ProbeHooks {
  /** All violations seen so far, in order (the scenario listens from the start). */
  violations(): Violation[];
  /** Name the phase that later violations belong to. */
  phase(name: string): void;
  /** The effective policy, from the first violation's `originalPolicy`. */
  policy(): string | null;
  /** A screenshot of the real window, taken by the operating system. */
  shot(name: string): Promise<Data>;
  /** Deliver the plain letter `q` through the operating system; null if not possible. */
  pressQ(): Promise<Data | null>;
}

const KEYWORD = "#5fd4e8"; // the reference's keyword colour (§6.3)

const worker = { constructed: 0, failedToConstruct: [] as string[], messages: 0, errors: [] as string[] };
const consoleNotes: string[] = [];

function installEnvironment(): void {
  (self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
    getWorker(_moduleId: string, label: string) {
      try {
        const created = new EditorWorker();
        worker.constructed += 1;
        created.addEventListener("message", () => { worker.messages += 1; });
        created.addEventListener("error", (event) => {
          worker.errors.push(`${label}: ${(event as ErrorEvent).message ?? "error event"}`);
        });
        return created;
      } catch (problem) {
        worker.failedToConstruct.push(`${label}: ${String(problem)}`);
        throw problem;
      }
    },
  };
  for (const level of ["warn", "error"] as const) {
    const original = console[level].bind(console);
    console[level] = (...args: unknown[]) => {
      const text = args.map(String).join(" ");
      if (/worker|Content Security|style|font|Refused/i.test(text)) consoleNotes.push(`${level}: ${text.slice(0, 400)}`);
      original(...args);
    };
  }
}

function frames(count: number): Promise<void> {
  return new Promise((resolve) => {
    let left = count;
    const step = () => (--left <= 0 ? resolve() : requestAnimationFrame(step));
    requestAnimationFrame(step);
  });
}

function container(id: string, top: number, height: number): HTMLDivElement {
  const host = document.createElement("div");
  host.id = id;
  // CSSOM property writes, which the policy does not govern (only a style
  // attribute or a <style> element would be).
  host.style.position = "fixed";
  host.style.left = "0px";
  host.style.top = `${top}px`;
  host.style.width = "900px";
  host.style.height = `${height}px`;
  host.style.zIndex = "2147483647";
  host.style.background = "#191919";
  document.body.appendChild(host);
  return host;
}

function hex(rgb: string): string {
  const parts = rgb.match(/\d+/g)?.slice(0, 3).map(Number) ?? [];
  return parts.length === 3 ? `#${parts.map((n) => n.toString(16).padStart(2, "0")).join("")}` : rgb;
}

/** The computed colour of the first rendered token whose text is exactly `word`. */
function tokenColour(host: HTMLElement, word: string): string | null {
  const spans = [...host.querySelectorAll<HTMLElement>(".view-line span span")];
  const span = spans.find((element) => element.textContent === word);
  return span ? hex(getComputedStyle(span).color) : null;
}

function styleElements(): Data {
  const all = [...document.querySelectorAll("style")];
  return {
    count: all.length,
    withNonce: all.filter((element) => (element as HTMLStyleElement).nonce).length,
    withRules: all.filter((element) => {
      try { return ((element as HTMLStyleElement).sheet?.cssRules.length ?? 0) > 0; } catch { return false; }
    }).length,
  };
}

const SAMPLE = [
  "import { readFile } from \"node:fs\";",
  "// Comodor D3 spike",
  "export async function load(path: string): Promise<number> {",
  "  const text = await readFile(path, \"utf-8\");",
  "  return text.length * 2;",
  "}",
  "",
].join("\n");

function eolCases(): Data[] {
  const cases: Array<[string, string]> = [
    ["lf", "a\nb\n"],
    ["crlf", "a\r\nb\r\n"],
    ["cr", "a\rb\r"],
    ["mixed", "a\r\nb\nc\r\n"],
    ["bom-lf", "﻿a\nb\n"],
    ["no-final-newline", "a\nb"],
  ];
  const esc = (text: string) => JSON.stringify(text);
  return cases.map(([name, text]) => {
    const model = monaco.editor.createModel(text, "plaintext");
    const value = model.getValue();
    const defined = model.getValue(monaco.editor.EndOfLinePreference.TextDefined);
    // An edit at the end, the way typing a new line would.
    const end = model.getFullModelRange().getEndPosition();
    model.pushEditOperations([], [{ range: new monaco.Range(end.lineNumber, end.column, end.lineNumber, end.column),
                                    text: "z\n" }], () => null);
    const edited = model.getValue();
    const result = {
      name, input: esc(text), eol: esc(model.getEOL()), lines: model.getLineCount(),
      valueEqualsInput: value === text, value: esc(value), textDefinedEqualsInput: defined === text,
      keepsBom: value.charCodeAt(0) === 0xfeff, afterEdit: esc(edited),
    };
    model.dispose();
    return result;
  });
}

async function waitForWorker(host: HTMLElement): Promise<Data> {
  // A diff is computed by the editor worker (or, if it cannot start, on the
  // main thread): the update event says the computation finished.
  const diff = monaco.editor.createDiffEditor(host, { readOnly: true, automaticLayout: false });
  const original = monaco.editor.createModel("one\ntwo\nthree\n", "plaintext");
  const modified = monaco.editor.createModel("one\n2\nthree\nfour\n", "plaintext");
  const started = performance.now();
  const updated = new Promise<void>((resolve) => { diff.onDidUpdateDiff(() => resolve()); });
  diff.setModel({ original, modified });
  diff.layout({ width: 900, height: 160 });
  await updated;
  const changes = diff.getLineChanges();
  const data = { diffMs: Math.round(performance.now() - started), lineChanges: changes?.length ?? null };
  diff.dispose();
  original.dispose();
  modified.dispose();
  return data;
}

export async function probe(hooks: ProbeHooks): Promise<Data> {
  installEnvironment();
  const results: Data = { monaco: "0.57.0", userAgent: navigator.userAgent };

  // 1. Theme and a read-only editor, as PR-1 would show a file.
  hooks.phase("editor");
  monaco.editor.defineTheme("comodor-spike", {
    base: "vs-dark", inherit: true,
    rules: [{ token: "keyword", foreground: KEYWORD.slice(1) }, { token: "comment", foreground: "5E5E5E", fontStyle: "italic" },
            { token: "string", foreground: "7FD39A" }],
    colors: { "editor.background": "#191919" },
  });
  const viewHost = container("spike-view", 0, 320);
  const started = performance.now();
  const view = monaco.editor.create(viewHost, {
    value: SAMPLE, language: "typescript", theme: "comodor-spike", readOnly: true,
    fontFamily: "JetBrains Mono, monospace", fontSize: 13, lineHeight: 20, minimap: { enabled: false },
    automaticLayout: false,
  });
  view.layout({ width: 900, height: 320 });
  await frames(3);
  results["editor"] = {
    createToFramesMs: Math.round(performance.now() - started),
    renderedLines: viewHost.querySelectorAll(".view-line").length,
    keywordColour: tokenColour(viewHost, "export"),
    expectedKeywordColour: KEYWORD,
    editorBackground: hex(getComputedStyle(viewHost.querySelector(".monaco-editor") as Element).backgroundColor),
    styles: styleElements(),
  };
  results["shotEditor"] = await hooks.shot("spike-monaco-editor");

  // 2. The base editor worker.
  hooks.phase("worker");
  const diffHost = container("spike-diff", 330, 160);
  results["worker"] = { ...(await waitForWorker(diffHost)), ...worker, consoleNotes: [...consoleNotes] };
  diffHost.remove();

  // 3. Line endings and the BOM in Monaco's model.
  hooks.phase("eol");
  results["eol"] = eolCases();

  // 4. Typing: Monaco's own command, then a key from the operating system.
  hooks.phase("typing");
  const editHost = container("spike-edit", 330, 120);
  const edit = monaco.editor.create(editHost, { value: "", language: "plaintext", theme: "comodor-spike",
                                                minimap: { enabled: false } });
  edit.layout({ width: 900, height: 120 });
  edit.focus();
  const typeStarted = performance.now();
  for (let at = 0; at < 200; at += 1) edit.trigger("spike", "type", { text: "x" });
  const typed = { programmatic200Ms: Math.round(performance.now() - typeStarted),
                  programmaticLength: edit.getModel()?.getValueLength() ?? null };
  edit.setValue("");
  edit.focus();
  const before = edit.getValue();
  const osKey = await hooks.pressQ();
  await frames(5);
  results["typing"] = { ...typed, osKey, osBefore: before, osAfter: edit.getValue(),
                        osReachedEditor: edit.getValue().includes("q"),
                        focused: edit.hasTextFocus() };
  edit.dispose();
  editHost.remove();

  // 5. A 2,000,000-byte file.
  hooks.phase("large");
  const line = `${"const value = 1234567890; // padding ".repeat(2).slice(0, 79)}\n`;
  const big = line.repeat(Math.ceil(2_000_000 / line.length)).slice(0, 2_000_000);
  const bigStarted = performance.now();
  const bigModel = monaco.editor.createModel(big, "typescript");
  const modelMs = Math.round(performance.now() - bigStarted);
  view.setModel(bigModel);
  await frames(3);
  const shownMs = Math.round(performance.now() - bigStarted);
  const revealStarted = performance.now();
  view.revealLine(bigModel.getLineCount());
  await frames(3);
  results["large"] = { bytes: big.length, lines: bigModel.getLineCount(), modelMs, firstFramesMs: shownMs,
                       revealEndMs: Math.round(performance.now() - revealStarted) };
  view.setModel(monaco.editor.createModel(SAMPLE, "typescript"));
  bigModel.dispose();
  await frames(2);

  // 6. Experiment, labelled as such: give Monaco's runtime <style> elements
  // the page's style nonce, if the effective policy has one and the page can
  // read it. A measurement of what a nonce would change, not a proposal.
  hooks.phase("nonce-experiment");
  const policy = hooks.policy() ?? "";
  const styleNonce = /style-src[^;]*'nonce-([^']+)'/.exec(policy)?.[1] ?? null;
  const readable = [...document.querySelectorAll<HTMLElement>("[nonce]")].map((element) => element.nonce).find(Boolean) ?? null;
  const experiment: Data = { policyHasStyleNonce: Boolean(styleNonce), pageCanReadNonce: Boolean(readable) };
  const nonce = styleNonce ?? readable;
  if (nonce) {
    const append = Node.prototype.appendChild;
    try {
      Node.prototype.appendChild = function <T extends Node>(this: Node, child: T): T {
        if (child instanceof HTMLStyleElement && !child.nonce) child.nonce = nonce;
        return append.call(this, child) as T;
      };
    } catch (problem) {
      experiment["patchFailed"] = String(problem);
    }
    const before = hooks.violations().length;
    monaco.editor.defineTheme("comodor-spike-2", {
      base: "vs-dark", inherit: true, rules: [{ token: "keyword", foreground: "E0605A" }], colors: {},
    });
    const host = container("spike-nonce", 330, 160);
    const second = monaco.editor.create(host, { value: SAMPLE, language: "typescript", theme: "comodor-spike-2",
                                                readOnly: true, minimap: { enabled: false } });
    second.layout({ width: 900, height: 160 });
    await frames(3);
    experiment["violationsDuring"] = hooks.violations().length - before;
    experiment["keywordColour"] = tokenColour(host, "export");
    experiment["expectedKeywordColour"] = "#e0605a";
    results["shotNonce"] = await hooks.shot("spike-monaco-nonce-experiment");
    second.dispose();
    host.remove();
    Node.prototype.appendChild = append;
  } else {
    experiment["note"] = "no style nonce in the effective policy and none readable: nothing to try";
  }
  results["nonceExperiment"] = experiment;

  view.dispose();
  viewHost.remove();
  return results;
}
