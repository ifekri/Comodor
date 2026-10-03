/**
 * Every in-application scenario, by the name the harness launches it with.
 */

import type { Scenario } from "../runner.ts";

import { empty } from "./empty.ts";
import { ready } from "./ready.ts";
import { workspaceLaunch, workspaceLaunchPath } from "./workspace-launch.ts";

export const SCENARIOS: Readonly<Record<string, Scenario>> = {
  empty,
  ready,
  "workspace-launch": workspaceLaunch,
  "workspace-launch-path": workspaceLaunchPath,
};
