/**
 * T040: the conversation (FR-012, FR-013), against the in-memory native side
 * and Core. Everything shown is what the Core sent.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { COMMAND_IDS, commands } from "../src/commands.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { byText, click, press, render, type Rendered, typeInto, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function open(native?: FakeNative) {
  return openWindow(async (n) => {
    rendered = await render(<App api={n.api} />);
    return rendered;
  }, until, native);
}

const S = "s1";

describe("the conversation", () => {
  test("deltas render in seq order, and tool output by call_id", async () => {
    const { native, container } = await open();
    native.core.emit("message.started", { session_id: S, turn_id: "t1", message_id: "m1", role: "assistant" });
    native.core.emit("message.delta", { session_id: S, turn_id: "t1", message_id: "m1", text: "Hel" });
    native.core.emit("tool.started", { session_id: S, turn_id: "t1", call_id: "c1", name: "read_file", summary: "a.txt" });
    native.core.emit("tool.started", { session_id: S, turn_id: "t1", call_id: "c2", name: "list_dir", summary: "." });
    native.core.emit("tool.output", { session_id: S, turn_id: "t1", call_id: "c2", text: "second's output" });
    native.core.emit("tool.output", { session_id: S, turn_id: "t1", call_id: "c1", text: "first's output" });
    native.core.emit("message.delta", { session_id: S, turn_id: "t1", message_id: "m1", text: "lo" });
    const message = await until(() => byText(container, '[data-testid="line"]', "Hello"), "the message");
    expect(message.textContent).toContain("Hello");
    const first = await until(() => container.querySelector<HTMLElement>('[data-testid="tool"][data-call="c1"]'), "c1");
    const second = container.querySelector<HTMLElement>('[data-testid="tool"][data-call="c2"]')!;
    expect(first.textContent).toContain("first's output");
    expect(first.textContent).not.toContain("second's output");
    expect(second.textContent).toContain("second's output");
  });

  test("a gap asks for a snapshot, and a duplicate is ignored", async () => {
    const { native, container } = await open();
    native.core.emit("message.started", { session_id: S, turn_id: "t1", message_id: "m1", role: "assistant" }, 1);
    native.core.emit("message.delta", { session_id: S, turn_id: "t1", message_id: "m1", text: "once" }, 2);
    native.core.emit("message.delta", { session_id: S, turn_id: "t1", message_id: "m1", text: "once" }, 2);
    await until(() => byText(container, '[data-testid="line"]', "once"), "the delta");
    expect(byText(container, '[data-testid="line"]', "onceonce")).toBeNull();
    const before = native.core.requests("session.snapshot").length;
    native.core.emit("message.delta", { session_id: S, turn_id: "t1", message_id: "m1", text: "later" }, 7);
    await until(() => native.core.requests("session.snapshot").length > before, "a resync");
  });

  test("send and cancel are single commands, reached by button and keyboard", async () => {
    expect(COMMAND_IDS).toEqual({ send: "conversation.send", cancel: "conversation.cancel" });
    expect(commands.get(COMMAND_IDS.send)).toBeDefined();
    expect(commands.get(COMMAND_IDS.cancel)).toBeDefined();

    const { native, container } = await open();
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "by button");
    await click(byText(container, "button", "Send")!);
    await until(() => native.core.requests("session.send").length === 1, "a send by button");
    expect(native.core.requests("session.send")[0]!.params).toEqual({ session_id: S, text: "by button" });

    await typeInto(field, "by key");
    await press(field, "Enter");
    await until(() => native.core.requests("session.send").length === 2, "a send by key");
    expect(native.core.requests("session.send")[1]!.params["text"]).toBe("by key");

    await typeInto(field, "two\nlines");
    await press(field, "Enter", { shiftKey: true });
    expect(native.core.requests("session.send").length).toBe(2);

    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    const stop = await until(() => byText(container, "button", "Cancel"), "the cancel button");
    await click(stop);
    await until(() => native.core.requests("session.cancel").length === 1, "a cancel by button");
    await press(field, "Escape");
    await until(() => native.core.requests("session.cancel").length === 2, "a cancel by key");
  });

  test("nothing is sent while the session is being read, and the draft waits", async () => {
    const native = new FakeNative();
    let snapshotId = "";
    native.core.handlers.set("session.snapshot", (_params, id) => {
      snapshotId = id;
      return { hold: true };
    });
    const { container } = await open(native);
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "early words");
    await press(field, "Enter");
    expect(native.core.requests("session.send")).toEqual([]);
    expect(field.value).toBe("early words");

    native.core.respond(snapshotId, { snapshot: native.core.snapshot });
    await until(() => !byText(container, "button", "Send")?.hasAttribute("disabled"), "Send enabled");
    await press(field, "Enter");
    await until(() => native.core.requests("session.send").length === 1, "the send");
    await until(() => byText(container, '[data-testid="line"]', "early words"), "the line, kept");
  });

  test("a refused prompt keeps its text", async () => {
    const native = new FakeNative();
    native.core.handlers.set("session.send", () => ({ error: { code: "busy", message: "the session is busy" } }));
    const { container } = await open(native);
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "keep me");
    await press(field, "Enter");
    const line = await until(() => byText(container, '[data-testid="line"]', "keep me"), "the pending line");
    await until(() => line.textContent?.includes("the session is busy"), "the reason");
  });
});
