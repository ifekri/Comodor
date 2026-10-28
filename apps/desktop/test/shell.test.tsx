/**
 * T026, corrected 2026-10-17: the workbench shell in the reference's
 * composition around D1's window (US1; FR-001, FR-003–FR-007, SC-012),
 * against the in-memory native side and Core. Every later-phase element is
 * unavailable and runs nothing; every listed value is the Core's.
 */

import { afterEach, describe, expect, test } from "bun:test";

import type { CoreStatus } from "../src/bridge.ts";
import { App } from "../src/app.tsx";
import { MENUS } from "../src/shell/TopBar.tsx";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";
import { chooseMenuItem, key, menuTrigger, panelOf, paletteControl, resizeTo, showSurface, WIDE } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
  await resizeTo(WIDE);
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const STATES: Record<string, Partial<CoreStatus>> = {
  ready: {},
  starting: { state: "starting", core: null },
  handshaking: { state: "handshaking", core: null },
  checking: { state: "checking", check_epoch: 1 },
  restarting: { state: "restarting", restart_count: 1, core: null },
  failed: { state: "failed", core: null, failure: { class: "crashed", message: "it stopped" } },
  stopping: { state: "stopping", closing: { seconds_remaining: 7 } },
  absent: { state: "absent", workspace: null, workspace_id: null, core: null, notice: null },
};

const sidebar = (container: HTMLElement) => container.querySelector<HTMLElement>('nav[aria-label="Workbench"]');

describe("the reference's regions", () => {
  for (const [name, overrides] of Object.entries(STATES)) {
    test(`are present in the ${name} state`, async () => {
      const view = await show(new FakeNative(status(overrides)));
      await until(() => view.container.querySelector('[data-testid="status-strip"]'), "the status strip");
      const container = view.container;
      expect(container.querySelector("header.top-bar")).not.toBeNull();
      expect(sidebar(container)).not.toBeNull();
      const mains = container.querySelectorAll("main");
      expect(mains.length).toBe(1);
      expect(mains[0]!.getAttribute("data-testid")).toBe("window");
      const bar = container.querySelector<HTMLElement>("footer.status-bar");
      expect(bar).not.toBeNull();
      expect(bar!.querySelector('[role="status"]')).not.toBeNull();
      expect(container.querySelectorAll('[data-testid="status-strip"]').length).toBe(1);
      expect(bar!.querySelector('[data-testid="status-strip"]')).not.toBeNull();
      expect(paletteControl(container)).not.toBeNull();
    });
  }

  test("D1's views sit in D1's main", async () => {
    for (const [name, testid] of [["failed", "failure-view"], ["stopping", "closing"],
                                  ["absent", "workspace-gate"]] as const) {
      const view = await show(new FakeNative(status(STATES[name])));
      const found = await until(() => view.container.querySelector(`[data-testid="${testid}"]`), testid);
      expect(found.closest("main")?.getAttribute("data-testid")).toBe("window");
      await rendered!.unmount();
      rendered = undefined;
    }
    const { container } = await openWindow(show, until);
    for (const testid of ["conversation", "composer", "mode"]) {
      expect(container.querySelector(`[data-testid="${testid}"]`)?.closest("main")?.getAttribute("data-testid"))
        .toBe("window");
    }
  });

  test("the status bar carries the Core's values as the strip did", async () => {
    const native = new FakeNative(status({ workspace: "/repo/src" }));
    native.core.session = { ...native.core.session, workspace: "/repo" };
    native.core.model = { provider: "fake", model: "fake-1", configured: true };
    const view = await show(native);
    const strip = await until(() =>
      view.container.querySelector<HTMLElement>('footer.status-bar [data-testid="status-strip"][data-state="ready"]'),
      "the strip in the status bar");
    await until(() => strip.textContent?.includes("fake-1"), "the model");
    await until(() => strip.querySelector(".status-workspace")?.textContent === "/repo", "the Core's workspace");
    expect(strip.querySelector(".status-state")?.textContent).toBe("Ready");
    expect(strip.textContent).toContain("Configured");
  });

  test("the prompt's footer holds the mode control, Send and the palette, and the model the Core reports", async () => {
    const native = new FakeNative();
    native.core.model = { provider: "fake", model: "fake-1", configured: true };
    const { container } = await openWindow(show, until, native);
    const footer = container.querySelector<HTMLElement>('[data-testid="composer"] .composer-actions')!;
    expect(footer.querySelector('[data-testid="mode"]')).not.toBeNull();
    expect(footer.querySelector('button[data-focus-key="prompt-commands"]')).not.toBeNull();
    await until(() => footer.querySelector('[data-testid="model-chip"]')?.textContent === "fake / fake-1", "the model");
  });
});

