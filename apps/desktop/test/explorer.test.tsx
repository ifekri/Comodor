/**
 * D3a: the EXPLORER tab and the canvas's file tabs, over an in-memory Core
 * that offers `workspace_files`. The file viewer itself (CodeMirror) is
 * measured in the real WebView (e2e `explorer`); here, the tree, its pages,
 * its refusals, the tabs and what reaches the Core.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { CanvasTabs } from "../src/explorer/FilePane.tsx";
import { EMPTY_TREE, treeReducer, visibleRows } from "../src/explorer/files.ts";
import { TabsStore } from "../src/explorer/tabs.ts";
import type { FakeCore } from "./fake-core.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";
import { key, resizeTo, WIDE } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
  sessionStorage.clear();
  await resizeTo(WIDE);
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

type Entry = { name: string; path: string; kind: "file" | "directory"; refused?: string };
const file = (path: string, refused?: string): Entry =>
  ({ name: path.split("/").pop()!, path, kind: "file", ...(refused ? { refused } : {}) });
const dir = (path: string): Entry => ({ name: path.split("/").pop()!, path, kind: "directory" });

/** A Core that lists `folders` (one page each unless `pages` says more) and reads `texts`. */
function offerFiles(core: FakeCore, folders: Record<string, Entry[]>, texts: Record<string, string> = {},
                    pages: Record<string, number> = {}): void {
  core.handlers.set("client.hello", () => ({ result: {
    protocol_version: 2, core: { name: "comodor-core", version: "test" },
    capabilities: ["streaming", "questions", "permissions", "modes", "tool_events", "tasks", "delegates", "usage",
                   "workspace_files"],
  } }));
  core.handlers.set("workspace.list", (params) => {
    const path = String(params["path"] ?? "");
    const all = folders[path];
    if (!all) return { error: { code: "invalid_params", message: "missing", data: { reason: "not_found" } } };
    const size = pages[path] ?? all.length;
    const start = params["cursor"] ? Number(params["cursor"]) : 0;
    const entries = all.slice(start, start + size);
    return { result: { path, entries, ...(start + size < all.length ? { cursor: String(start + size) } : {}) } };
  });
  core.handlers.set("workspace.read", (params) => {
    const path = String(params["path"]);
    if (path === ".env") {
      return { error: { code: "not_allowed", message: "refused", data: { reason: "sensitive_name" } } };
    }
    if (path === "logo.png") return { result: { path, size: 2048, unavailable: "binary" } };
    const text = texts[path] ?? "";
    return { result: { path, size: text.length, text, encoding: "utf-8", bom: false, replaced: false, eol: "lf",
                       lines: text.split("\n").length, hash: "h" } };
  });
}

function sidebar(container: HTMLElement): HTMLElement {
  return container.querySelector<HTMLElement>('[data-testid="sidebar"]')!;
}

async function openExplorer(container: HTMLElement): Promise<HTMLElement> {
  await click([...sidebar(container).querySelectorAll<HTMLButtonElement>('[role="tab"]')].at(-1)!);
  return until(() => container.querySelector<HTMLElement>('[role="tree"]'), "the explorer's tree");
}

function rowNames(tree: HTMLElement): string[] {
  return [...tree.querySelectorAll<HTMLElement>('[role="treeitem"][data-path]')].map((row) => row.dataset["path"]!);
}

