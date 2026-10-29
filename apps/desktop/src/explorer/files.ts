/**
 * The workspace's files, as the Core reports them (D3a).
 *
 * The window never touches the disk: every listing and every file's text
 * comes from the Core's `workspace.list`, `workspace.stat` and
 * `workspace.read`, which refuse what may not be shown. This module is the
 * window's side of that contract, without React: the tree's state, its pages,
 * and what each refusal says to a person.
 */

import type { CoreClient } from "@comodor/client";
import { ProtocolError } from "@comodor/protocol";

/** The Core's capability for these methods; without it the window says so. */
export const WORKSPACE_FILES = "workspace_files";

export interface Entry {
  readonly name: string;
  /** Workspace-relative, `/`-separated. */
  readonly path: string;
  readonly kind: "file" | "directory";
  readonly link?: boolean;
  readonly size?: number;
  /** Why it may not be opened; it is listed so the folder is not misrepresented. */
  readonly refused?: string;
}

export interface Page {
  readonly path: string;
  readonly entries: readonly Entry[];
  readonly cursor?: string;
}

/** A file's text, or why there is none. */
export type FileContent =
  | { readonly kind: "text"; readonly path: string; readonly size: number; readonly text: string;
      readonly encoding: string; readonly bom: boolean; readonly replaced: boolean;
      readonly eol: string; readonly lines: number; readonly hash: string }
  | { readonly kind: "unavailable"; readonly path: string; readonly size: number; readonly reason: string }
  | { readonly kind: "refused"; readonly path: string; readonly reason: string; readonly message: string };

/** What a person reads for each reason the Core gives. */
const MESSAGES: Readonly<Record<string, string>> = {
  not_found: "This file is no longer there.",
  not_a_directory: "This is not a folder.",
  not_a_file: "This is not a file that can be shown: a folder, or a pipe or device.",
  bad_path: "This path is not inside the workspace.",
  bad_cursor: "The folder changed; refresh it to see its contents.",
  outside_workspace: "This leads outside the workspace, so it is not opened here.",
  comodor_data: "This is Comodor's own data, which is not shown here.",
  workspace_is_comodor_data: "This folder is Comodor's own data folder, so its files are not shown here. "
    + "Open another folder, or point COMODOR_HOME elsewhere.",
  sensitive_name: "This file may contain secrets, so Comodor does not open it here. Open it in your own editor.",
  secret_content: "This file appears to contain a secret, so Comodor does not open it here. "
    + "Open it in your own editor.",
  permission_denied: "This cannot be read: the system refused access.",
  too_large: "This file is too large to open here.",
  binary: "This is a binary file, so it is not shown as text.",
  changed: "This path changed while it was being opened, so nothing was shown. Refresh and try again.",
  cannot_confine: "This system cannot open files without the risk of following a path that changed underneath, "
    + "so Comodor does not show the workspace's files here.",
};

export function reasonText(reason: string, size?: number): string {
  if (reason === "too_large" && size !== undefined) {
    return `This file is too large to open here (${size.toLocaleString("en-US")} bytes; the limit is 2,000,000).`;
  }
  return MESSAGES[reason] ?? "The Core could not show this.";
}

/** The reason a failed call carries, or null when it is not a file refusal. */
export function refusalReason(problem: unknown): string | null {
  if (problem instanceof ProtocolError || (problem as { data?: unknown })?.data) {
    const reason = (problem as { data?: Record<string, unknown> }).data?.["reason"];
    return typeof reason === "string" ? reason : null;
  }
  return null;
}

export function offersFiles(client: CoreClient | null): boolean {
  return Boolean(client?.handshake?.capabilities?.includes(WORKSPACE_FILES));
}

export async function listPage(client: CoreClient, path: string, cursor?: string): Promise<Page> {
  const result = await client.call("workspace.list", cursor ? { path, cursor } : { path });
  return result as unknown as Page;
}

export async function readFile(client: CoreClient, path: string): Promise<FileContent> {
  try {
    const result = await client.call("workspace.read", { path }) as Record<string, unknown>;
    const size = Number(result["size"] ?? 0);
    if (typeof result["unavailable"] === "string") {
      return { kind: "unavailable", path, size, reason: result["unavailable"] };
    }
    return {
      kind: "text", path, size, text: String(result["text"] ?? ""), encoding: String(result["encoding"] ?? "utf-8"),
      bom: Boolean(result["bom"]), replaced: Boolean(result["replaced"]), eol: String(result["eol"] ?? "none"),
      lines: Number(result["lines"] ?? 0), hash: String(result["hash"] ?? ""),
    };
  } catch (problem) {
    const reason = refusalReason(problem);
    if (reason === null) throw problem;
    return { kind: "refused", path, reason, message: reasonText(reason) };
  }
}

