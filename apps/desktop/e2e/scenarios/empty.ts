/**
 * The empty scenario: the test build starts, the page renders, the report
 * reaches the harness. It proves the machinery every other scenario uses.
 */

import type { Scenario } from "../runner.ts";

export const empty: Scenario = async (context) => {
  await context.element("main");
  return { rendered: true };
};
