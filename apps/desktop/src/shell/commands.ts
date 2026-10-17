/**
 * The workbench's commands (contracts/workbench-shell.md, "Commands"), in
 * the window's one registry beside D1's Send and Cancel. Every button,
 * shortcut and palette entry for an action is the same command; each is
 * enabled only when its rule — D1's gate for anything that reaches the Core —
 * holds (FR-011, FR-012, FR-029).
 */

import type { Binding, Command } from "@comodor/commands";
import { CYCLE, type Mode, MODES } from "@comodor/modes";

import type { CoreStatus } from "../bridge.ts";
import type { WindowContext } from "../commands.ts";
import type { PanelSurface } from "./layout.ts";
import type { SharedSession } from "./session-store.ts";

export const WORKBENCH_COMMAND_IDS = {
  paletteOpen: "palette.open",
  composerFocus: "composer.focus",
  viewTail: "view.tail",
  modeAct: "mode.act",
  modePlan: "mode.plan",
  modeAsk: "mode.ask",
  modeNext: "mode.next",
  modePrevious: "mode.previous",
  workspaceChange: "workspace.change",
  checkAgain: "core.check_again",
  retry: "core.retry",
  quitNow: "app.quit_now",
  viewConversation: "view.conversation",
  viewCore: "view.core",
  viewDiagnostics: "view.diagnostics",
  viewShortcuts: "view.shortcuts",
  diagnosticsRefresh: "diagnostics.refresh",
  panelClose: "panel.close",
  sidebarToggle: "sidebar.toggle",
  layoutReset: "layout.reset",
  regionNext: "region.next",
  regionPrevious: "region.previous",
} as const;

const ID = WORKBENCH_COMMAND_IDS;

/** What the shell shows now: the facts the rules read. */
export interface ShellState {
  readonly status: CoreStatus | null;
  readonly session: SharedSession | null;
  readonly paletteOpen: boolean;
  readonly panelOpen: boolean;
  readonly panelSurface: PanelSurface;
  /** Whether the sidebar is shown, beside the canvas or covering it. */
  readonly sidebarShown: boolean;
}

/** What the commands do: the shell's own actions and D1's native ones. */
export interface ShellActions {
  openPalette(): void;
  showConversation(): void;
  showSurface(surface: PanelSurface): void;
  closePanel(): void;
  toggleSidebar(): void;
  resetLayout(): void;
  nextRegion(): void;
  previousRegion(): void;
  focusComposer(): void;
  jumpToNewest(): void;
  refreshDiagnostics(): void;
  changeWorkspace(): void;
  checkAgain(): void;
  retry(): void;
  quitNow(): void;
}

export interface ShellContext {
  readonly state: ShellState;
  readonly act: ShellActions;
}

/** Where a workspace can be chosen: anything but a Core on its way out. */
const CHANGE_STATES = new Set(["starting", "handshaking", "restarting", "ready", "checking", "failed", "absent"]);

type Rule = (shell: ShellContext) => boolean;

function command(id: string, title: string, group: string, keywords: string[], enabled: Rule,
                 run: (shell: ShellContext) => void): Command<WindowContext> {
  return {
    id, title, group, keywords,
    enabled: (context) => context.shell !== undefined && enabled(context.shell),
    run: (context) => {
      if (context.shell) run(context.shell);
    },
  };
}

/** A session is shown and D1's gate is open. */
const open = (shell: ShellContext): SharedSession | null => {
  const session = shell.state.session;
  return session !== null && session.shown && !session.gated ? session : null;
};

function step(mode: Mode, by: 1 | -1): Mode {
  const at = CYCLE.indexOf(mode);
  return CYCLE[((at < 0 ? 0 : at) + by + CYCLE.length) % CYCLE.length]!;
}

function modeCommand(mode: Mode): Command<WindowContext> {
  return command(`mode.${mode}`, `Mode: ${MODES[mode].label}`, "Mode", [MODES[mode].label.toLowerCase(), "mode"],
                 (shell) => {
                   const session = open(shell);
                   return session !== null && session.intent.confirmed !== mode;
                 },
                 (shell) => open(shell)?.chooseMode(mode));
}

