/**
 * T027, corrected 2026-10-17: a later phase appears only as an unavailable
 * control that says so and runs nothing, and no application-level operation
 * beyond D2's is offered (FR-005, FR-031, SC-012).
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

/**
 * The working controls whose words name a later phase, and why each is
 * truthful: they switch what is shown, and what they show is the Core's
 * report or a statement that the feature arrives later.
 */
const NAMED_BUT_REAL: Readonly<Record<string, string>> = {
  EXPLORER: "the tab shows only that browsing arrives later, and the workspace path",
  "AGENTS0/0": "folds the section of the delegates the Core reported",
  "TASKS0/0": "folds the section of the task list the Core reported",
};

describe("the window's controls and the registry", () => {
  test("a control naming a later phase is unavailable and says so, unless it only shows the Core's report", async () => {
    const { container } = await openWindow(show, until);
    const outsideMain = [...container.querySelectorAll<HTMLButtonElement>("button")]
      .filter((button) => button.closest("main") === null || button.closest(".composer-actions") !== null);
    expect(outsideMain.length).toBeGreaterThan(20);
    for (const button of outsideMain) {
      const words = `${button.getAttribute("aria-label") ?? ""} ${button.title} ${button.textContent}`;
      const later = button.classList.contains("later");
      if (later) {
        expect(button.getAttribute("aria-disabled")).toBe("true");
        expect(button.title).toBe(`${button.getAttribute("data-later")} arrives in a later version.`);
      } else if (button.hasAttribute("data-menu")) {
        // A menu's trigger only opens it; shell.test holds every item real or unavailable.
        expect(button.getAttribute("aria-haspopup")).toBe("menu");
      } else if (LATER.test(words)) {
        expect([words.trim(), NAMED_BUT_REAL[(button.textContent ?? "").trim()] !== undefined])
          .toEqual([words.trim(), true]);
      }
      if (!later) expect([words.trim(), words.match(NOT_ADDED)?.[0] ?? null]).toEqual([words.trim(), null]);
    }
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
