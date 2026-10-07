/**
 * T053: outside text is inert (FR-029, SC-010). Messages, tool output, file
 * names, model names and errors render as text: no markup, no script, no
 * navigation, control characters as visible symbols, and nothing that can
 * forge the window's own status.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { segments, visible } from "../src/text.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { byText, click, render, type Rendered, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

const S = "s1";
const HOSTILE = [
  "<script>window.__ran = 1</script>",
  '<img src=x onerror="window.__ran = 2">',
  "javascript:window.__ran=3",
  "\x1b[2J\x1b[H",
  "\x1b]0;forged title\x07",
  "[Connected] [Ready]",
].join(" ");

describe("the inert renderer", () => {
  test("control characters become visible symbols; line breaks and tabs stay", () => {
    expect(visible("a\x1b[2Jb")).toBe("a␛[2Jb");
    expect(visible("\x00\x07\x7f\x9b")).toBe("␀␇␡�");
    expect(visible("one\ntwo\tthree")).toBe("one\ntwo\tthree");
    expect(visible("فارسی and English")).toBe("فارسی and English");
  });

  test("only http and https links are links, by the native side's rule", () => {
    expect(segments("see https://example.com/docs, then javascript:alert(1)")).toEqual([
      { kind: "text", text: "see " },
      { kind: "link", url: "https://example.com/docs" },
      { kind: "text", text: ", then javascript:alert(1)" },
    ]);
    expect(segments("<http://a.example/x>")).toEqual([
      { kind: "text", text: "<" },
      { kind: "link", url: "http://a.example/x" },
      { kind: "text", text: ">" },
    ]);
    expect(segments("https:// alone")).toEqual([{ kind: "text", text: "https:// alone" }]);
  });
});

describe("hostile text in the window", () => {
  test("renders as text everywhere, runs nothing, and forges nothing", async () => {
    const native = new FakeNative();
    native.core.model = { provider: "fake<b>", model: `m\x1b[2J<script>x</script>`, configured: true };
    const title = document.title;
    const { container } = await openWindow(async (n) => {
      rendered = await render(<App api={n.api} />);
      return rendered;
    }, until, native);
    native.core.emit("message.started", { session_id: S, turn_id: "t1", message_id: "m1", role: "assistant" });
    native.core.emit("message.delta", { session_id: S, turn_id: "t1", message_id: "m1", text: HOSTILE });
    native.core.emit("tool.started", { session_id: S, turn_id: "t1", call_id: "c1", name: "read_file",
                                       summary: `missing \x1b[2J [Ready].txt` });
    native.core.emit("tool.output", { session_id: S, turn_id: "t1", call_id: "c1", text: HOSTILE });
    native.core.emit("tool.failed", { session_id: S, turn_id: "t1", call_id: "c1", name: "read_file",
                                      error: HOSTILE });
    native.core.emit("notification.created", { session_id: S, level: "error", text: HOSTILE });
    await until(() => container.querySelector('[data-testid="tool"][data-state="failed"]'), "the failed tool");
    await until(() => byText(container, ".status-model", "␛[2J"), "the model name, made visible");

    expect(container.querySelector("script, img, iframe, object, embed, b")).toBeNull();
    expect(container.querySelector('a[href^="javascript"], [onerror]')).toBeNull();
    expect((window as unknown as Record<string, unknown>)["__ran"]).toBeUndefined();
    expect(document.title).toBe(title);
    const text = container.textContent ?? "";
    expect(text).toContain("<script>window.__ran = 1</script>");
    expect(text).toContain("␛[2J␛[H");
    expect(text).toContain("␛]0;forged title␇");
    expect(text).not.toContain("\x1b");
    // The window's own status is its own: one strip, still "Ready".
    expect(container.querySelectorAll('[data-testid="status-strip"]').length).toBe(1);
    expect(container.querySelector('[data-testid="status-strip"]')!.getAttribute("data-state")).toBe("ready");
    expect(container.querySelector(".status-state")!.textContent).toBe("Ready");
  });

  test("a shown link opens through open_external, and nothing navigates", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(async (n) => {
      rendered = await render(<App api={n.api} />);
      return rendered;
    }, until, native);
    const before = window.location.href;
    native.core.emit("message.started", { session_id: S, turn_id: "t1", message_id: "m1", role: "assistant" });
    native.core.emit("message.delta", { session_id: S, turn_id: "t1", message_id: "m1",
                                        text: "Read https://example.com/guide and javascript:alert(1)" });
    const link = await until(() => byText(container, '[data-testid="line"] .link', "https://example.com/guide"),
                             "the link");
    expect(link.tagName).toBe("BUTTON");
    expect(byText(container, '[data-testid="line"] .link', "javascript")).toBeNull();
    await click(link);
    expect(native.commands("open_external").map((call) => call.args)).toEqual([{ url: "https://example.com/guide" }]);
    expect(window.location.href).toBe(before);
  });
});
