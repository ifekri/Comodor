/** D3 editor spike 2 (throwaway, never merged): helpers shared by the probes. */

export type Data = Record<string, unknown>;

export interface ProbeHooks {
  violations(): unknown[];
  phase(name: string): void;
  policy(): string | null;
  shot(name: string): Promise<Data>;
  /** The plain letter `q`, delivered by the operating system to the window. */
  pressQ(): Promise<Data | null>;
  /** WCAG 2.1 A/AA violations in the whole document (axe-core). */
  axe(where: string): Promise<Data>;
}

export const KEYWORD = "#5fd4e8";

export const SAMPLE_TS = [
  "import { readFile } from \"node:fs\";",
  "// Comodor D3 spike",
  "export async function load(path: string): Promise<number> {",
  "  const text = await readFile(path, \"utf-8\");",
  "  return text.length * 2;",
  "}",
  "",
].join("\n");

/** Every name a frozen Object.prototype holds, as words in each language. */
const WORDS = "constructor toString __proto__ hasOwnProperty valueOf isPrototypeOf propertyIsEnumerable toLocaleString __defineGetter__";
export const ADVERSARIAL: Record<string, string> = {
  ts: `class constructor { toString(): string { return "${WORDS}"; } }\nconst valueOf = { __proto__: null, hasOwnProperty: 1 };\n// ${WORDS}\n`,
  js: `function toString() { return { constructor: 1, valueOf: 2 }; }\nlet __proto__ = "${WORDS}";\n`,
  css: `.constructor { toString: valueOf; }\n#hasOwnProperty::before { content: "${WORDS}"; }\n`,
  md: `# constructor\n\n- toString\n- __proto__\n\n\`hasOwnProperty\` ${WORDS}\n`,
  yaml: `constructor: toString\n__proto__:\n  hasOwnProperty: valueOf\nwords: "${WORDS}"\n`,
  shell: `constructor=toString\nfunction valueOf() { echo "${WORDS}"; }\nhasOwnProperty --__proto__\n`,
};

export function frames(count: number): Promise<void> {
  return new Promise((resolve) => {
    let left = count;
    const step = () => (--left <= 0 ? resolve() : requestAnimationFrame(step));
    requestAnimationFrame(step);
  });
}

export function hex(rgb: string): string {
  const parts = rgb.match(/\d+/g)?.slice(0, 3).map(Number) ?? [];
  return parts.length === 3 ? `#${parts.map((n) => n.toString(16).padStart(2, "0")).join("")}` : rgb;
}

/** Line endings and the BOM: what the editor's model keeps of each file. */
export function eolCases(model: (text: string) => Data): Data[] {
  const cases: Array<[string, string]> = [
    ["lf", "a\nb\n"], ["crlf", "a\r\nb\r\n"], ["cr", "a\rb\r"], ["mixed", "a\r\nb\nc\r\n"],
    ["bom-lf", "﻿a\nb\n"], ["no-final-newline", "a\nb"],
  ];
  return cases.map(([name, text]) => {
    const seen = model(text);
    const value = String(seen["value"] ?? "");
    return { ...seen, name, input: JSON.stringify(text), value: JSON.stringify(value), keptExactly: value === text,
             keepsBom: value.charCodeAt(0) === 0xfeff };
  });
}
