/**
 * The read-only file viewer (D3a): CodeMirror 6, mounted inside a shadow
 * root.
 *
 * Why a shadow root: CodeMirror's styles come from style-mod, which uses a
 * constructable stylesheet (`adoptedStyleSheets`, set through the CSSOM) when
 * it is given a shadow root, and an inline `<style>` element otherwise. The
 * window's Content Security Policy (`style-src 'self'`, no `'unsafe-inline'`)
 * blocks the latter. The spike that chose CodeMirror (specs/005, research)
 * measured both on Windows, Linux and macOS.
 *
 * Colours are the design tokens' custom properties (`--text-keyword` …),
 * which inherit into the shadow root from the document.
 */

import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, keymap, lineNumbers } from "@codemirror/view";
import { HighlightStyle, StreamLanguage, bracketMatching, foldGutter, syntaxHighlighting } from "@codemirror/language";
import { defaultKeymap } from "@codemirror/commands";
import { search, searchKeymap } from "@codemirror/search";
import { tags } from "@lezer/highlight";

import type { languageOf } from "./files.ts";

type Language = ReturnType<typeof languageOf>;

const color = (role: string) => `var(--${role.replace(/\./g, "-")})`;

const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.modifier, tags.controlKeyword, tags.operatorKeyword, tags.definitionKeyword],
    color: color("text.keyword") },
  { tag: [tags.string, tags.special(tags.string), tags.regexp, tags.character], color: color("text.string") },
  { tag: [tags.number, tags.bool, tags.null, tags.atom, tags.unit], color: color("text.number") },
  { tag: [tags.typeName, tags.className, tags.namespace], color: color("text.type") },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: color("text.function") },
  { tag: [tags.propertyName, tags.attributeName], color: color("text.property") },
  { tag: [tags.tagName], color: color("text.tag") },
  { tag: [tags.comment, tags.lineComment, tags.blockComment, tags.docComment], color: color("text.comment"),
    fontStyle: "italic" },
  { tag: [tags.punctuation, tags.bracket, tags.separator, tags.operator], color: color("text.punctuation") },
  { tag: [tags.heading], color: color("text.keyword"), fontWeight: "600" },
  { tag: [tags.strong], color: color("text.primary"), fontWeight: "600" },
  { tag: [tags.emphasis], fontStyle: "italic" },
  { tag: [tags.link, tags.url], color: color("text.accent") },
]);

const theme = EditorView.theme({
  "&": { color: color("text.code"), backgroundColor: color("surface.base"), height: "100%", fontSize: "12.5px" },
  ".cm-scroller": { fontFamily: "\"JetBrains Mono\", monospace", lineHeight: "20px" },
  ".cm-content": { caretColor: color("border.focused") },
  "&.cm-focused": { outline: `1px solid ${color("border.focused")}`, outlineOffset: "-1px" },
  ".cm-gutters": { backgroundColor: color("surface.base"), color: color("text.muted"), border: "none" },
  // The bar ground, not the hover ground: every syntax colour reaches AA on it.
  ".cm-activeLine": { backgroundColor: color("surface.bar") },
  ".cm-activeLineGutter": { backgroundColor: color("surface.bar"), color: color("text.primary") },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": {
    backgroundColor: color("surface.selected") },
  ".cm-panels": { backgroundColor: color("surface.panel"), color: color("text.primary") },
  ".cm-panels input, .cm-panels button": { color: color("text.primary"), backgroundColor: color("surface.input"),
    border: `1px solid ${color("border.default")}` },
  ".cm-searchMatch": { backgroundColor: color("surface.plan") },
}, { dark: true });

async function languageExtension(language: Language): Promise<Extension> {
  switch (language) {
    case "typescript": return (await import("@codemirror/lang-javascript")).javascript({ typescript: true, jsx: true });
    case "javascript": return (await import("@codemirror/lang-javascript")).javascript({ jsx: true });
    case "css": return (await import("@codemirror/lang-css")).css();
    case "markdown": return (await import("@codemirror/lang-markdown")).markdown();
    case "yaml": return (await import("@codemirror/lang-yaml")).yaml();
    case "json": return (await import("@codemirror/lang-json")).json();
    case "python": return (await import("@codemirror/lang-python")).python();
    case "shell": return StreamLanguage.define((await import("@codemirror/legacy-modes/mode/shell")).shell);
    case "text": return [];
  }
}

export interface Viewer {
  show(text: string, language: Language, label: string): Promise<void>;
  focus(): void;
  destroy(): void;
  readonly view: EditorView;
}

/**
 * A read-only viewer inside `host`'s own shadow root. The text can be
 * selected, searched and read by a screen reader; it cannot be changed.
 */
export function createViewer(host: HTMLElement): Viewer {
  const root = host.shadowRoot ?? host.attachShadow({ mode: "open" });
  const frame = document.createElement("div");
  frame.className = "viewer-frame";
  frame.style.height = "100%";
  root.replaceChildren(frame);
  const base = (label: string, language: Extension): Extension[] => [
    lineNumbers(), foldGutter(), highlightActiveLine(), drawSelection(), bracketMatching(), search({ top: true }),
    keymap.of([...defaultKeymap, ...searchKeymap]), syntaxHighlighting(highlight), theme, language,
    EditorState.readOnly.of(true),
    // Read-only, yet still a focusable, navigable text for the keyboard and
    // screen readers. A key typed into it is cancelled before the browser's
    // own editing inserts anything: that insertion carries inline styles the
    // CSP refuses (measured in the spike), and the text must not change.
    EditorView.domEventHandlers({ beforeinput: (event) => { event.preventDefault(); return true; } }),
    EditorView.contentAttributes.of({ "aria-label": label, "aria-readonly": "true" }),
  ];
  const view = new EditorView({ parent: frame, root, state: EditorState.create({ doc: "", extensions: base("", []) }) });
  let generation = 0;
  return {
    view,
    async show(text, language, label) {
      const mine = ++generation;
      const extension = await languageExtension(language);
      // A newer file shown meanwhile wins: an older language load never replaces it.
      if (mine !== generation) return;
      view.setState(EditorState.create({ doc: text, extensions: base(label, extension) }));
    },
    focus() { view.focus(); },
    destroy() { generation += 1; view.destroy(); },
  };
}
