/**
 * T072: closing (OD-2, FR-017, SC-016). While the Core stops the window says
 * "Closing…" with the seconds left and offers "Quit now"; a forced stop is
 * reported as exactly that, never as anything having been saved.
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

const FORCED = "Comodor was stopped before it finished; work it had not saved may be lost.";

function claimsSaved(text: string): boolean {
  return text.replaceAll("had not saved", "").includes("saved");
}

describe("closing", () => {
  test('"Closing…" shows the seconds left, and "Quit now" calls quit_now', async () => {
    const native = new FakeNative(status({ state: "stopping", closing: { seconds_remaining: 7 } }));
    rendered = await render(<App api={native.api} />);
    const view = await until(() => rendered!.container.querySelector<HTMLElement>('[data-testid="closing"]'),
                             "the closing view");
    expect(view.textContent).toContain("Closing…");
    expect(view.textContent).toContain("7");
    await click(byText(view, "button", "Quit now")!);
    expect(native.commands("quit_now").length).toBe(1);
    expect(native.commands("send_line")).toEqual([]);
  });

  test("a forced stop says work may be lost, and claims nothing was saved", async () => {
    const native = new FakeNative(status({ state: "starting", core: null, stop_outcome: "forced" }));
    rendered = await render(<App api={native.api} />);
    const notice = await until(() => byText(rendered!.container, '[data-testid="stop-outcome"]', "stopped before"),
                               "the forced-stop notice");
    expect(notice.textContent).toBe(FORCED);
    expect(claimsSaved(rendered.text())).toBe(false);
  });

  test("an orderly stop says nothing about being stopped early", async () => {
    const native = new FakeNative(status({ state: "starting", core: null, stop_outcome: "orderly" }));
    rendered = await render(<App api={native.api} />);
    await until(() => rendered!.container.querySelector('[data-testid="status-strip"]'), "the strip");
    expect(rendered.container.querySelector('[data-testid="stop-outcome"]')).toBeNull();
    expect(claimsSaved(rendered.text())).toBe(false);
  });
});
