/**
 * A mode change queued when the machine sleeps (review finding, PR #62):
 * nothing queued is sent while the Core is being checked or the session read
 * again, and what is still wanted afterwards is matched against what the
 * Core says — sent once to the same session in the same Core, never replayed
 * into a reopened one, and never dropped without the window saying so.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeCore } from "./fake-core.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { byText, click, render, type Rendered, until } from "./render.ts";

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

/** Every `session.set_mode` the window tried to send, refused ones included. */
function modeAttempts(native: FakeNative): string[] {
  return native.commands("send_line")
    .map((call) => JSON.parse(String(call.args?.["line"])) as { method: string; params: { mode?: string } })
    .filter((request) => request.method === "session.set_mode")
    .map((request) => String(request.params.mode));
}

/** `plan` asked for and held in flight, then `ask` queued behind it. */
async function queueBehindAnInFlightChange(native: FakeNative, container: HTMLElement) {
  native.core.handlers.set("session.set_mode", () => ({ hold: true }));
  const button = (label: string) => byText(container, '[data-testid="mode"] button', label) as HTMLButtonElement;
  await until(() => button("PLAN") && !button("PLAN").disabled, "the modes");
  await click(button("PLAN"));
  await until(() => modeAttempts(native).length === 1, "plan in flight");
  await click(button("ASK"));
  expect(modeAttempts(native)).toEqual(["plan"]);
}

/** The Core confirms `plan`, the change in flight. */
function confirmPlan(native: FakeNative) {
  const asked = native.core.requests("session.set_mode")[0]!;
  native.core.respond(asked.id, { mode: "plan" });
  native.core.emit("mode.changed", { session_id: "s1", mode: "plan" });
}

async function checking(native: FakeNative, container: HTMLElement, epoch: number) {
  native.push(status({ state: "checking", check_epoch: epoch }));
  await until(() => container.querySelector('[data-testid="status-strip"][data-state="checking"]'), "the check");
}

