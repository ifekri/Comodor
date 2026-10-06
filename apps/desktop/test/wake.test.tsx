/**
 * After the machine sleeps (spec: Machine sleep and wake): while the native
 * side checks the Core, the window keeps the conversation and sends nothing;
 * once the Core has answered, the session is read again from the Core.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeCore } from "./fake-core.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { byText, press, render, type Rendered, until } from "./render.ts";

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

function send(container: HTMLElement): HTMLButtonElement | null {
  return byText(container, '[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
}

describe("after the machine wakes", () => {
  test("nothing is sent while the Core is checked, then the session is read again", async () => {
    const { native, container } = await open();
    native.core.emit("message.started", { session_id: "s1", turn_id: "t1", message_id: "m1", role: "assistant" });
    native.core.emit("message.completed", { session_id: "s1", turn_id: "t1", message_id: "m1",
                                            text: "before the sleep", status: "completed" });
    await until(() => byText(container, '[data-testid="line"]', "before the sleep"), "the conversation");
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available");

    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => container.querySelector('[data-testid="status-strip"][data-state="checking"]'),
                "the strip says so");
    await until(() => send(container)?.disabled === true, "Send unavailable during the check");
    expect(byText(container, '[data-testid="line"]', "before the sleep")).not.toBeNull();

    // The session moved on while the machine slept.
    native.core.snapshot = {
      session: native.core.session, revision: 9, tools: [],
      messages: [
        { message_id: "m1", turn_id: "t1", role: "assistant", text: "before the sleep", status: "completed" },
        { message_id: "m2", turn_id: "t2", role: "assistant", text: "while it slept", status: "completed" },
      ],
    };
    const asked = native.core.requests("session.snapshot").length;
    native.push(status({ state: "ready", check_epoch: 1 }));
    await until(() => native.core.requests("session.snapshot").length === asked + 1, "the session read again");
    await until(() => byText(container, '[data-testid="line"]', "while it slept"), "what changed meanwhile");
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available again");
  });

  /** Review finding (PR #62): Send stays unavailable from the check until
   * the session has been read again, with no moment in between. */
  test("Send is never available between the check and the session read again", async () => {
    const { native, container } = await open();
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available");
    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => send(container)?.disabled === true, "Send unavailable during the check");
    const button = send(container)!;
    let enabledEarly = false;
    const watcher = new MutationObserver(() => {
      if (!button.disabled) enabledEarly = true;
    });
    watcher.observe(button, { attributes: true, attributeFilter: ["disabled"] });
    native.core.handlers.set("session.snapshot", () => ({ hold: true }));
    const asked = native.core.requests("session.snapshot").length;
    native.push(status({ state: "ready", check_epoch: 1 }));
    await until(() => native.core.requests("session.snapshot").length === asked + 1, "the session read again");
    expect(enabledEarly).toBe(false);
    native.core.respond(native.core.requests("session.snapshot")[asked]!.id, { snapshot: native.core.snapshot });
    await until(() => !send(container)!.disabled, "Send available once the session is read");
    watcher.disconnect();
  });

  /** Review finding (PR #62): Cancel is not offered while the Core is being
   * checked, since nothing can reach it then. */
  test("Cancel is unavailable while the Core is checked", async () => {
    const { native, container } = await open();
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    const cancel = await until(() => byText(container, '[data-testid="composer"] button', "Cancel") as
      HTMLButtonElement | null, "Cancel offered while busy");
    expect(cancel.disabled).toBe(false);
    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => (byText(container, '[data-testid="composer"] button', "Cancel") as HTMLButtonElement).disabled,
                "Cancel unavailable during the check");
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await press(field, "Escape");
    expect(native.core.requests("session.cancel")).toEqual([]);
  });

  /** Review finding (PR #62): a turn that ended while the machine slept is
   * not offered for cancelling before the fresh read says so. */
  test("Cancel stays unavailable until the session is read again", async () => {
    const { native, container } = await open();
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    await until(() => byText(container, '[data-testid="composer"] button', "Cancel"), "Cancel offered while busy");
    native.push(status({ state: "checking", check_epoch: 1 }));
    const cancel = await until(() => {
      const button = byText(container, '[data-testid="composer"] button', "Cancel") as HTMLButtonElement | null;
      return button?.disabled ? button : null;
    }, "Cancel unavailable during the check");
    let enabledEarly = false;
    const watcher = new MutationObserver(() => {
      if (!cancel.disabled) enabledEarly = true;
    });
    watcher.observe(cancel, { attributes: true, attributeFilter: ["disabled"] });
    // The turn ended while the machine slept: the Core's session is idle.
    native.core.snapshot = { ...native.core.snapshot, session: { ...native.core.session, busy: false }, revision: 50 };
    native.core.handlers.set("session.snapshot", () => ({ hold: true }));
    const asked = native.core.requests("session.snapshot").length;
    native.push(status({ state: "ready", check_epoch: 1 }));
    await until(() => native.core.requests("session.snapshot").length === asked + 1, "the session read again");
    expect(enabledEarly).toBe(false);
    native.core.respond(native.core.requests("session.snapshot")[asked]!.id, { snapshot: native.core.snapshot });
    await until(() => byText(container, '[data-testid="composer"] button', "Cancel") === null, "no turn to cancel");
    watcher.disconnect();
    expect(native.core.requests("session.cancel")).toEqual([]);
  });

  /** Review finding (PR #62): a wake while the window is still opening its
   * session does not leave Send unavailable for good. */
  test("a wake while the session is still being opened still ends with Send available", async () => {
    const native = new FakeNative();
    native.core.handlers.set("session.list", () => ({ hold: true }));
    rendered = await render(<App api={native.api} />);
    await until(() => native.core.requests("session.list").length === 1, "the window opening its session");
    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => rendered!.container.querySelector('[data-testid="status-strip"][data-state="checking"]'),
                "the check shown");
    native.core.handlers.delete("session.list");
    native.push(status({ state: "ready", check_epoch: 1 }));
    // The first opening's answer comes late.
    native.core.respond(native.core.requests("session.list")[0]!.id, { sessions: [] });
    const container = rendered.container;
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available");
    expect(native.core.requests("session.create").length).toBe(1);
  });

  /** The same, when the opening tried to send during the check and was
   * refused: it is opened again once the Core has answered. */
  test("an opening refused during the check is tried again once the Core answers", async () => {
    const native = new FakeNative();
    native.core.handlers.set("session.list", () => ({ hold: true }));
    rendered = await render(<App api={native.api} />);
    await until(() => native.core.requests("session.list").length === 1, "the window opening its session");
    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => rendered!.container.querySelector('[data-testid="status-strip"][data-state="checking"]'),
                "the check shown");
    native.core.handlers.delete("session.list");
    // Its next step, session.create, is refused while the Core is checked.
    native.core.respond(native.core.requests("session.list")[0]!.id, { sessions: [] });
    await until(() => native.commands("send_line").some((call) =>
      JSON.parse(String(call.args?.["line"])).method === "session.create"), "the refused create");
    expect(native.core.requests("session.create")).toEqual([]);
    native.push(status({ state: "ready", check_epoch: 1 }));
    const container = rendered.container;
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available");
    expect(native.core.requests("session.create").length).toBe(1);
  });

  /** Review finding (PR #62, P1): a check that begins and ends before the
   * window renders again is still followed by a fresh read, with Send and
   * Cancel unavailable until it has settled. */
  test("a check over before the next render is still followed by a fresh read", async () => {
    const { native, container } = await open();
    native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
    await until(() => byText(container, '[data-testid="composer"] button', "Cancel"), "Cancel offered while busy");
    const sendButton = send(container)!;
    const cancelButton = byText(container, '[data-testid="composer"] button', "Cancel") as HTMLButtonElement;
    let offeredEarly = false;
    const watcher = new MutationObserver(() => {
      if (!sendButton.disabled || !cancelButton.disabled) offeredEarly = true;
    });
    native.core.snapshot = {
      session: { ...native.core.session, busy: false }, revision: 60, tools: [],
      messages: [{ message_id: "m9", turn_id: "t9", role: "assistant", text: "while it slept", status: "completed" }],
    };
    native.core.handlers.set("session.snapshot", () => ({ hold: true }));
    const asked = native.core.requests("session.snapshot").length;
    // Both arrive in the same turn: the window never renders `checking`.
    native.push(status({ state: "checking", check_epoch: 1 }));
    native.push(status({ state: "ready", check_epoch: 1 }));
    watcher.observe(container, { attributes: true, attributeFilter: ["disabled"], subtree: true });
    await until(() => native.core.requests("session.snapshot").length === asked + 1, "the session read again");
    expect(sendButton.disabled).toBe(true);
    expect(cancelButton.disabled).toBe(true);
    expect(offeredEarly).toBe(false);
    native.core.respond(native.core.requests("session.snapshot")[asked]!.id, { snapshot: native.core.snapshot });
    await until(() => byText(container, '[data-testid="line"]', "while it slept"), "what changed meanwhile");
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available once read");
    watcher.disconnect();
    expect(native.core.requests("session.cancel")).toEqual([]);
  });

  test("a Core that ended while the machine slept is reopened as after any crash", async () => {
    const { native, container } = await open();
    native.push(status({ state: "checking", check_epoch: 1 }));
    await until(() => send(container)?.disabled === true, "Send unavailable during the check");
    const next = new FakeCore();
    native.restart(next);
    await until(() => next.requests("session.open").length === 1, "the stored conversation reopened");
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available again");
  });
});