describe("names", () => {
  // WCAG 2.5.3: a control's visible text is part of its name; the wordmark is text.
  test("the visible text of the search, the footer links and the wordmark is their name", async () => {
    const { container } = await openWindow(show, until);
    expect(paletteControl(container).getAttribute("aria-label")).toBeNull();
    expect(paletteControl(container).textContent).toContain("Search commands");
    const links = [...container.querySelectorAll<HTMLButtonElement>('[data-testid="composer"] .prompt-link')];
    expect(links.length).toBe(2);
    for (const link of links) {
      expect(link.getAttribute("aria-label")).toBeNull();
      expect(link.querySelector(".prompt-link-label")?.textContent).toBeTruthy();
    }
    const wordmark = container.querySelector("header.top-bar .wordmark")!;
    expect(wordmark.getAttribute("aria-label")).toBeNull();
    expect(wordmark.textContent).toBe("Comodor");
  });
});

describe("the menus", () => {
  test("are the reference's, in its order", async () => {
    const { container } = await openWindow(show, until);
    const labels = [...container.querySelectorAll<HTMLButtonElement>("header.top-bar [data-menu]")]
      .map((button) => button.textContent);
    expect(labels).toEqual(["File", "Model", "Memory", "Skills", "Context", "Agent", "Option", "MCP"]);
  });

  test("every item is a real command or unavailable, and an unavailable one runs nothing", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    for (const menu of MENUS) {
      await click(menuTrigger(container, menu.label));
      const items = await until(() => {
        const found = [...container.querySelectorAll<HTMLButtonElement>(`[data-menu-of="${menu.label}"] [role="menuitem"]`)];
        return found.length > 0 ? found : null;
      }, `the ${menu.label} menu`);
      expect(items.length).toBe(menu.items.length);
      for (const [at, item] of items.entries()) {
        const expected = menu.items[at]!;
        if (expected.command === undefined) {
          expect(item.getAttribute("aria-disabled")).toBe("true");
          expect(item.getAttribute("data-command")).toBeNull();
          expect(item.getAttribute("title")).toContain("arrives in a later version");
        } else {
          expect(item.getAttribute("data-command")).toBe(expected.command);
        }
      }
      await click(menuTrigger(container, menu.label));
    }
    // Every later item, chosen: nothing reaches the native side or the Core.
    const calls = native.calls.length;
    const requests = native.core.sent.length;
    for (const menu of MENUS) {
      for (const item of menu.items.filter((entry) => entry.command === undefined)) {
        await chooseMenuItem(container, menu.label, item.label);
        await until(() => container.querySelector('[data-testid="later-notice"]')?.textContent
          === `${item.label} arrives in a later version.`, `the notice for ${item.label}`);
      }
    }
    expect(native.calls.slice(calls)).toEqual([]);
    expect(native.core.sent.length).toBe(requests);
  });

  test("are a menubar: one tab stop, Left and Right and Home and End between the menus", async () => {
    const { container } = await openWindow(show, until);
    const bar = container.querySelector<HTMLElement>('header.top-bar [role="menubar"]')!;
    expect(bar.getAttribute("aria-label")).toBe("Menu");
    expect(container.querySelector('header.top-bar nav')).toBeNull();
    const triggers = [...bar.querySelectorAll<HTMLButtonElement>("button[data-menu]")];
    expect(triggers.map((trigger) => trigger.getAttribute("role"))).toEqual(Array(8).fill("menuitem"));
    expect(triggers.filter((trigger) => trigger.tabIndex === 0).map((trigger) => trigger.textContent)).toEqual(["File"]);
    triggers[0]!.focus();
    await key("ArrowRight", {}, triggers[0]);
    expect(document.activeElement).toBe(menuTrigger(container, "Model"));
    await key("End", {}, document.activeElement);
    expect(document.activeElement).toBe(menuTrigger(container, "MCP"));
    await key("ArrowRight", {}, document.activeElement);
    expect(document.activeElement).toBe(menuTrigger(container, "File"));
    await key("ArrowLeft", {}, document.activeElement);
    expect(document.activeElement).toBe(menuTrigger(container, "MCP"));
    // The tab stop follows the menu last focused.
    expect(menuTrigger(container, "MCP").tabIndex).toBe(0);
    expect(menuTrigger(container, "File").tabIndex).toBe(-1);
  });

  test("crossing 760 px keeps the focus in the menubar, on the corresponding trigger", async () => {
    const { container } = await openWindow(show, until);
    menuTrigger(container, "Agent").focus();
    await resizeTo(700);
    await until(() => container.querySelector('header.top-bar button[data-menu="Menu"]'), "folded");
    expect(document.activeElement).toBe(menuTrigger(container, "Menu"));
    // An item of the folded menu holding the focus: unfolding goes to its menu.
    await key("ArrowDown", {}, menuTrigger(container, "Menu"));
    const option = await until(() => [...container.querySelectorAll<HTMLElement>('[data-menu-of="Menu"] [role="menuitem"]')]
      .find((item) => item.textContent?.startsWith("Option · ")), "an Option item");
    option.focus();
    await resizeTo(WIDE);
    await until(() => menuTrigger(container, "Option"), "unfolded");
    expect(document.activeElement).toBe(menuTrigger(container, "Option"));
    expect(container.querySelector('[role="menu"]')).toBeNull();
  });

  test("a menu opened with the pointer takes the focus, on its first item", async () => {
    const { container } = await openWindow(show, until);
    await click(menuTrigger(container, "Option"));
    const first = await until(() => container.querySelector<HTMLElement>('[data-menu-of="Option"] [role="menuitem"]'),
      "the Option menu");
    await until(() => document.activeElement === first, "focus on its first item");
    await key("ArrowDown", {}, first);
    expect(document.activeElement?.textContent).toContain("Thread Space");
  });

  test("an open menu raises the top bar above the panel's layer", async () => {
    const { container } = await openWindow(show, until);
    const bar = container.querySelector("header.top-bar")!;
    expect(bar.classList.contains("menu-open")).toBe(false);
    await click(menuTrigger(container, "File"));
    await until(() => container.querySelector('[role="menu"]'), "the File menu");
    expect(bar.classList.contains("menu-open")).toBe(true);
    await click(menuTrigger(container, "File"));
    await until(() => !bar.classList.contains("menu-open"), "lowered again when it closes");
  });

  test("an open menu closes when focus leaves the menubar", async () => {
    const { container } = await openWindow(show, until);
    await click(menuTrigger(container, "File"));
    await until(() => container.querySelector('[role="menu"]'), "the File menu");
    container.querySelector<HTMLButtonElement>('nav[aria-label="Workbench"] button:not(.later)')!.focus();
    await until(() => container.querySelector('[role="menu"]') === null, "closed when focus left");
  });

  test("a real item runs its command: Open Folder changes the workspace", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await chooseMenuItem(container, "File", "Open Folder");
    await until(() => native.commands("choose_workspace").length === 1, "the chooser");
  });
});

