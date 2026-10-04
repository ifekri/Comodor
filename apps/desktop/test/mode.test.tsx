/**
 * T042: the mode control (FR-014, FR-024). The Core is the authority: the
 * label changes only when the Core says the mode changed.
 */

import { afterEach, describe, expect, test } from "bun:test";
import { readdirSync, readFileSync } from "node:fs";

import { App } from "../src/app.tsx";
import { FakeNative, openWindow } from "./fake-native.ts";
import { byText, click, render, type Rendered, until } from "./render.ts";

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

function label(container: HTMLElement): string {
  return container.querySelector('[data-testid="mode"] [data-current]')?.textContent ?? "";
}

describe("the mode control", () => {
  test("sends session.set_mode and keeps the old label until mode.changed", async () => {
    const native = new FakeNative();
    native.core.handlers.set("session.set_mode", () => ({ hold: true }));
    const { container } = await open(native);
    await until(() => label(container) === "ACT", "ACT");
    await click(byText(container, '[data-testid="mode"] button', "PLAN")!);
    await until(() => native.core.requests("session.set_mode").length === 1, "the request");
    expect(native.core.requests("session.set_mode")[0]!.params).toEqual({ session_id: "s1", mode: "plan" });
    expect(label(container)).toBe("ACT");
    native.core.emit("mode.changed", { session_id: "s1", mode: "plan" });
    await until(() => label(container) === "PLAN", "PLAN after mode.changed");
  });

  test("a refusal keeps the Core's mode, and says why", async () => {
    const native = new FakeNative();
    native.core.handlers.set("session.set_mode", () => ({ error: { code: "invalid_params", message: "not now" } }));
    const { container } = await open(native);
    await until(() => label(container) === "ACT", "ACT");
    await click(byText(container, '[data-testid="mode"] button', "ASK")!);
    await until(() => container.textContent?.includes("not now"), "the reason");
    expect(label(container)).toBe("ACT");
  });

  test("no view decides whether an action is allowed", () => {
    const folder = new URL("../src/view/", import.meta.url);
    for (const file of readdirSync(folder)) {
      const source = readFileSync(new URL(file, folder), "utf-8");
      expect(source).not.toMatch(/mode\s*===?\s*["'](?:act|plan|ask|chat)["']/);
      expect(source).not.toMatch(/\b(?:allowed|permitted|canWrite|canRun|mayRun)\b/);
    }
  });
});
