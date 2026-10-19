/**
 * T048: the keyboard shortcuts reference (US3 scenario 4): every binding of
 * the registry, read from the registry, with its command and the platform's
 * modifier name — and every listed shortcut runs its command.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { commands } from "../src/commands.ts";
import { displayKey } from "../src/shell/keys.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { render, type Rendered, until } from "./render.ts";
import { key, panelOf, showSurface } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

async function reference(): Promise<HTMLElement> {
  const { container } = await openWindow(show, until);
  await showSurface(container, "Keyboard shortcuts");
  return await until(() => panelOf(container, "Keyboard shortcuts"), "the reference");
}

describe("the reference", () => {
  test("lists every binding of the registry with its command, in the platform's names", async () => {
    const panel = await reference();
    const rows = [...panel.querySelectorAll<HTMLElement>("[data-binding]")];
    const listed = rows.map((row) => row.getAttribute("data-binding"));
    const bound = commands.allBindings().map((binding) => `${binding.key} ${binding.command}`);
    expect(listed).toEqual(bound);
    for (const binding of commands.allBindings()) {
      const row = rows.find((element) => element.getAttribute("data-binding") === `${binding.key} ${binding.command}`)!;
      expect(row.querySelector("kbd")!.textContent).toBe(displayKey(binding.key, "other"));
      expect(row.textContent).toContain(commands.get(binding.command)!.title);
    }
    expect(panel.textContent).toContain("Ctrl+K");
    expect(panel.textContent).not.toContain("Cmd");
  });

  test("lists no key of the withdrawn panel edge (FR-025)", async () => {
    const panel = await reference();
    expect(panel.textContent).not.toMatch(/widen|narrow|panel edge/i);
    expect([...panel.querySelectorAll("th")].map((cell) => cell.textContent)).toEqual(["Command", "Keys"]);
  });
});

describe("every listed shortcut runs its command", () => {
  test("by its key", async () => {
    const { container } = await openWindow(show, until);
    const ran: string[] = [];
    const original = commands.run.bind(commands);
    commands.run = async (id, context) => {
      ran.push(id);
      return original(id, context);
    };
    try {
      for (const binding of commands.allBindings()) {
        // Enter and Escape act in their own places (the composer, the
        // palette, a covering panel); the focus tests prove them.
        if (binding.key === "enter" || binding.key === "escape") continue;
        ran.length = 0;
        document.body.focus();
        const parts = binding.key.split("+");
        const name = parts.at(-1)!;
        await key(name.length === 1 ? name : name.toUpperCase(), {
          ctrlKey: parts.includes("mod"), shiftKey: parts.includes("shift"), altKey: parts.includes("alt"),
        }, document.body);
        expect([binding.key, ran]).toEqual([binding.key, [binding.command]]);
        // Close anything the shortcut opened, so the next one starts the same way.
        const dialog = container.querySelector('[role="dialog"]');
        if (dialog) await key("Escape", {}, dialog.querySelector("input"));
      }
    } finally {
      commands.run = original;
    }
  });
});
