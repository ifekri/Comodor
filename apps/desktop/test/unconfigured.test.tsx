/**
 * T081: a Core with no configured provider (FR-031, SC-015). The window says
 * how to fix it, cannot send, and "Check again" asks for an orderly restart.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeCore } from "./fake-core.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { byText, click, press, render, type Rendered, typeInto, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function open(native: FakeNative) {
  return openWindow(async (n) => {
    rendered = await render(<App api={n.api} />);
    return rendered;
  }, until, native);
}

function unconfigured(): FakeNative {
  const native = new FakeNative();
  native.core.model = { provider: "", model: "", configured: false };
  return native;
}

describe("an unconfigured provider", () => {
  test("the window directs to `comodor setup` in a terminal", async () => {
    const { container } = await open(unconfigured());
    const notice = await until(() => container.querySelector<HTMLElement>('[data-testid="setup-notice"]'),
                               "the setup notice");
    expect(notice.textContent).toContain("comodor setup");
    expect(notice.textContent).toContain("terminal");
  });

  test("nothing can be sent", async () => {
    const native = unconfigured();
    const { container } = await open(native);
    await until(() => container.querySelector('[data-testid="setup-notice"]'), "the setup notice");
    const send = byText(container, '[data-testid="composer"] button', "Send") as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    const field = container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea')!;
    await typeInto(field, "hello");
    await press(field, "Enter");
    await click(send);
    expect(native.core.requests("session.send")).toEqual([]);
  });

  test('"Check again" calls check_again', async () => {
    const native = unconfigured();
    const { container } = await open(native);
    const notice = await until(() => container.querySelector<HTMLElement>('[data-testid="setup-notice"]'),
                               "the setup notice");
    await click(byText(notice, "button", "Check again")!);
    expect(native.commands("check_again").length).toBe(1);
  });

  test("once the Core says it is configured, sending works", async () => {
    const native = unconfigured();
    const { container } = await open(native);
    await until(() => container.querySelector('[data-testid="setup-notice"]'), "the setup notice");
    const next = new FakeCore();
    next.model = { provider: "fake", model: "fake-1", configured: true };
    native.restart(next, 0);
    await until(() => container.querySelector('[data-testid="setup-notice"]') === null, "the notice to go");
    const field = await until(() => container.querySelector<HTMLTextAreaElement>('[data-testid="composer"] textarea'),
                              "the composer");
    await until(() => !(byText(container, '[data-testid="composer"] button', "Send") as HTMLButtonElement).disabled,
                "Send enabled");
    await typeInto(field, "now it works");
    await press(field, "Enter");
    await until(() => next.requests("session.send").length === 1, "the send");
  });
});
