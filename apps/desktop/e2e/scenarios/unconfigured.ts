/**
 * T082: start with no provider configured, fix it outside the window, and
 * "Check again" (FR-031, SC-015) — with no application restart.
 */

import { expect, type Scenario, withText } from "../runner.ts";

export const unconfigured: Scenario = async (context) => {
  const notice = await context.element('[data-testid="setup-notice"]');
  expect((notice.textContent ?? "").includes("comodor setup"), "the direction to comodor setup");
  const strip = () => document.querySelector('[data-testid="status-strip"]')?.textContent ?? "";
  expect(strip().includes("Not configured"), `the strip says so: ${strip()}`);
  const send = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement;
  expect(send.disabled, "Send is unavailable");
  const { pid: first } = await context.query("core_pid");

  // What `comodor setup` would leave behind, written by the harness.
  await context.checkpoint("configure-provider");
  withText("button", "Check again", notice)!.click();

  await context.waitFor(() => document.querySelector('[data-testid="setup-notice"]') === null
    && strip().includes("Configured") && !strip().includes("Not configured"));
  await context.waitFor(() => {
    const button = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
    return button !== null && !button.disabled;
  });
  const { pid: second } = await context.query("core_pid");
  expect(second !== first, "a new Core read the configuration");
  expect(document.querySelector('[data-testid="stop-outcome"]') === null, "the restart was orderly");
  return { first, second };
};
