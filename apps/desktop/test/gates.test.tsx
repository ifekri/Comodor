/**
 * T038: every command that reaches the Core keeps D1's gates, whichever way
 * it is run — its button, its shortcut or the palette — and the forms of
 * one action are one command (FR-010, FR-029).
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { commands } from "../src/commands.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { byText, click, render, type Rendered, typeInto, until } from "./render.ts";
import { key, openPalette, optionIds } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const CORE_BOUND = ["conversation.send", "conversation.cancel", "mode.act", "mode.plan", "mode.ask", "mode.next",
                    "mode.previous"];

/** Record every command the registry runs, by id. */
function recordRuns(): { ran: string[]; restore: () => void } {
  const ran: string[] = [];
  const original = commands.run.bind(commands);
  commands.run = async (id, context) => {
    ran.push(id);
    return original(id, context);
  };
  return { ran, restore: () => { commands.run = original; } };
}

describe("while D1's gate holds (the wake check)", () => {
  test("no Core-bound command is listed, and its shortcut and buttons send nothing", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    const composer = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(composer, "held back");
    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => container.querySelector('[data-testid="status-strip"][data-state="checking"]'), "checking");

    await key("M", { ctrlKey: true, shiftKey: true }, document.body);
    await key("Enter", {}, composer);
    for (const button of container.querySelectorAll<HTMLButtonElement>('[data-testid="mode"] button')) {
      expect(button.disabled).toBe(true);
    }
    expect((byText(container, '[data-testid="composer"] button', "Send") as HTMLButtonElement).disabled).toBe(true);

    await openPalette(container);
    for (const id of CORE_BOUND) expect(optionIds(container)).not.toContain(id);
    expect(native.core.requests("session.set_mode").length).toBe(0);
    expect(native.core.requests("session.send").length).toBe(0);
  });
});

describe("when the Core is ready", () => {
  test("the mode shortcut runs the same command as the mode buttons", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    const runs = recordRuns();
    try {
      await key("M", { ctrlKey: true, shiftKey: true }, document.body);
      await until(() => native.core.requests("session.set_mode").length === 1, "the mode request");
      expect(native.core.requests("session.set_mode")[0]!.params["mode"]).toBe("plan");
      expect(runs.ran).toContain("mode.next");
      runs.ran.length = 0;
      await click(byText(container, '[data-testid="mode"] button', "ASK")!);
      expect(runs.ran).toEqual(["mode.ask"]);
    } finally {
      runs.restore();
    }
  });
});

describe("D1's buttons are the shell's commands", () => {
  test("Try again and Choose workspace… in a failure", async () => {
    const native = new FakeNative(status({ state: "failed", core: null,
                                            failure: { class: "crashed", message: "it stopped" } }));
    const view = await show(native);
    const failure = await until(() => view.container.querySelector<HTMLElement>('[data-testid="failure-view"]'),
                                "the failure view");
    const runs = recordRuns();
    try {
      await click(byText(failure, "button", "Try again")!);
      await click(byText(failure, "button", "Choose workspace…")!);
    } finally {
      runs.restore();
    }
    expect(runs.ran).toEqual(["core.retry", "workspace.change"]);
    expect(native.commands("retry").length).toBe(1);
    expect(native.commands("choose_workspace").length).toBe(1);
  });

  test("Change workspace… in the status bar, and Check again when unconfigured", async () => {
    const native = new FakeNative();
    native.core.model = { provider: "fake", model: "fake-1", configured: false };
    const view = await show(native);
    const notice = await until(() => view.container.querySelector<HTMLElement>('[data-testid="setup-notice"]'),
                               "the setup notice");
    const runs = recordRuns();
    try {
      await click(byText(view.container, "footer.status-bar button", "Change workspace…")!);
      await click(byText(notice, "button", "Check again")!);
    } finally {
      runs.restore();
    }
    expect(runs.ran).toEqual(["workspace.change", "core.check_again"]);
    expect(native.commands("choose_workspace").length).toBe(1);
    expect(native.commands("check_again").length).toBe(1);
  });

  test("Quit now while closing, and Choose workspace… with no workspace", async () => {
    const closing = new FakeNative(status({ state: "stopping", closing: { seconds_remaining: 7 } }));
    let view = await show(closing);
    await until(() => view.container.querySelector('[data-testid="closing"]'), "closing");
    let runs = recordRuns();
    try {
      await click(byText(view.container, "button", "Quit now")!);
    } finally {
      runs.restore();
    }
    expect(runs.ran).toEqual(["app.quit_now"]);
    expect(closing.commands("quit_now").length).toBe(1);
    await rendered!.unmount();

    const absent = new FakeNative(status({ state: "absent", workspace: null, workspace_id: null, core: null,
                                           notice: "No workspace was chosen." }));
    view = await show(absent);
    await until(() => view.container.querySelector('[data-testid="workspace-gate"]'), "the gate");
    runs = recordRuns();
    try {
      await click(byText(view.container, '[data-testid="workspace-gate"] button', "Choose workspace…")!);
    } finally {
      runs.restore();
    }
    expect(runs.ran).toEqual(["workspace.change"]);
    expect(absent.commands("choose_workspace").length).toBe(1);
  });
});
