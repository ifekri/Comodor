/**
 * T037: typing at most the first three letters of a word in a command's
 * title puts it among the first three results; Enter runs the highlighted
 * result (SC-003).
 */

import { afterEach, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { commands } from "../src/commands.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { render, type Rendered, typeInto, until } from "./render.ts";
import { highlighted, key, openPalette, palette, paletteInput } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

/** The words of a title a person would type: letters and digits only. */
function words(title: string): string[] {
  return title.split(/[^\p{L}\p{N}]+/u).filter((word) => word.length > 0);
}

test("every command is among the first three for the first three letters of some word in its title", () => {
  const missed: string[] = [];
  for (const command of commands.all()) {
    const found = words(command.title).some((word) =>
      [1, 2, 3].some((length) => {
        const typed = word.slice(0, length);
        return commands.search(typed).slice(0, 3).some((result) => result.id === command.id);
      }));
    if (!found) missed.push(`${command.id} "${command.title}"`);
  }
  expect(missed).toEqual([]);
});

test("Enter runs the highlighted result", async () => {
  const { container } = await openWindow(async (native: FakeNative) => {
    rendered = await render(<App api={native.api} />);
    return rendered;
  }, until);
  await openPalette(container);
  await typeInto(paletteInput(container), "key");
  await until(() => highlighted(container) === "view.shortcuts", "the shortcuts first");
  await key("Enter", {}, paletteInput(container));
  await until(() => palette(container) === null, "closed");
  await until(() => container.querySelector('[role="dialog"][aria-label="Keyboard shortcuts"]'), "the shortcuts reference");
});
