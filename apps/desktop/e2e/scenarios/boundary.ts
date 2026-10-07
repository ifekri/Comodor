/**
 * T054 and T055: the window's boundary, in the real WebView against the
 * scripted Core's adversarial scenario.
 *
 * - `canary-early`: the ready window and an adversarial conversation run with
 *   a unique credential in the Core's home; the page then hands back
 *   everything it holds, and the harness searches that and every recorded
 *   message, command, file and log for the credential (SC-009, early part).
 * - `boundary`: a plugin command and an unregistered command are refused,
 *   navigation away and a new window are refused, and the adversarial text
 *   renders inertly (SC-010, SC-011).
 */

import { invoke } from "@tauri-apps/api/core";

import { expect, holdings, pressKey, type Scenario, type ScenarioContext, typeInto, withText } from "../runner.ts";

/** Prompt the adversarial Core, and wait until its whole answer is shown. */
async function adversarial(context: ScenarioContext): Promise<void> {
  await context.waitFor(() => {
    const send = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
    return send !== null && !send.disabled;
  });
  const field = await context.element('[data-testid="composer"] textarea');
  typeInto(field, "Show me what you have.");
  pressKey(field, "Enter");
  await context.waitFor(() => document.querySelector('[data-testid="tool"][data-state="failed"]'));
  await context.waitFor(() => document.querySelectorAll('[data-testid="line"][data-state="completed"]').length >= 2);
}

function inert(): void {
  const window = document.querySelector('[data-testid="window"]')!;
  expect(window.querySelector("script, img, iframe, object, embed") === null, "no markup from the Core");
  expect(window.querySelector('a[href^="javascript"], [onerror]') === null, "no script link or handler");
  expect((globalThis as Record<string, unknown>)["__pwned"] === undefined, "nothing ran");
  expect(document.title === "Comodor", `the title is the window's own: ${document.title}`);
  const text = window.textContent ?? "";
  expect(text.includes("<script>window.__pwned = true</script>"), "the markup shows as text");
  expect(text.includes("␛[2J␛[H"), "escape sequences show as visible symbols");
  expect(!text.includes("\x1b"), "no raw escape character reaches the page text");
  const strips = document.querySelectorAll('[data-testid="status-strip"]');
  expect(strips.length === 1 && strips[0]!.getAttribute("data-state") === "ready", "one strip, still ready");
  expect(document.querySelector(".status-state")?.textContent === "Ready", "the state label is the window's own");
}

export const canaryEarly: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"] .status-model');
  await adversarial(context);
  // Through the bridge, so the recorder sees them: the tail and the status.
  const diagnostics = await invoke<string>("diagnostics");
  const status = await invoke<Record<string, unknown>>("status");
  return { held: await holdings(), diagnostics, status };
};

/**
 * Wait until the native side reports refusing `url` as `kind`. Each check is
 * one round trip to the native side, which is what paces it; there is no
 * timer, and the page deadline ends a refusal that never comes.
 */
async function refusal(context: ScenarioContext, kind: string, url: string): Promise<void> {
  for (;;) {
    const { refused: list } = await context.query("refused");
    if ((list as { kind: string; url: string }[]).some((entry) => entry.kind === kind
        && entry.url.startsWith(url))) return;
  }
}

export const boundary: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  const attempts: Record<string, string> = {};
  for (const [command, args] of [
    ["plugin:opener|open_url", { url: "https://example.com/" }],
    ["plugin:dialog|open", {}],
    ["plugin:fs|read_text_file", { path: "config.json" }],
    ["read_file", { path: "config.json" }],
  ] as const) {
    try {
      await invoke(command, args);
      attempts[command] = "allowed";
    } catch (problem) {
      attempts[command] = String(problem);
    }
  }
  for (const [command, outcome] of Object.entries(attempts)) {
    expect(outcome !== "allowed", `${command} must be refused`);
  }

  const before = window.location.href;
  window.location.href = "https://example.com/away";
  await refusal(context, "navigation", "https://example.com/away");
  const opened = window.open("https://example.org/new", "_blank");
  await refusal(context, "new_window", "https://example.org/new");
  expect(window.location.href === before, `the page stayed: ${window.location.href}`);

  await adversarial(context);
  inert();
  return { attempts, opened: opened === null ? "null" : "a window object" };
};