export function workbenchCommands(): Command<WindowContext>[] {
  const always: Rule = () => true;
  const shown: Rule = (shell) => shell.state.session?.shown === true;
  const state = (shell: ShellContext) => shell.state.status?.state;
  return [
    command(ID.paletteOpen, "Commands", "Workbench", ["palette", "command", "search"],
            (shell) => !shell.state.paletteOpen, (shell) => shell.act.openPalette()),
    command(ID.composerFocus, "Go to the message box", "Conversation", ["prompt", "message", "write"],
            shown, (shell) => shell.act.focusComposer()),
    command(ID.viewTail, "Jump to the newest output", "Conversation", ["bottom", "scroll", "latest"],
            shown, (shell) => shell.act.jumpToNewest()),
    ...CYCLE.map(modeCommand),
    command(ID.modeNext, "Next mode", "Mode", ["mode", "cycle"],
            (shell) => open(shell) !== null,
            (shell) => {
              const session = open(shell);
              session?.chooseMode(step(session.intent.desired, 1));
            }),
    command(ID.modePrevious, "Previous mode", "Mode", ["mode", "cycle"],
            (shell) => open(shell) !== null,
            (shell) => {
              const session = open(shell);
              session?.chooseMode(step(session.intent.desired, -1));
            }),
    command(ID.workspaceChange, "Change workspace…", "Core", ["folder", "project", "choose"],
            (shell) => CHANGE_STATES.has(state(shell) ?? ""), (shell) => shell.act.changeWorkspace()),
    command(ID.checkAgain, "Check again", "Core", ["setup", "provider", "configure"],
            (shell) => state(shell) === "ready" && shell.state.session?.model?.configured === false,
            (shell) => shell.act.checkAgain()),
    command(ID.retry, "Try again", "Core", ["restart", "start"],
            (shell) => state(shell) === "failed", (shell) => shell.act.retry()),
    command(ID.quitNow, "Quit now", "Core", ["exit", "force"],
            (shell) => state(shell) === "stopping", (shell) => shell.act.quitNow()),
    command(ID.viewConversation, "Show the conversation", "Workbench", ["chat", "messages", "main"],
            always, (shell) => shell.act.showConversation()),
    command(ID.viewCore, "Show the Core panel", "Workbench", ["status", "version", "protocol"],
            always, (shell) => shell.act.showSurface("core")),
    command(ID.viewDiagnostics, "Show diagnostics", "Workbench", ["output", "stderr", "errors"],
            always, (shell) => shell.act.showSurface("diagnostics")),
    command(ID.viewShortcuts, "Show keyboard shortcuts", "Workbench", ["keys", "help"],
            always, (shell) => shell.act.showSurface("shortcuts")),
    command(ID.diagnosticsRefresh, "Refresh diagnostics", "Workbench", ["again", "fetch"],
            (shell) => shell.state.panelOpen && shell.state.panelSurface === "diagnostics",
            (shell) => shell.act.refreshDiagnostics()),
    command(ID.panelClose, "Close the panel", "Workbench", ["hide", "dismiss"],
            (shell) => shell.state.panelOpen, (shell) => shell.act.closePanel()),
    command(ID.sidebarToggle, "Show or hide the sidebar", "Workbench", ["sidebar", "session", "navigation"],
            always, (shell) => shell.act.toggleSidebar()),
    command(ID.layoutReset, "Reset layout", "Workbench", ["default", "restore"],
            always, (shell) => shell.act.resetLayout()),
    command(ID.regionNext, "Next region", "Workbench", ["focus", "pane"],
            always, (shell) => shell.act.nextRegion()),
    command(ID.regionPrevious, "Previous region", "Workbench", ["focus", "pane"],
            always, (shell) => shell.act.previousRegion()),
  ];
}

export function workbenchBindings(): Binding[] {
  return [
    { key: "mod+k", command: ID.paletteOpen, hint: "Commands" },
    { key: "mod+shift+m", command: ID.modeNext },
    { key: "mod+1", command: ID.viewConversation },
    { key: "mod+2", command: ID.viewCore },
    { key: "mod+3", command: ID.viewDiagnostics },
    { key: "mod+/", command: ID.viewShortcuts },
    { key: "mod+o", command: ID.workspaceChange },
    { key: "mod+b", command: ID.sidebarToggle },
    { key: "f6", command: ID.regionNext },
    { key: "shift+f6", command: ID.regionPrevious },
    // After D1's Escape (Cancel), so the composer still finds Cancel first;
    // the shell resolves Escape itself, in the contract's order.
    { key: "escape", command: ID.panelClose },
  ];
}
