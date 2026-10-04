/**
 * Every in-application scenario, by the name the harness launches it with.
 */

import type { Scenario } from "../runner.ts";

import { boundary, canaryEarly } from "./boundary.ts";
import { conversation, conversationCancel, conversationPermission } from "./conversation.ts";
import { empty } from "./empty.ts";
import {
  lifetimeClose, lifetimeKill, lifetimeQuitHeld, lifetimeQuitNow, lifetimeSecondConfirmed,
  lifetimeSecondDeclined, lifetimeSecondSame,
} from "./lifetime.ts";
import { ready } from "./ready.ts";
import { crash, reload } from "./recovery.ts";
import { workspaceLaunch, workspaceLaunchPath } from "./workspace-launch.ts";

export const SCENARIOS: Readonly<Record<string, Scenario>> = {
  boundary,
  "canary-early": canaryEarly,
  conversation,
  "conversation-cancel": conversationCancel,
  "conversation-permission": conversationPermission,
  crash,
  empty,
  "lifetime-close": lifetimeClose,
  "lifetime-kill": lifetimeKill,
  "lifetime-kill-stubborn": lifetimeKill,
  "lifetime-quit-held": lifetimeQuitHeld,
  "lifetime-quit-now": lifetimeQuitNow,
  "lifetime-second-confirmed": lifetimeSecondConfirmed,
  "lifetime-second-declined": lifetimeSecondDeclined,
  "lifetime-second-same": lifetimeSecondSame,
  ready,
  reload,
  "workspace-launch": workspaceLaunch,
  "workspace-launch-path": workspaceLaunchPath,
};
