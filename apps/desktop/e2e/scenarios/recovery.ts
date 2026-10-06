/**
 * T063 and T064: a reload during a held turn, and Core crashes, in the real
 * window (SC-003, SC-004, SC-005, SC-006, SC-017).
 *
 * A reload runs the page again from the start, so a scenario that reloads
 * keeps its place in session storage — the page's own, holding no
 * credential — and carries on from there.
 */

import type { CoreClient } from "@comodor/client";

import { expect, pressKey, type Scenario, type ScenarioContext, typeInto, withText } from "../runner.ts";

const PLACE = "comodor-e2e-place";

function place(): string | null {
  return sessionStorage.getItem(PLACE);
}

async function sendable(context: ScenarioContext): Promise<HTMLTextAreaElement> {
  await context.waitFor(() => {
    const send = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
    return send !== null && !send.disabled;
  });
  return await context.element('[data-testid="composer"] textarea') as HTMLTextAreaElement;
}

async function prompt(context: ScenarioContext, text: string): Promise<void> {
  const field = await sendable(context);
  typeInto(field, text);
  pressKey(field, "Enter");
  await context.waitFor(() => withText('[data-testid="line"]', text));
}

function lines(): { speaker: string; text: string }[] {
  return [...document.querySelectorAll<HTMLElement>('[data-testid="line"]')].map((line) => ({
    speaker: line.querySelector(".speaker")?.textContent ?? "",
    text: line.querySelector(".text")?.textContent ?? "",
  }));
}

function workspace(): string {
  return document.querySelector('[data-testid="status-strip"] .status-workspace')?.textContent ?? "";
}

async function noChooser(context: ScenarioContext): Promise<void> {
  const { starts } = await context.query("chooser");
  expect(Array.isArray(starts) && starts.length === 0, `no chooser appeared: ${JSON.stringify(starts)}`);
}

/** The window equals what the Core's snapshot says, line for line. */
async function equalsTheCore(): Promise<number> {
  const client = (window as unknown as Record<string, unknown>)["__comodorClient"] as CoreClient;
  const sessions = (await client.call("session.list"))["sessions"] as { id: string }[];
  const snapshot = (await client.call("session.snapshot", { session_id: sessions[0]!.id }))["snapshot"] as
    { messages: { role: string; text: string }[] };
  const shown = lines();
  const told = snapshot.messages.map((message) => ({
    speaker: message.role === "user" ? "You" : "Comodor", text: message.text,
  }));
  expect(JSON.stringify(shown) === JSON.stringify(told),
         `the window equals the Core's snapshot:\n${JSON.stringify(shown)}\n${JSON.stringify(told)}`);
  return shown.length;
}

/**
 * Spec: Machine sleep and wake. The machine "wakes" while an answer is held
 * mid-message and then finishes: the native side checks the Core before the
 * page may send again, and the page reads its session again afterwards (the
 * harness checks both, in order, from the run's record). The window ends up
 * equal to the Core's snapshot, and can send again.
 */
export const wake: Scenario = async (context) => {
  await prompt(context, "Tell me something long.");
  await context.waitFor(() => withText('[data-testid="line"][data-state="streaming"]', "The first words"));
  await context.checkpoint("release-and-wake");
  await context.waitFor(() => withText('[data-testid="line"][data-state="completed"]', "the rest of it follows"));
  await context.waitFor(() => document.querySelector('[data-testid="status-strip"][data-state="ready"]'));
  await sendable(context);
  return { lines: await equalsTheCore() };
};

