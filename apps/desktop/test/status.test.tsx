/**
 * T026: the status strip, the failure views and the workspace gate
 * (FR-020, SC-002), against the in-memory native side and Core.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeNative, status } from "./fake-native.ts";
import { byText, click, render, type Rendered, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const CLASSES = [
  "not_found", "spawn_failed", "workspace_unavailable", "exited_before_ready",
  "protocol_mismatch", "protocol_fault", "crashed",
] as const;

describe("the ready strip", () => {
  test("shows the workspace, provider, model and configured state as reported", async () => {
    const native = new FakeNative(status({ workspace: "/work/دفتر project" }));
    native.core.session = { ...native.core.session, workspace: "/work/دفتر project" };
    native.core.model = { provider: "fake", model: "fake-1", configured: true };
    const view = await show(native);
    const strip = await until(() =>
      view.container.querySelector<HTMLElement>('[data-testid="status-strip"][data-state="ready"]'),
      "the ready strip");
    await until(() => strip.textContent?.includes("fake-1"), "the model");
    const text = strip.textContent ?? "";
    expect(text).toContain("/work/دفتر project");
    expect(text).toContain("fake");
    expect(text).toContain("fake-1");
    expect(text).toContain("Configured");
    expect(native.core.requests("model.get").length).toBe(1);
  });

  /** Review finding (PR #62): the workspace shown is the one the Core
   * reports (FR-020) — its project root, not the folder it was started in. */
  test("shows the workspace the Core reports, not the folder it was started in", async () => {
    const native = new FakeNative(status({ workspace: "/repo/src" }));
    native.core.session = { ...native.core.session, workspace: "/repo" };
    const view = await show(native);
    const strip = await until(() =>
      view.container.querySelector<HTMLElement>('[data-testid="status-strip"][data-state="ready"]'),
      "the ready strip");
    await until(() => strip.querySelector(".status-workspace")?.textContent === "/repo", "the Core's workspace");
    expect(native.core.requests("workspace.get").length).toBe(1);
  });

  /** Review finding (PR #62): Send waits until the Core says it is
   * configured, not merely until it has not said otherwise. */
  test("Send stays unavailable until the Core reports the provider configured", async () => {
    const native = new FakeNative();
    native.core.handlers.set("model.get", () => ({ hold: true }));
    const view = await show(native);
    const send = await until(() => byText(view.container, '[data-testid="composer"] button', "Send"), "Send");
    await until(() => native.core.requests("model.get").length === 1, "the model asked");
    expect((send as HTMLButtonElement).disabled).toBe(true);
    native.core.respond(native.core.requests("model.get")[0]!.id,
                        { provider: "fake", model: "fake-1", configured: true });
    await until(() => !(byText(view.container, '[data-testid="composer"] button', "Send") as HTMLButtonElement).disabled,
                "Send available");
  });

  test("an unconfigured provider is shown as not configured", async () => {
    const native = new FakeNative();
    native.core.model = { provider: "", model: "", configured: false };
    const view = await show(native);
    await until(() => view.text().includes("Not configured"), "not configured");
  });

  test("while starting it says so, and asks the Core nothing", async () => {
    const native = new FakeNative(status({ state: "handshaking", core: null }));
    const view = await show(native);
    await until(() => view.container.querySelector('[data-state="handshaking"]'), "starting");
    expect(view.text()).toContain("Starting");
    expect(native.commands("send_line")).toEqual([]);
  });
});