/** One folder as the tree holds it. */
export interface FolderState {
  readonly entries: readonly Entry[];
  /** Present while the Core has more of this folder to give. */
  readonly cursor?: string;
  readonly loading: boolean;
  readonly error?: string;
}

/** The tree: which folders are open, and what each has shown so far. */
export interface TreeState {
  readonly folders: Readonly<Record<string, FolderState>>;
  readonly expanded: ReadonlySet<string>;
}

export const EMPTY_TREE: TreeState = { folders: {}, expanded: new Set([""]) };

export type TreeAction =
  | { type: "loading"; path: string }
  | { type: "page"; path: string; page: Page; append: boolean }
  | { type: "failed"; path: string; reason: string }
  | { type: "toggle"; path: string }
  | { type: "collapseAll" }
  | { type: "reset" };

export function treeReducer(state: TreeState, action: TreeAction): TreeState {
  switch (action.type) {
    case "loading": {
      const previous = state.folders[action.path];
      return { ...state, folders: { ...state.folders, [action.path]: { entries: previous?.entries ?? [],
        ...(previous?.cursor ? { cursor: previous.cursor } : {}), loading: true } } };
    }
    case "page": {
      const previous = action.append ? state.folders[action.path]?.entries ?? [] : [];
      // A page never repeats an entry the folder already shows.
      const known = new Set(previous.map((entry) => entry.path));
      const entries = [...previous, ...action.page.entries.filter((entry) => !known.has(entry.path))];
      return { ...state, folders: { ...state.folders, [action.path]: {
        entries, loading: false, ...(action.page.cursor ? { cursor: action.page.cursor } : {}) } } };
    }
    case "failed":
      return { ...state, folders: { ...state.folders, [action.path]: { entries: [], loading: false,
        error: reasonText(action.reason) } } };
    case "toggle": {
      const expanded = new Set(state.expanded);
      if (expanded.has(action.path)) expanded.delete(action.path);
      else expanded.add(action.path);
      return { ...state, expanded };
    }
    case "collapseAll":
      return { ...state, expanded: new Set([""]) };
    case "reset":
      return EMPTY_TREE;
  }
}

/** One visible row of the tree, in order: what the tree draws. */
export type Row =
  | { readonly kind: "entry"; readonly entry: Entry; readonly depth: number; readonly expanded: boolean }
  | { readonly kind: "more"; readonly path: string; readonly depth: number; readonly shown: number }
  | { readonly kind: "loading"; readonly path: string; readonly depth: number }
  | { readonly kind: "error"; readonly path: string; readonly depth: number; readonly text: string };

export function visibleRows(state: TreeState, path = "", depth = 0): Row[] {
  const folder = state.folders[path];
  if (!folder) return depth === 0 ? [] : [{ kind: "loading", path, depth }];
  const rows: Row[] = [];
  if (folder.error) rows.push({ kind: "error", path, depth, text: folder.error });
  for (const entry of folder.entries) {
    const open = entry.kind === "directory" && !entry.refused && state.expanded.has(entry.path);
    rows.push({ kind: "entry", entry, depth, expanded: open });
    if (open) rows.push(...visibleRows(state, entry.path, depth + 1));
  }
  if (folder.loading) rows.push({ kind: "loading", path, depth });
  else if (folder.cursor) rows.push({ kind: "more", path, depth, shown: folder.entries.length });
  return rows;
}

/** The language a file is coloured as, from its name. */
export function languageOf(path: string): "typescript" | "javascript" | "css" | "markdown" | "yaml"
  | "shell" | "json" | "python" | "text" {
  const name = path.split("/").pop()?.toLowerCase() ?? "";
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1) : "";
  switch (ext) {
    case "ts": case "tsx": case "mts": case "cts": return "typescript";
    case "js": case "jsx": case "mjs": case "cjs": return "javascript";
    case "css": return "css";
    case "md": case "markdown": return "markdown";
    case "yml": case "yaml": return "yaml";
    case "sh": case "bash": case "zsh": return "shell";
    case "json": return "json";
    case "py": case "pyi": return "python";
    default: return "text";
  }
}

export const LANGUAGE_NAMES: Readonly<Record<ReturnType<typeof languageOf>, string>> = {
  typescript: "TypeScript", javascript: "JavaScript", css: "CSS", markdown: "Markdown", yaml: "YAML",
  shell: "Shell", json: "JSON", python: "Python", text: "Plain text",
};

export const EOL_NAMES: Readonly<Record<string, string>> = {
  lf: "LF", crlf: "CRLF", cr: "CR", mixed: "Mixed line endings", none: "No line ending",
};