/** T063: reload while the answer is held mid-message. */
export const reload: Scenario = async (context) => {
  if (place() === null) {
    await prompt(context, "Tell me something long.");
    await context.waitFor(() => withText('[data-testid="line"][data-state="streaming"]', "The first words"));
    sessionStorage.setItem(PLACE, JSON.stringify({ workspace: workspace() }));
    location.reload();
    return new Promise(() => {});
  }
  const before = JSON.parse(place()!) as { workspace: string };
  sessionStorage.removeItem(PLACE);
  await sendable(context);
  // The reloaded page rejoined the same live session, still held.
  await context.checkpoint("release-hold");
  await context.waitFor(() => withText('[data-testid="line"][data-state="completed"]', "the rest of it follows"));
  const client = (window as unknown as Record<string, unknown>)["__comodorClient"] as CoreClient;
  const sessions = (await client.call("session.list"))["sessions"] as { id: string }[];
  const snapshot = (await client.call("session.snapshot", { session_id: sessions[0]!.id }))["snapshot"] as
    { messages: { role: string; text: string }[] };
  const shown = lines();
  const told = snapshot.messages.map((message) => ({
    speaker: message.role === "user" ? "You" : "Comodor", text: message.text,
  }));
  expect(JSON.stringify(shown) === JSON.stringify(told),
         `the window equals the Core's snapshot:\n${JSON.stringify(shown)}\n${JSON.stringify(told)}`);
  expect(workspace() === before.workspace, `the workspace is unchanged: ${workspace()}`);
  await noChooser(context);
  return { lines: shown.length };
};

function currentClient(): unknown {
  return (window as unknown as Record<string, unknown>)["__comodorClient"];
}

/** Kill the Core; the page's client at that moment, and when. */
async function killCore(context: ScenarioContext): Promise<{ client: unknown; at: number }> {
  const client = currentClient();
  const { pid } = await context.query("core_pid");
  expect(typeof pid === "number" && pid > 0, `a running Core: ${String(pid)}`);
  await context.checkpoint("kill-core", { pid });
  return { client, at: context.now() };
}

/** The page has a new client on the next Core, and can be written to again. */
async function reconnected(context: ScenarioContext, before: unknown): Promise<void> {
  await context.waitFor(() => currentClient() !== before);
  await sendable(context);
}

function restartsShown(): string {
  return document.querySelector('[data-testid="failure-view"] .failure-count')?.textContent ?? "";
}

/** T064: a kill between turns, a kill during a held turn, then a third crash. */
export const crash: Scenario = async (context) => {
  const first = workspace() || (await context.element(".status-workspace")).textContent || "";

  // Launch 1: a turn completes, then the Core is killed between turns.
  await prompt(context, "remember this line");
  await context.waitFor(() => document.querySelectorAll('[data-testid="line"][data-state="completed"]').length >= 2);
  await context.waitFor(() => !withText('[data-testid="composer"] button', "Cancel"));
  const killed = await killCore(context);
  // Launch 2 reopens the stored conversation: the transcript is back.
  await reconnected(context, killed.client);
  await context.waitFor(() => withText('[data-testid="line"]', "remember this line"));
  expect(!withText('[data-testid="recovery"]', "could not"), "the stored conversation reopened");
  const backMs = context.now() - killed.at;
  expect(backMs < 10_000, `SC-003: the transcript is back in ${Math.round(backMs)} ms`);
  expect(workspace() === first, `the workspace is kept: ${workspace()}`);

  // Launch 2: a turn held mid-message, and the Core killed during it.
  await prompt(context, "Tell me something long.");
  await context.waitFor(() => withText('[data-testid="line"][data-state="streaming"]', "The first words"));
  const held = await killCore(context);
  // Launch 3: the interrupted turn is reported, and nothing is sent again.
  await reconnected(context, held.client);
  const notice = await context.waitFor(() => withText('[data-testid="recovery"]', "interrupted"));
  expect((notice.textContent ?? "").includes("not sent again"), notice.textContent ?? "");
  expect(workspace() === first, `the workspace is kept: ${workspace()}`);

  // Launch 3 crashes on the next send: the third crash in a row stops.
  await prompt(context, "this one crashes it");
  const view = await context.element('[data-testid="failure-view"][data-class="crashed"]');
  expect(restartsShown().includes("3 of 3"), `the count is shown: ${restartsShown()}`);
  expect(withText("button", "Try again", view) !== null, "Try again is offered");
  await noChooser(context);
  return { backMs: Math.round(backMs) };
};
