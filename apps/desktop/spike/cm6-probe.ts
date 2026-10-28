/**
 * D3 editor spike 2 (throwaway, never merged): CodeMirror 6 in the real
 * WebView under the window's unchanged CSP and `freezePrototype`.
 *
 * Mounted inside a shadow root, style-mod gives CodeMirror its styles through
 * a constructable stylesheet (`adoptedStyleSheets`, CSSOM) instead of a
 * `<style>` element; a second editor mounted in the document itself shows
 * what happens without that.
 */

import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";
import { HighlightStyle, StreamLanguage, syntaxHighlighting, bracketMatching, foldGutter } from "@codemirror/language";
import { defaultKeymap } from "@codemirror/commands";
import { search, searchKeymap, openSearchPanel, setSearchQuery, SearchQuery, findNext } from "@codemirror/search";
import { javascript } from "@codemirror/lang-javascript";
import { css } from "@codemirror/lang-css";
import { markdown } from "@codemirror/lang-markdown";
import { yaml } from "@codemirror/lang-yaml";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { tags } from "@lezer/highlight";

import { ADVERSARIAL, KEYWORD, eolCases, frames, hex, SAMPLE_TS, type ProbeHooks, type Data } from "./common.ts";

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: KEYWORD },
  { tag: [tags.string, tags.regexp], color: "#7fd39a" },
  { tag: tags.comment, color: "#5e5e5e", fontStyle: "italic" },
  { tag: [tags.number, tags.bool, tags.null], color: "#e0a04a" },
  { tag: tags.typeName, color: "#9be6f2" },
  { tag: tags.function(tags.variableName), color: "#8ab8ff" },
]);
const theme = EditorView.theme({
  "&": { color: "#d6d6d6", backgroundColor: "#191919", height: "100%" },
  ".cm-content": { fontFamily: "JetBrains Mono, monospace", caretColor: "#5fd4e8" },
  ".cm-gutters": { backgroundColor: "#191919", color: "#4a4a4a", border: "none" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": { backgroundColor: "#264f78" },
}, { dark: true });

function extensions(language: unknown, readOnly: boolean) {
  return [
    lineNumbers(), foldGutter(), highlightActiveLine(), drawSelection(), bracketMatching(), search(),
    keymap.of([...defaultKeymap, ...searchKeymap]),
    syntaxHighlighting(highlight), theme, language as never,
    EditorState.readOnly.of(readOnly),
    EditorView.contentAttributes.of({ "aria-label": readOnly ? "File (read-only)" : "File" }),
  ];
}

function host(id: string, top: number, height: number, shadow: boolean): { parent: Element | ShadowRoot; root: Document | ShadowRoot; box: HTMLElement } {
  const box = document.createElement("div");
  box.id = id;
  box.style.position = "fixed";
  box.style.left = "0px";
  box.style.top = `${top}px`;
  box.style.width = "900px";
  box.style.height = `${height}px`;
  box.style.zIndex = "2147483647";
  document.body.appendChild(box);
  if (!shadow) return { parent: box, root: document, box };
  const root = box.attachShadow({ mode: "open" });
  const inner = document.createElement("div");
  inner.style.height = "100%";
  root.appendChild(inner);
  return { parent: inner, root, box };
}

function tokenColour(scope: ParentNode, word: string): string | null {
  const span = [...scope.querySelectorAll<HTMLElement>(".cm-line span")].find((e) => e.textContent === word);
  return span ? hex(getComputedStyle(span).color) : null;
}

export async function probe(hooks: ProbeHooks): Promise<Data> {
  const results: Data = { editor: "codemirror6", versions: { view: "6.43.14", state: "6.7.6", styleMod: "4.1.4" } };

  // 1. Read-only viewer in a shadow root (the D3a candidate).
  hooks.phase("shadow-viewer");
  const viewer = host("cm-shadow", 0, 320, true);
  const started = performance.now();
  const view = new EditorView({
    parent: viewer.parent,
    root: viewer.root as ShadowRoot,
    state: EditorState.create({ doc: SAMPLE_TS, extensions: extensions(javascript({ typescript: true }), true) }),
  });
  await frames(3);
  const shadowRoot = viewer.root as ShadowRoot;
  results["shadowViewer"] = {
    createToFramesMs: Math.round(performance.now() - started),
    lines: shadowRoot.querySelectorAll(".cm-line").length,
    keywordColour: tokenColour(shadowRoot, "export"), expectedKeywordColour: KEYWORD,
    background: hex(getComputedStyle(shadowRoot.querySelector(".cm-editor") as Element).backgroundColor),
    adoptedSheets: shadowRoot.adoptedStyleSheets.length,
    adoptedRules: shadowRoot.adoptedStyleSheets.reduce((n, s) => n + s.cssRules.length, 0),
    styleElementsInDocument: document.querySelectorAll("style").length,
    contenteditable: view.contentDOM.getAttribute("contenteditable"),
    role: view.contentDOM.getAttribute("role"), ariaReadonly: view.contentDOM.getAttribute("aria-readonly"),
  };
  // Selection is drawn by CodeMirror's own layer: measure it.
  view.dispatch({ selection: { anchor: 0, head: 60 } });
  view.focus();
  await frames(3);
  const selections = [...shadowRoot.querySelectorAll<HTMLElement>(".cm-selectionBackground")].map((e) => {
    const r = e.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  });
  results["selection"] = { rects: selections, visible: selections.some((r) => r.w > 0 && r.h > 0) };
  // Typing into the read-only viewer must change nothing.
  const before = view.state.doc.toString();
  const keyReadOnly = await hooks.pressQ();
  await frames(4);
  results["readOnlyTyping"] = { osKey: keyReadOnly, unchanged: view.state.doc.toString() === before };
  results["shotViewer"] = await hooks.shot("spike-cm6-viewer");
  // axe-core builds its own elements while it measures: a phase of its own.
  hooks.phase("axe");
  results["axeViewer"] = await hooks.axe("CodeMirror 6 viewer in a shadow root");
  hooks.phase("shadow-viewer-after-axe");

  // 2. Editable instance: OS-level typing reaches it.
  hooks.phase("shadow-editable");
  const editHost = host("cm-edit", 330, 120, true);
  const edit = new EditorView({
    parent: editHost.parent, root: editHost.root as ShadowRoot,
    state: EditorState.create({ doc: "", extensions: extensions(javascript(), false) }),
  });
  edit.focus();
  await frames(2);
  const key = await hooks.pressQ();
  await frames(5);
  results["editableTyping"] = { osKey: key, doc: edit.state.doc.toString(), reached: edit.state.doc.toString().includes("q"), focused: edit.hasFocus };

  // 3. Adversarial content: prototype member names as words in every language,
  // typed, searched and folded. Under freezePrototype a plain-object map keyed
  // by text throws; every error is recorded.
  hooks.phase("adversarial");
  const errors: string[] = [];
  const onError = (e: ErrorEvent) => errors.push(String(e.message));
  (window as unknown as { __spikeCapture?: boolean }).__spikeCapture = true;
  window.addEventListener("error", onError);
  const languages: Array<[string, unknown]> = [["ts", javascript({ typescript: true })], ["js", javascript()],
    ["css", css()], ["md", markdown()], ["yaml", yaml()], ["shell", StreamLanguage.define(shell)]];
  const adversarial: Data[] = [];
  for (const [name, language] of languages) {
    try {
      edit.setState(EditorState.create({ doc: ADVERSARIAL[name] ?? "", extensions: extensions(language, false) }));
      await frames(2);
      edit.dispatch(edit.state.replaceSelection(" constructor toString __proto__ hasOwnProperty valueOf "));
      openSearchPanel(edit);
      edit.dispatch({ effects: setSearchQuery.of(new SearchQuery({ search: "constructor" })) });
      findNext(edit);
      await frames(2);
      adversarial.push({ language: name, ok: true });
    } catch (problem) {
      adversarial.push({ language: name, ok: false, error: String(problem) });
    }
  }
  window.removeEventListener("error", onError);
  (window as unknown as { __spikeCapture?: boolean }).__spikeCapture = false;
  results["adversarial"] = { cases: adversarial, pageErrors: errors };

  // 4. A 2,000,000-byte file.
  hooks.phase("large");
  const line = `${"const value = 1234567890; // padding ".repeat(2).slice(0, 79)}\n`;
  const big = line.repeat(Math.ceil(2_000_000 / line.length)).slice(0, 2_000_000);
  const bigStarted = performance.now();
  view.setState(EditorState.create({ doc: big, extensions: extensions(javascript({ typescript: true }), true) }));
  await frames(3);
  const shown = Math.round(performance.now() - bigStarted);
  const endStarted = performance.now();
  view.dispatch({ selection: { anchor: view.state.doc.length }, scrollIntoView: true });
  await frames(3);
  results["large"] = { bytes: big.length, lines: view.state.doc.lines, firstFramesMs: shown,
                       revealEndMs: Math.round(performance.now() - endStarted),
                       renderedLines: shadowRoot.querySelectorAll(".cm-line").length };

  // 5. Line endings and the BOM.
  hooks.phase("eol");
  results["eol"] = eolCases((text) => {
    const state = EditorState.create({ doc: text });
    return { value: state.doc.toString(), lines: state.doc.lines, separatorKept: state.sliceDoc() === text };
  });

  // 6. The same viewer mounted in the document itself (no shadow root).
  hooks.phase("document-viewer");
  const plain = host("cm-plain", 460, 160, false);
  const violationsBefore = hooks.violations().length;
  const plainView = new EditorView({
    parent: plain.parent as Element,
    state: EditorState.create({ doc: SAMPLE_TS, extensions: extensions(javascript({ typescript: true }), true) }),
  });
  await frames(3);
  results["documentViewer"] = { keywordColour: tokenColour(plain.box, "export"),
                                violationsDuring: hooks.violations().length - violationsBefore,
                                styleElementsInDocument: document.querySelectorAll("style").length };
  results["shotDocument"] = await hooks.shot("spike-cm6-document-mount");
  plainView.destroy();
  plain.box.remove();
  view.destroy();
  edit.destroy();
  viewer.box.remove();
  editHost.box.remove();
  return results;
}