describe("a mode change queued when the machine sleeps", () => {
  test("is not sent during the check or before the session is read, then is sent once", async () => {
    const { native, container } = await open();
    await queueBehindAnInFlightChange(native, container);
    await checking(native, container, 1);
    confirmPlan(native);
    await until(() => container.querySelector('[data-testid="mode"] [data-current]')?.textContent === "PLAN",
                "plan confirmed");
    native.core.snapshot = { ...native.core.snapshot, session: { ...native.core.session, mode: "plan" },
                             revision: 70 };
    native.core.handlers.set("session.snapshot", () => ({ hold: true }));
    const asked = native.core.requests("session.snapshot").length;
    native.push(status({ state: "ready", check_epoch: 1 }));
    await until(() => native.core.requests("session.snapshot").length === asked + 1, "the session read again");
    expect(modeAttempts(native)).toEqual(["plan"]);
    native.core.handlers.delete("session.set_mode");
    native.core.respond(native.core.requests("session.snapshot")[asked]!.id, { snapshot: native.core.snapshot });
    await until(() => modeAttempts(native).length === 2, "the queued change, after the read");
    expect(modeAttempts(native)).toEqual(["plan", "ask"]);
  });

  test("is not sent when the read after the check fails", async () => {
    const { native, container } = await open();
    await queueBehindAnInFlightChange(native, container);
    await checking(native, container, 1);
    confirmPlan(native);
    native.core.handlers.set("session.snapshot", () => ({
      error: { code: "internal", message: "the store could not be read" } }));
    native.push(status({ state: "ready", check_epoch: 1 }));
    await until(() => container.querySelector('[data-testid="session-unread"]'), "the failed read said");
    expect(modeAttempts(native)).toEqual(["plan"]);
  });

  test("waits for the read after the last of several wakes", async () => {
    const { native, container } = await open();
    await queueBehindAnInFlightChange(native, container);
    await checking(native, container, 1);
    confirmPlan(native);
    native.core.snapshot = { ...native.core.snapshot, session: { ...native.core.session, mode: "plan" },
                             revision: 80 };
    native.core.handlers.set("session.snapshot", () => ({ hold: true }));
    const asked = native.core.requests("session.snapshot").length;
    native.push(status({ state: "ready", check_epoch: 1 }));
    await until(() => native.core.requests("session.snapshot").length === asked + 1, "the first read");
    // Asleep again before that read came back.
    await checking(native, container, 2);
    native.core.respond(native.core.requests("session.snapshot")[asked]!.id, { snapshot: native.core.snapshot });
    native.push(status({ state: "ready", check_epoch: 2 }));
    await until(() => native.core.requests("session.snapshot").length === asked + 2, "the second read");
    expect(modeAttempts(native)).toEqual(["plan"]);
    native.core.handlers.delete("session.set_mode");
    native.core.respond(native.core.requests("session.snapshot")[asked + 1]!.id, { snapshot: native.core.snapshot });
    await until(() => modeAttempts(native).length === 2, "the queued change, once");
    expect(modeAttempts(native)).toEqual(["plan", "ask"]);
  });

  /** Review finding (PR #62): the click that is the first to notice a wake
   * is refused by the native side, not by the Core; it is kept and sent once
   * the session has been read again, not lost. */
  test("a choice refused because it was the first to notice the wake is sent after the read", async () => {
    const { native, container } = await open();
    // As `Desktop::send_line` does: the line notices the wake, the Core is
    // then being checked, and the line is refused.
    const invoke = native.api.invoke;
    let noticed = false;
    (native.api as { invoke: typeof invoke }).invoke = async (command, args) => {
      const line = command === "send_line" ? JSON.parse(String(args?.["line"])) as { method: string } : null;
      if (line?.method === "session.set_mode" && !noticed) {
        noticed = true;
        native.push(status({ state: "checking", check_epoch: 1 }));
      }
      return invoke(command, args);
    };
    const button = (label: string) => byText(container, '[data-testid="mode"] button', label) as HTMLButtonElement;
    await until(() => button("PLAN") && !button("PLAN").disabled, "the modes");
    await click(button("PLAN"));
    await until(() => modeAttempts(native).length === 1, "the click that noticed the wake");
    await until(() => container.querySelector('[data-testid="status-strip"][data-state="checking"]'), "the check");
    expect(native.core.requests("session.set_mode")).toEqual([]);
    native.push(status({ state: "ready", check_epoch: 1 }));
    await until(() => native.core.requests("session.set_mode").length === 1, "the choice, after the read");
    expect(native.core.requests("session.set_mode")[0]!.params["mode"]).toBe("plan");
  });

  test("a native side that keeps refusing a choice is not asked again and again", async () => {
    const { native, container } = await open();
    const invoke = native.api.invoke;
    let refused = 0;
    (native.api as { invoke: typeof invoke }).invoke = async (command, args) => {
      const line = command === "send_line" ? JSON.parse(String(args?.["line"])) as { method: string } : null;
      if (line?.method === "session.set_mode") {
        refused += 1;
        throw "the generation is not current";
      }
      return invoke(command, args);
    };
    const button = (label: string) => byText(container, '[data-testid="mode"] button', label) as HTMLButtonElement;
    await until(() => button("PLAN") && !button("PLAN").disabled, "the modes");
    await click(button("PLAN"));
    await until(() => container.querySelector('[data-testid="mode"] .mode-refused'), "the refusal shown");
    expect(refused).toBe(4);
  });

  /** Review finding (PR #62): what a Core puts in its own error cannot make
   * its refusal pass for the native side's. */
  test("a Core's refusal claiming to be the native side's is still the Core's", async () => {
    const { native, container } = await open();
    native.core.handlers.set("session.set_mode", () => ({
      error: { code: "not_allowed", message: "no", data: { refused_by: "native", native_refusal: "guess" } } }));
    const button = (label: string) => byText(container, '[data-testid="mode"] button', label) as HTMLButtonElement;
    await until(() => button("PLAN") && !button("PLAN").disabled, "the modes");
    await click(button("PLAN"));
    await until(() => container.querySelector('[data-testid="mode"] .mode-refused'), "the refusal shown");
    expect(native.core.requests("session.set_mode").length).toBe(1);
  });

  test("is not replayed into a reopened conversation when the Core is restarted, and the window says so",
       async () => {
    const { native, container } = await open();
    await queueBehindAnInFlightChange(native, container);
    await checking(native, container, 1);
    const next = new FakeCore();
    native.restart(next);
    await until(() => next.requests("session.open").length === 1, "the conversation reopened");
    const note = await until(() => byText(container, '[data-testid="recovery"]', "ASK"), "the window says so");
    expect(note.textContent).toContain("not applied");
    await until(() => next.requests("session.snapshot").length > 0, "the reopened session read");
    expect(next.requests("session.set_mode")).toEqual([]);
  });
});
