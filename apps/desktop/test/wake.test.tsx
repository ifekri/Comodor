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

    native.push(status({ state: "checking" }));
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
    native.push(status({ state: "ready" }));
    await until(() => native.core.requests("session.snapshot").length === asked + 1, "the session read again");
    await until(() => byText(container, '[data-testid="line"]', "while it slept"), "what changed meanwhile");
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available again");
  });

  /** Review finding (PR #62): Send stays unavailable from the check until
   * the session has been read again, with no moment in between. */
  test("Send is never available between the check and the session read again", async () => {
    const { native, container } = await open();
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available");
    native.push(status({ state: "checking" }));
    await until(() => send(container)?.disabled === true, "Send unavailable during the check");
    const button = send(container)!;
    let enabledEarly = false;
    const watcher = new MutationObserver(() => {
      if (!button.disabled) enabledEarly = true;
    });
    watcher.observe(button, { attributes: true, attributeFilter: ["disabled"] });
    native.core.handlers.set("session.snapshot", () => ({ hold: true }));
    const asked = native.core.requests("session.snapshot").length;
    native.push(status({ state: "ready" }));
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
    native.push(status({ state: "checking" }));
    await until(() => (byText(container, '[data-testid="composer"] button', "Cancel") as HTMLButtonElement).disabled,
                "Cancel unavailable during the check");
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await press(field, "Escape");
    expect(native.core.requests("session.cancel")).toEqual([]);
  });

  test("a Core that ended while the machine slept is reopened as after any crash", async () => {
    const { native, container } = await open();
    native.push(status({ state: "checking" }));
    await until(() => send(container)?.disabled === true, "Send unavailable during the check");
    const next = new FakeCore();
    native.restart(next);
    await until(() => next.requests("session.open").length === 1, "the stored conversation reopened");
    await until(() => send(container) !== null && !send(container)!.disabled, "Send available again");
  });
});