describe("every later-phase control", () => {
  test("is marked unavailable, says so, and runs nothing", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    const later = [...container.querySelectorAll<HTMLButtonElement>("button.later")];
    expect(later.length).toBeGreaterThan(10);
    const calls = native.calls.length;
    const requests = native.core.sent.length;
    for (const button of later) {
      expect(button.getAttribute("aria-disabled")).toBe("true");
      const label = button.getAttribute("data-later")!;
      expect(button.getAttribute("title")).toBe(`${label} arrives in a later version.`);
      await click(button);
      await until(() => container.querySelector('[data-testid="later-notice"]')?.textContent
        === `${label} arrives in a later version.`, `the notice for ${label}`);
    }
    expect(native.calls.slice(calls)).toEqual([]);
    expect(native.core.sent.length).toBe(requests);
  });
});

describe("the sidebar", () => {
  test("lists only what the Core reported: the session, its delegates and its tasks", async () => {
    const native = new FakeNative();
    native.core.snapshot = {
      ...native.core.snapshot,
      tasks: [{ text: "Read the settings page", state: "done" }, { text: "Split the form", state: "active" }],
      delegates: [{ id: "d1", label: "search the docs", state: "running", steps: 3, tool_calls: 2, tokens: 10,
                    elapsed: 4, started_at: 1 }],
    };
    const { container } = await openWindow(show, until, native);
    const nav = sidebar(container)!;
    await until(() => nav.querySelectorAll(".task-row").length === 2, "the Core's tasks");
    expect([...nav.querySelectorAll(".task-text")].map((node) => node.textContent))
      .toEqual(["Read the settings page", "Split the form"]);
    expect(nav.querySelector('[data-task-state="done"]')).not.toBeNull();
    expect(nav.querySelectorAll(".agent-card").length).toBe(1);
    expect(nav.querySelector(".agent-task")?.textContent).toBe("Task : search the docs");
    expect(nav.querySelector('section[aria-label="Agents"] .side-count')?.textContent).toBe("1/1");
    expect(nav.querySelector('section[aria-label="Tasks"] .side-count')?.textContent).toBe("1/2");
    expect(nav.querySelectorAll(".side-row").length).toBe(1);
  });

  test("with nothing reported, says so, and invents nothing", async () => {
    const { container } = await openWindow(show, until);
    const nav = sidebar(container)!;
    expect(nav.querySelectorAll(".agent-card, .task-row").length).toBe(0);
    expect(nav.textContent).toContain("No agents in this session.");
    expect(nav.textContent).toContain("No tasks in this session.");
    for (const demo of ["John", "Devid", "Sara", "Mina", "Settings page – Sample app", "Fable", "%36", "ifekri/main"]) {
      expect(container.textContent).not.toContain(demo);
    }
  });

  // D3a changed this D2 test: the explorer is no longer a later-phase
  // placeholder. A Core that does not offer its files (this fake does not)
  // is said to, and nothing pretends to browse.
  test("the explorer tab says when the Core does not offer files, and shows the workspace as reported", async () => {
    const native = new FakeNative(status({ workspace: "/work/project" }));
    const { container } = await openWindow(show, until, native);
    await click([...sidebar(container)!.querySelectorAll<HTMLButtonElement>('[role="tab"]')].at(-1)!);
    const explorer = await until(() => sidebar(container)!.querySelector('[role="tabpanel"][data-tab="explorer"]'),
      "the explorer");
    expect(explorer.textContent).toContain("This Core does not offer the workspace's files.");
    expect(explorer.textContent).toContain("/work/project");
    expect(explorer.querySelector('[role="tree"]')).toBeNull();
    expect(explorer.querySelectorAll("button").length).toBe(0);
  });
});

