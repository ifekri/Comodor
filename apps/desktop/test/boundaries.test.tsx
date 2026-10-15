/**
 * T027: no entry for a later phase, and no application-level operation
 * beyond D2's (FR-005, FR-031, SC-012).
 *
 * The palette lists `registry.search(query, context)`, a subset of the
 * registry, in every state; scanning every command and binding of the
 * registry therefore covers the palette's results in every state.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { commands } from "../src/commands.ts";
import { FakeNative, openWindow } from "./fake-native.ts";
import { render, type Rendered, until } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

/** D3–D6 and the surfaces no phase of D2 offers. */
const LATER = /\b(editor|edit file|file tree|files?|browse|explorer|terminal|console|agents?|tasks?|delegates?|session panel|sessions|histor(y|ies)|install(er)?|updates?|credentials?|api key|password|token|sign in|log ?in)\b/i;
/** Application-level operations D2 does not add (FR-031). */
const NOT_ADDED = /\b(reload|refresh window|open log|log folder|logs folder)\b/i;

describe("the rail and the registry", () => {
  test("the rail offers nothing of a later phase", async () => {
    const { container } = await openWindow(show, until);
    const rail = container.querySelector<HTMLElement>('nav[aria-label="Workbench"]')!;
    const text = [...rail.querySelectorAll("button")]
      .map((button) => `${button.getAttribute("aria-label")} ${button.title} ${button.textContent}`).join(" ");
    expect(text).not.toMatch(LATER);
    expect(text).not.toMatch(NOT_ADDED);
  });

  test("no command or binding refers to a later phase or an operation D2 does not add", () => {
    for (const command of commands.all()) {
      const words = [command.id.replace(/[._]/g, " "), command.title, command.group ?? "",
                     ...(command.keywords ?? [])].join(" ");
      expect([command.id, words.match(LATER)?.[0] ?? null]).toEqual([command.id, null]);
      expect([command.id, words.match(NOT_ADDED)?.[0] ?? null]).toEqual([command.id, null]);
    }
    for (const binding of commands.allBindings()) {
      expect(commands.get(binding.command)).toBeDefined();
    }
  });

  test("the only quit is D1's Quit now while closing", () => {
    const quits = commands.all().filter((command) => /quit/i.test(`${command.id} ${command.title}`));
    expect(quits.map((command) => command.id)).toEqual(
      commands.get("app.quit_now") ? ["app.quit_now"] : []);
  });
});
