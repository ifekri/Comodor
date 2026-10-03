/**
 * Every in-application scenario, by the name the harness launches it with.
 */

import type { Scenario } from "../runner.ts";

import { empty } from "./empty.ts";

export const SCENARIOS: Readonly<Record<string, Scenario>> = {
  empty,
};
