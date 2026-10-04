/**
 * T062: the window after its Core restarts (FR-011, FR-016, R12). The page
 * reconnects with a new client and reopens the stored conversation; what the
 * Core never completed is shown as interrupted and is never sent again.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeCore } from "./fake-core.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { byText, click, press, render, type Rendered, typeInto, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function open(native = new FakeNative()) {
  return openWindow(async (n) => {
    rendered = await render(<App api={n.api} />);
    return rendered;
  }, until, native);
}

describe("after a restart", () => {
  test("the page reconnects with a new client and reopens the stored conversation", async () => {
    const { native, container } = await open();
    const first = native.core;
    const next = new FakeCore();
    native.restart(next);
    await until(() => next.requests("session.open").length === 1, "the reopen");
    expect(next.requests("session.open")[0]!.params).toEqual({ session_id: "s1" });
    expect(next.requests("client.hello").length).toBe(1);
    expect(next.requests("session.create")).toEqual([]);
    expect(native.commands("connect").length).toBe(2);
    await until(() => container.querySelector('[data-testid="composer"]'), "the composer again");
    expect(first.requests("session.open")).toEqual([]);
  });

  test("when nothing was stored, a new conversation starts and the window says so", async () => {
    const { native, container } = await open();
    const next = new FakeCore();
    next.handlers.set("session.open", () => ({
      error: { code: "not_allowed", message: "no stored session named 's1'" } }));
    native.restart(next);
    await until(() => next.requests("session.create").length === 1, "a new conversation");
    await until(() => byText(container, '[data-testid="recovery"]', "could not be reopened"), "the notice");
  });

  test("an accepted turn the Core never finished is shown as interrupted, and never sent again", async () => {
    const { native, container } = await open();
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "start something");
    await press(field, "Enter");
    await until(() => native.core.requests("session.send").length === 1, "the send");
    native.core.emit("message.started", { session_id: "s1", turn_id: "t1", message_id: "m1", role: "assistant" });
    native.core.emit("message.delta", { session_id: "s1", turn_id: "t1", message_id: "m1", text: "half an ans" });
    await until(() => byText(container, '[data-testid="line"]', "half an ans"), "the stream");

    const next = new FakeCore();
    native.restart(next);
    await until(() => next.requests("session.open").length === 1, "the reopen");
    const notice = await until(() => byText(container, '[data-testid="recovery"]', "interrupted"), "the notice");
    expect(notice.textContent).toContain("not saved");
    expect(next.requests("session.send")).toEqual([]);
  });

  test("a turn that finished before the restart is not called interrupted", async () => {
    const { native, container } = await open();
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "a short one");
    await press(field, "Enter");
    await until(() => native.core.requests("session.send").length === 1, "the send");
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    native.core.emit("message.started", { session_id: "s1", turn_id: "t1", message_id: "m1", role: "assistant" });
    native.core.emit("message.completed", { session_id: "s1", turn_id: "t1", message_id: "m1",
                                            text: "done", status: "completed" });
    native.core.emit("session.updated", { session: { ...native.core.session, busy: false } });
    await until(() => byText(container, '[data-testid="line"]', "done"), "the answer");
    const next = new FakeCore();
    native.restart(next);
    await until(() => next.requests("session.open").length === 1, "the reopen");
    await until(() => container.querySelector('[data-testid="composer"]'), "the composer");
    expect(byText(container, '[data-testid="recovery"]', "interrupted")).toBeNull();
  });

  test("background delegates are summarised in one line, lost ones included", async () => {
    const native = new FakeNative();
    native.core.snapshot = {
      ...native.core.snapshot,
      delegates: [
        { id: "d1", label: "index the tests", state: "running", steps: 1, tool_calls: 0,
          tokens: 0, elapsed: 3, started_at: 0 },
        { id: "d2", label: "read the docs", state: "lost", steps: 2, tool_calls: 1,
          tokens: 0, elapsed: 9, started_at: 0 },
      ],
    };
    const { container } = await open(native);
    const line = await until(() => container.querySelector<HTMLElement>('[data-testid="delegates"]'), "the summary");
    expect(line.textContent).toContain("2 background tasks");
    expect(line.textContent).toContain("1 running");
    expect(line.textContent).toContain("1 lost");
  });
});

/** A Core whose live session has its own id, as `session.open` gives. */
function coreWith(id: string, workspace = "/work/project"): FakeCore {
  const core = new FakeCore();
  core.session = { ...core.session, id, workspace };
  core.snapshot = { ...core.snapshot, session: core.session };
  return core;
}

/** Review findings (PR #62): which conversation a new Core reopens. */
describe("what the window keeps", () => {
  test("a reload keeps the stored conversation for the next restart", async () => {
    const { native } = await open();
    const second = coreWith("live-2");
    native.restart(second);
    await until(() => second.requests("session.snapshot").length > 0, "the reopened session");
    expect(second.requests("session.open")[0]!.params).toEqual({ session_id: "s1" });

    // The window's content reloads: a new page, the same Core.
    await rendered!.unmount();
    rendered = await render(<App api={native.api} />);
    await until(() => second.requests("session.snapshot").length > 1, "the session after the reload");
    expect(second.requests("session.open").length).toBe(1);
    expect(second.requests("session.create")).toEqual([]);

    const third = coreWith("live-3");
    native.restart(third, 2);
    await until(() => third.requests("session.open").length === 1, "the reopen");
    expect(third.requests("session.open")[0]!.params).toEqual({ session_id: "s1" });
  });

  test("a new workspace starts a new conversation, with nothing called interrupted", async () => {
    const { native, container } = await open();
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "start something");
    await press(field, "Enter");
    await until(() => native.core.requests("session.send").length === 1, "the send");

    const next = coreWith("s2", "/work/other");
    native.replace(next, { ...native.current, state: "stopping" },
                   { ...native.current, state: "ready", workspace: "/work/other", workspace_id: "launch:2" });
    await until(() => next.requests("session.create").length === 1, "a new conversation");
    expect(next.requests("session.open")).toEqual([]);
    await until(() => container.querySelector('[data-testid="composer"]'), "the composer");
    expect(container.querySelector('[data-testid="recovery"]')).toBeNull();
  });
});

describe("telling workspaces apart", () => {
  /** Review finding (PR #62): two folders can display the same (a byte that
   * is not UTF-8); the native side's id tells them apart. */
  test("a folder that only looks the same is still a new conversation", async () => {
    const { native } = await open();
    const next = coreWith("s2");
    native.replace(next, { ...native.current, state: "stopping" },
                   { ...native.current, state: "ready", workspace_id: "launch:2" });
    await until(() => next.requests("session.create").length === 1, "a new conversation");
    expect(next.requests("session.open")).toEqual([]);
  });
});

describe("at the restart limit", () => {
  test("the window shows the count and offers Try again", async () => {
    const native = new FakeNative(status({
      state: "failed", core: null, restart_count: 3,
      failure: { class: "crashed",
                 message: "The Core stopped unexpectedly (exit code 70). It stopped 3 times in a row, so it was not started again." },
    }));
    rendered = await render(<App api={native.api} />);
    const view = await until(() => rendered!.container.querySelector<HTMLElement>('[data-testid="failure-view"]'),
                             "the failure view");
    expect(view.textContent).toContain("3 of 3");
    await click(byText(view, "button", "Try again")!);
    expect(native.commands("retry").length).toBe(1);
  });
});