describe("the explorer", () => {
  test("lists the workspace as the Core reports it, folders first, a refused entry locked", async () => {
    const native = new FakeNative(status({ workspace: "/work/project" }));
    offerFiles(native.core, { "": [dir("src"), file("README.md"), file(".env", "sensitive_name")] });
    const { container } = await openWindow(show, until, native);
    const tree = await openExplorer(container);
    await until(() => rowNames(tree).length === 3, "three rows");
    expect(rowNames(tree)).toEqual(["src", "README.md", ".env"]);
    const locked = tree.querySelector<HTMLElement>('[data-path=".env"]')!;
    expect(locked.getAttribute("aria-disabled")).toBe("true");
    expect(locked.textContent).toContain("may contain secrets");
    expect(native.core.requests("workspace.list")[0]!.params).toEqual({ path: "" });
  });

  test("opens a folder with the keyboard, loading it from the Core only then", async () => {
    const native = new FakeNative();
    offerFiles(native.core, { "": [dir("src"), file("a.txt")], src: [file("src/main.ts")] });
    const { container } = await openWindow(show, until, native);
    const tree = await openExplorer(container);
    await until(() => rowNames(tree).length === 2, "the root");
    expect(native.core.requests("workspace.list").map((r) => r.params["path"])).toEqual([""]);
    const first = tree.querySelector<HTMLElement>('[data-path="src"]')!;
    first.focus();
    await key("ArrowRight", {}, first);
    await until(() => rowNames(tree).includes("src/main.ts"), "src opened");
    expect(rowNames(tree)).toEqual(["src", "src/main.ts", "a.txt"]);
    expect(first.getAttribute("aria-expanded")).toBe("true");
    await key("ArrowLeft", {}, first);
    await until(() => !rowNames(tree).includes("src/main.ts"), "src closed");
  });

  test("a large folder is read a page at a time, and Show more adds the next page once", async () => {
    const native = new FakeNative();
    const many = Array.from({ length: 5 }, (_, at) => file(`f${at}.txt`));
    offerFiles(native.core, { "": many }, {}, { "": 2 });
    const { container } = await openWindow(show, until, native);
    const tree = await openExplorer(container);
    await until(() => rowNames(tree).length === 2, "the first page");
    for (const expected of [4, 5]) {
      await click(await until(() => tree.querySelector<HTMLElement>('[data-testid="explorer-more"]'), "show more"));
      await until(() => rowNames(tree).length === expected, `${expected} rows`);
    }
    expect(tree.querySelector('[data-testid="explorer-more"]')).toBeNull();
    expect(new Set(rowNames(tree)).size).toBe(5);
    expect(native.core.requests("workspace.list").map((r) => r.params["cursor"] ?? "")).toEqual(["", "2", "4"]);
  });

  test("a workspace the Core refuses whole says why and lists nothing", async () => {
    const native = new FakeNative();
    offerFiles(native.core, {});
    native.core.handlers.set("workspace.list", () => ({ error: { code: "not_allowed", message: "refused",
      data: { reason: "workspace_is_comodor_data" } } }));
    const { container } = await openWindow(show, until, native);
    await click([...sidebar(container).querySelectorAll<HTMLButtonElement>('[role="tab"]')].at(-1)!);
    const refused = await until(() => container.querySelector<HTMLElement>('[data-testid="explorer-refused"]'),
      "the refusal");
    expect(refused.textContent).toContain("Comodor's own data folder");
  });
});