describe("the failure views", () => {
  test("each class has its own message, with the tail as inert text", async () => {
    const titles = new Set<string>();
    for (const failureClass of CLASSES) {
      const native = new FakeNative(status({
        state: "failed", core: null,
        failure: { class: failureClass, message: `native says ${failureClass}` },
      }));
      native.diagnostics = "Traceback\n<b>bold</b><script>alert(1)</script>";
      const view = await show(native);
      const failure = await until(() =>
        view.container.querySelector<HTMLElement>(`[data-testid="failure-view"][data-class="${failureClass}"]`),
        failureClass);
      await until(() => failure.textContent?.includes("Traceback"), "the tail");
      titles.add(failure.querySelector("h1")?.textContent ?? "");
      expect(failure.textContent).toContain(`native says ${failureClass}`);
      expect(failure.textContent).toContain("<b>bold</b>");
      expect(failure.querySelector("b")).toBeNull();
      expect(failure.querySelector("script")).toBeNull();
      await rendered?.unmount();
      rendered = undefined;
    }
    expect(titles.size).toBe(CLASSES.length);
  });

  /** Review finding (PR #62): text from the native side was never shown
   * through the relay, so it carries no link to open. */
  test("a link in the failure or its diagnostics is shown as text, not offered", async () => {
    const native = new FakeNative(status({
      state: "failed", core: null,
      failure: { class: "crashed", message: "see https://example.com/why" },
    }));
    native.diagnostics = "Traceback: details at https://example.com/trace";
    const view = await show(native);
    const failure = await until(() => view.container.querySelector<HTMLElement>('[data-testid="failure-view"]'),
                                "the failure view");
    await until(() => failure.textContent?.includes("Traceback: details at https://example.com/trace"), "the tail");
    expect(failure.textContent).toContain("https://example.com/why");
    expect(failure.querySelector("button.link")).toBeNull();
  });

  /** Review finding (PR #62): whatever failed, the workspace can be changed. */
  test('every failure offers "Choose workspace…"', async () => {
    for (const failureClass of CLASSES) {
      const native = new FakeNative(status({
        state: "failed", core: null, failure: { class: failureClass, message: failureClass },
      }));
      const view = await show(native);
      const button = await until(() => byText(view.container, "button", "Choose workspace…"), failureClass);
      await click(button);
      expect(native.commands("choose_workspace").length).toBe(1);
      await rendered?.unmount();
      rendered = undefined;
    }
  });

  /** Review finding (PR #62): the tail is fetched again when the native
   * side reports again, once the faulted Core's last output is in. */
  test("the diagnostics are fetched again when the failure is reported again", async () => {
    const failed = status({ state: "failed", core: null,
                            failure: { class: "protocol_fault", message: "not protocol" } });
    const native = new FakeNative(failed);
    native.diagnostics = "first line";
    const view = await show(native);
    await until(() => view.text().includes("first line"), "the first tail");
    native.diagnostics = "first line\nlast line";
    native.push({ ...failed });
    await until(() => view.text().includes("last line"), "the complete tail");
  });

  test('"Try again" calls retry', async () => {
    const native = new FakeNative(status({
      state: "failed", core: null,
      failure: { class: "exited_before_ready", message: "it exited" },
    }));
    const view = await show(native);
    const button = await until(() => byText(view.container, "button", "Try again"), "Try again");
    await click(button);
    expect(native.commands("retry").length).toBe(1);
  });
});

describe("the workspace gate", () => {
  test('"no workspace chosen" offers "Choose workspace…", which calls choose_workspace', async () => {
    const native = new FakeNative(status({
      state: "absent", workspace: null, core: null, notice: "No workspace chosen.",
    }));
    const view = await show(native);
    await until(() => view.text().includes("No workspace chosen."), "the notice");
    const button = await until(() => byText(view.container, "button", "Choose workspace…"), "the button");
    await click(button);
    expect(native.commands("choose_workspace").length).toBe(1);
    expect(native.commands("send_line")).toEqual([]);
  });
});

/** Review finding (PR #62): the workspace can be changed later (FR-021). */
describe("changing the workspace later", () => {
  test('the ready view offers "Change workspace…", which calls choose_workspace', async () => {
    const native = new FakeNative(status({ workspace: "/work/one" }));
    native.chosen = "/work/two";
    const view = await show(native);
    await until(() => view.container.querySelector('[data-testid="status-strip"][data-state="ready"]'),
                "the ready strip");
    const button = await until(() => byText(view.container, "button", "Change workspace…"), "the button");
    await click(button);
    expect(native.commands("choose_workspace").length).toBe(1);
  });

  test("so does a Core that is still starting", async () => {
    const native = new FakeNative(status({ state: "handshaking", core: null }));
    const view = await show(native);
    await until(() => view.container.querySelector('[data-state="handshaking"]'), "starting");
    await click(await until(() => byText(view.container, "button", "Change workspace…"), "the button"));
    expect(native.commands("choose_workspace").length).toBe(1);
  });

  test("not while closing: a stop is already under way", async () => {
    const native = new FakeNative(status({ state: "stopping", core: null, closing: { seconds_remaining: 9 } }));
    const view = await show(native);
    await until(() => view.text().includes("Quit now"), "closing");
    expect(byText(view.container, "button", "Change workspace…")).toBeNull();
  });
});