describe("the sidebar's tabs", () => {
  test("are one tab stop, chosen with Left, Right, Home and End, each naming its panel", async () => {
    const { container } = await openWindow(show, until);
    const tabs = () => [...sidebar(container)!.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
    expect(tabs().map((tab) => tab.tabIndex)).toEqual([0, -1]);
    tabs()[0]!.focus();
    await key("ArrowRight", {}, tabs()[0]);
    await until(() => tabs()[1]!.getAttribute("aria-selected") === "true", "the explorer chosen");
    expect(document.activeElement).toBe(tabs()[1]);
    expect(tabs().map((tab) => tab.tabIndex)).toEqual([-1, 0]);
    const panel = sidebar(container)!.querySelector<HTMLElement>('[role="tabpanel"]')!;
    expect(panel.getAttribute("aria-labelledby")).toBe(tabs()[1]!.id);
    expect(tabs()[1]!.getAttribute("aria-controls")).toBe(panel.id);
    await key("Home", {}, tabs()[1]);
    await until(() => tabs()[0]!.getAttribute("aria-selected") === "true", "the workspace chosen");
    expect(document.activeElement).toBe(tabs()[0]);
    await key("ArrowLeft", {}, tabs()[0]);
    await until(() => tabs()[1]!.getAttribute("aria-selected") === "true", "around to the explorer");
  });
});

describe("choosing a surface", () => {
  test("shows it in the modal panel; choosing the one shown closes it", async () => {
    const { container } = await openWindow(show, until);
    expect(container.querySelector('[role="dialog"].modal-panel')).toBeNull();
    await showSurface(container, "Diagnostics");
    await until(() => panelOf(container, "Diagnostics"), "diagnostics");
    await showSurface(container, "Keyboard shortcuts");
    await until(() => panelOf(container, "Keyboard shortcuts"), "the shortcuts");
    expect(container.querySelectorAll('[role="dialog"].modal-panel').length).toBe(1);
    // A body with nothing focusable in it still scrolls by the keyboard (axe: scrollable-region-focusable).
    const body = panelOf(container, "Keyboard shortcuts")!.querySelector<HTMLElement>(".modal-body")!;
    expect([body.tabIndex, body.getAttribute("role"), body.getAttribute("aria-label")])
      .toEqual([0, "region", "Keyboard shortcuts contents"]);
    await showSurface(container, "Keyboard shortcuts");
    await until(() => container.querySelector('[role="dialog"].modal-panel') === null, "the panel closed");
  });

  test("the conversation is the canvas: choosing it closes the panel and moves focus there", async () => {
    const { container } = await openWindow(show, until);
    await showSurface(container, "Core");
    await until(() => panelOf(container, "Core"), "the Core panel");
    await click(container.querySelector<HTMLButtonElement>(".side-row-open")!);
    await until(() => panelOf(container, "Core") === null, "the panel closed");
    expect(document.activeElement?.closest("main")?.getAttribute("data-testid")).toBe("window");
  });
});
