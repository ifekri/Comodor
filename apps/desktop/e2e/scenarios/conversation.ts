/**
 * T043: one conversation in the real window against the scripted Core
 * (FR-013, SC-014): a prompt, its stream, a form answered, a permission
 * answered, a mode change, and a cancel while the turn is held mid-message.
 * Each Core scenario is its own launch.
 */

import { expect, pressKey, type Scenario, type ScenarioContext, typeInto, withText } from "../runner.ts";

const QUESTION_PROMPT = "Build the service. Which database: SQLite or PostgreSQL?";

async function prompt(context: ScenarioContext, text: string): Promise<void> {
  // Send is available once the session has been read.
  await context.waitFor(() => {
    const send = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
    return send !== null && !send.disabled;
  });
  const field = await context.element('[data-testid="composer"] textarea');
  typeInto(field, text);
  pressKey(field, "Enter");
  await context.waitFor(() => withText('[data-testid="line"]', text));
}

/** The question fixture: stream, form, the rest of the answer, then a mode. */
export const conversation: Scenario = async (context) => {
  await prompt(context, QUESTION_PROMPT);
  await context.waitFor(() => withText('[data-testid="line"]', "Asking."));

  const form = await context.element('[data-testid="form"]');
  expect(withText("button", "SQLite", form) !== null, "SQLite is offered");
  expect(withText("button", "PostgreSQL", form) !== null, "PostgreSQL is offered");
  expect(form.querySelector('input[type="text"]') !== null, "the write-your-own row is a field");
  withText("button", "SQLite", form)!.click();
  const current = document.querySelector('[data-testid="form"]');
  expect(form.isConnected && current === form,
         `the form was redrawn under the click (connected ${String(form.isConnected)})`);
  // The choice renders before the answer can be sent.
  const send = await context.waitFor(() => {
    const button = withText("button", "Answer", form) as HTMLButtonElement | null;
    return button !== null && !button.disabled && button;
  });
  send.click();
  await context.waitFor(() => document.querySelector('[data-testid="form"]') === null);
  // The Core took exactly the choice: its own tool summary names it.
  await context.waitFor(() => withText('[data-testid="tool"][data-state="completed"]', "Database: SQLite"));
  expect(withText('[data-testid="line"]', QUESTION_PROMPT) !== null, "the prompt stays in the conversation");

  const label = () => document.querySelector('[data-testid="mode"] [data-current]')?.textContent;
  expect(label() === "ACT", `the session starts in ACT: ${String(label())}`);
  withText('[data-testid="mode"] button', "PLAN")!.click();
  await context.waitFor(() => label() === "PLAN");
  return { mode: label() };
};

/** The permission fixture: every choice shown, and the reply decides. */
export const conversationPermission: Scenario = async (context) => {
  await prompt(context, "Write the file.");
  const card = await context.element('[data-testid="permission"]');
  const choices = [...card.querySelectorAll<HTMLButtonElement>("button")].map((b) => b.dataset["choice"]);
  expect(choices.includes("allow") && choices.includes("deny"), `choices: ${JSON.stringify(choices)}`);
  expect((card.textContent ?? "").includes("write_file"), "the tool is named");
  card.querySelector<HTMLButtonElement>('button[data-choice="deny"]')!.click();
  await context.waitFor(() => document.querySelector('[data-testid="permission"]') === null);
  // The Core received the refusal: the tool it held is declined.
  const tool = await context.waitFor(() => document.querySelector<HTMLElement>(
    '[data-testid="tool"][data-state="failed"]'));
  expect((tool.textContent ?? "").includes("write_file"), `the declined tool: ${tool.textContent}`);
  return { choices, tool: tool.textContent };
};

/** The hold fixture: cancel while the answer is provably mid-message. */
export const conversationCancel: Scenario = async (context) => {
  await prompt(context, "Tell me something long.");
  const answer = await context.waitFor(() => document.querySelector<HTMLElement>(
    '[data-testid="line"][data-state="streaming"]'));
  await context.waitFor(() => (answer.textContent ?? "").includes("The first words"));
  const cancel = await context.waitFor(() => withText('[data-testid="composer"] button', "Cancel"));
  cancel.click();
  // The Core has the cancel; the fixture is let go so its thread can see it.
  await context.checkpoint("release-hold");
  await context.waitFor(() => answer.dataset["state"] === "cancelled");
  return { state: answer.dataset["state"] };
};
