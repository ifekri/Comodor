/**
 * T027: the ready window against the offline Core (SC-001, FR-010).
 *
 * The page reports the moment the ready strip shows the model; the harness
 * measures it from the process start and fails above 10 seconds. The test
 * build reports this process's network listeners, and there must be none.
 */

import { expect, type Scenario } from "../runner.ts";

export const ready: Scenario = async (context) => {
  const strip = await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => strip.querySelector(".status-model")?.textContent === "fake-1");
  const readyAt = performance.timeOrigin + context.now();

  const text = strip.textContent ?? "";
  expect(text.includes("fake"), `the provider is shown: ${text}`);
  expect(text.includes("Configured"), `the configured state is shown: ${text}`);
  const shown = strip.querySelector(".status-workspace")?.textContent ?? "";
  expect(shown === context.params["workspace"],
         `the workspace is shown: ${shown} vs ${String(context.params["workspace"])}`);

  const { listeners } = await context.query("listeners");
  expect(Array.isArray(listeners) && listeners.length === 0,
         `the application listens on nothing: ${JSON.stringify(listeners)}`);
  return { readyAt, listeners };
};