describe("the file tabs", () => {
  for (const gesture of ["close mark", "Delete"] as const) {
    for (const [position, paths, closing, next] of [
      ["middle", ["a.ts", "b.ts", "c.ts"], "b.ts", "c.ts"],
      ["last", ["a.ts", "b.ts"], "b.ts", "a.ts"],
      ["only", ["a.ts"], "a.ts", null],
    ] as const) {
      test(`${gesture} on the focused ${position} file tab keeps focus with the selected view`, async () => {
        const tabs = new TabsStore(undefined);
        for (const path of paths) tabs.open(path);
        tabs.show(closing);
        rendered = await render(<CanvasTabs client={null} tabs={tabs} thread={<p>Conversation</p>} />);
        const { container } = rendered;
        const focused = container.querySelector<HTMLElement>(`[role="tab"][data-path="${closing}"]`)!;
        focused.focus();
        if (gesture === "Delete") await key("Delete", {}, focused);
        else await click(focused.querySelector("[data-close]")!);
        expect(tabs.get().active).toBe(next);
        const selected = next === null ? container.querySelector(".canvas-body")
          : container.querySelector('[role="tab"][aria-selected="true"]');
        expect(document.activeElement === selected).toBe(true);
      });
    }
  }

  test("closing a file tab without focus preserves focus on the conversation tab", async () => {
    const tabs = new TabsStore(undefined);
    tabs.open("a.ts");
    tabs.open("b.ts");
    tabs.show(null);
    rendered = await render(<CanvasTabs client={null} tabs={tabs} thread={<p>Conversation</p>} />);
    const { container } = rendered;
    const thread = container.querySelector<HTMLElement>('[role="tab"][data-path=""]')!;
    thread.focus();
    await click(container.querySelector('[data-close="a.ts"]')!);
    expect(tabs.get()).toEqual({ open: ["b.ts"], active: null });
    expect(document.activeElement).toBe(thread);
  });

  test("opening a file shows it in a tab after the thread; closing it shows the thread again", async () => {
    const native = new FakeNative();
    offerFiles(native.core, { "": [file("README.md")] }, { "README.md": "# Hello\n" });
    const { container } = await openWindow(show, until, native);
    const tree = await openExplorer(container);
    await click(await until(() => tree.querySelector<HTMLElement>('[data-path="README.md"]'), "the file"));
    const view = await until(() => container.querySelector<HTMLElement>('[data-testid="file-view"]'), "the file view");
    expect(view.dataset["path"]).toBe("README.md");
    await until(() => view.dataset["state"] === "text", "the text read");
    expect(container.querySelector('[data-testid="file-facts"]')!.textContent).toContain("Read-only");
    const tabs = [...container.querySelectorAll<HTMLElement>('[data-testid="file-tabs"] [role="tab"]')];
    expect(tabs.map((tab) => tab.textContent?.trim())).toEqual(["Thread", "README.md"]);
    expect(container.querySelector<HTMLElement>(".canvas-body")!.hidden).toBe(true);
    expect(native.core.requests("workspace.read").map((r) => r.params)).toEqual([{ path: "README.md" }]);
    const tablist = container.querySelector<HTMLElement>('[data-testid="file-tabs"]')!;
    expect([...tablist.children].every((child) => child.getAttribute("role") === "tab")).toBe(true);
    await click(container.querySelector<HTMLElement>('[data-close="README.md"]')!);
    await until(() => container.querySelector('[data-testid="file-view"]') === null, "the view closed");
    expect(container.querySelector<HTMLElement>(".canvas-body")!.hidden).toBe(false);
  });

  test("a refused or binary file says why and shows no text", async () => {
    const native = new FakeNative();
    offerFiles(native.core, { "": [file("logo.png")] });
    const { container } = await openWindow(show, until, native);
    const tree = await openExplorer(container);
    await click(await until(() => tree.querySelector<HTMLElement>('[data-path="logo.png"]'), "the file"));
    const view = await until(() => container.querySelector<HTMLElement>('[data-testid="file-view"][data-state="unavailable"]'),
      "the binary file");
    expect(view.querySelector('[data-testid="file-notice"]')!.textContent).toContain("binary file");
    expect(view.querySelector<HTMLElement>('[data-testid="file-code"]')!.hidden).toBe(true);
  });

  test("a refused entry in the tree opens nothing", async () => {
    const native = new FakeNative();
    offerFiles(native.core, { "": [file(".env", "sensitive_name")] });
    const { container } = await openWindow(show, until, native);
    const tree = await openExplorer(container);
    await click(await until(() => tree.querySelector<HTMLElement>('[data-path=".env"]'), "the entry"));
    expect(container.querySelector('[data-testid="file-view"]')).toBeNull();
    expect(native.core.requests("workspace.read")).toEqual([]);
  });
});

describe("the tree and tab models", () => {
  test("a repeated page never shows an entry twice", () => {
    let state = treeReducer(EMPTY_TREE, { type: "page", path: "", append: false,
      page: { path: "", entries: [file("a"), file("b")], cursor: "x" } });
    state = treeReducer(state, { type: "page", path: "", append: true,
      page: { path: "", entries: [file("b"), file("c")] } });
    expect(visibleRows(state).map((row) => (row.kind === "entry" ? row.entry.path : row.kind))).toEqual(["a", "b", "c"]);
  });

  test("tabs keep paths only, one tab per file, and closing the shown one shows its neighbour", () => {
    const store = new TabsStore(sessionStorage);
    store.open("a.ts");
    store.open("b.ts");
    store.open("a.ts");
    expect(store.get()).toEqual({ open: ["a.ts", "b.ts"], active: "a.ts" });
    store.close("a.ts");
    expect(store.get()).toEqual({ open: ["b.ts"], active: "b.ts" });
    store.close("b.ts");
    expect(store.get()).toEqual({ open: [], active: null });
    expect(sessionStorage.getItem("comodor.tabs")).toBe(JSON.stringify({ open: [], active: null }));
    store.open("c.ts");
    expect(new TabsStore(sessionStorage).get()).toEqual({ open: ["c.ts"], active: "c.ts" });
  });
});
