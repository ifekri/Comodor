/**
 * Every in-application scenario, by the name the harness launches it with.
 */

import type { Scenario } from "../runner.ts";

import { accessibilityClosing, accessibilityReady, accessibilityState } from "./accessibility.ts";
import { boundary, canaryEarly } from "./boundary.ts";
import { conversation, conversationCancel, conversationPermission } from "./conversation.ts";
import { corePanel, diagnosticsPanel } from "./core-panel.ts";
import { empty } from "./empty.ts";
import {
  lifetimeClose, lifetimeKill, lifetimeQuitHeld, lifetimeQuitNow, lifetimeSecondConfirmed,
  lifetimeSecondDeclined, lifetimeSecondSame,
} from "./lifetime.ts";
import { layoutRelaunchOther, layoutRelaunchSame } from "./lifetime.ts";
import { keyDelivery } from "./key-delivery.ts";
import { keyboard } from "./keyboard.ts";
import { layout, layoutSeeded } from "./layout.ts";
import { narrow } from "./narrow.ts";
import { palette, paletteClosing, paletteFailure, paletteUnconfigured } from "./palette.ts";
import { ready } from "./ready.ts";
import { reducedMotion, reducedMotionTransition } from "./reduced-motion.ts";
import { shell, shellFailure } from "./shell.ts";
import { unconfigured } from "./unconfigured.ts";
import { crash, reload, wake } from "./recovery.ts";
import { workspaceChange, workspaceLaunch, workspaceLaunchPath, workspaceProjectRoot } from "./workspace-launch.ts";

export const SCENARIOS: Readonly<Record<string, Scenario>> = {
  "accessibility": accessibilityReady,
  "accessibility-absent": accessibilityState,
  "accessibility-checking": accessibilityState,
  "accessibility-closing": accessibilityClosing,
  "accessibility-failed": accessibilityState,
  "accessibility-restarting": accessibilityState,
  "accessibility-starting": accessibilityState,
  "accessibility-unconfigured": accessibilityState,
  boundary,
  "canary-early": canaryEarly,
  conversation,
  "conversation-cancel": conversationCancel,
  "conversation-permission": conversationPermission,
  "core-panel": corePanel,
  crash,
  "diagnostics-panel": diagnosticsPanel,
  empty,
  "key-delivery": keyDelivery,
  keyboard,
  layout,
  "layout-relaunch-other": layoutRelaunchOther,
  "layout-relaunch-same": layoutRelaunchSame,
  "layout-seeded-range": layoutSeeded,
  "layout-seeded-unreadable": layoutSeeded,
  "layout-seeded-valid": layoutSeeded,
  "layout-seeded-version": layoutSeeded,
  "lifetime-close": lifetimeClose,
  "lifetime-kill": lifetimeKill,
  "lifetime-kill-stubborn": lifetimeKill,
  "lifetime-quit-held": lifetimeQuitHeld,
  "lifetime-quit-now": lifetimeQuitNow,
  "lifetime-second-confirmed": lifetimeSecondConfirmed,
  "lifetime-second-declined": lifetimeSecondDeclined,
  "lifetime-second-same": lifetimeSecondSame,
  narrow,
  palette,
  "palette-closing": paletteClosing,
  "palette-failure": paletteFailure,
  "palette-unconfigured": paletteUnconfigured,
  ready,
  "reduced-motion": reducedMotion,
  "reduced-motion-transition": reducedMotionTransition,
  reload,
  shell,
  "shell-failure": shellFailure,
  unconfigured,
  wake,
  "workspace-change": workspaceChange,
  "workspace-launch": workspaceLaunch,
  "workspace-launch-path": workspaceLaunchPath,
  "workspace-project-root": workspaceProjectRoot,
};
