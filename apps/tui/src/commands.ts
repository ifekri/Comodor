/**
 * Every action this client can take, and the keys that reach them.
 *
 * One list. The palette reads it, the key handler reads it, and the footer
 * prints from it — so a shortcut cannot be advertised without existing, and
 * `CommandRegistry.bind` refuses at build time if it is.
 *
 * That check is here because the previous interface shipped a footer
 * advertising `ctrl+s` and `esc` for things that did nothing. Nobody had lied;
 * the label and the binding were simply written in different files.
 *
 * The mode commands changed shape in F2. They used to compute the next mode
 * from the last one the core had confirmed and call `session.set_mode`
 * directly, which lost every press that arrived inside a round trip. They now
 * record *intent*; one coordinator decides what to ask the core for and when.
 * The command is still the single way in — four surfaces, one action — but
 * what it does is say where the person wants to end up.
 */

import { CommandRegistry, type Command } from "@comodor/commands";
import type { Mode } from "@comodor/modes";

export interface Screen {
  /** The core, for anything that has to be asked rather than decided here. */
  call(method: string, params?: Record<string, unknown>): Promise<unknown>;
  sessionId(): string | undefined;
  mode(): Mode;
  busy(): boolean;
  /** Aim one step around the cycle. Repeats accumulate; see `@comodor/session`. */
  stepMode(back: boolean): void;
  /** Aim at a named mode outright — a click, or a palette entry. */
  wantMode(mode: Mode): void;
  /** Ask the core what it can answer with, and open the chooser. */
  openModels(): void;
  openPalette(): void;
  closePalette(): void;
  paletteOpen(): boolean;
  /** Back to the newest line, and follow it again. */
  toTail(): void;
  /** Whether a prompt is sitting unsent because the core refused it. */
  hasUnsent(): boolean;
  /** Send it again. */
  retry(): void;
  quit(): void;
  note(text: string): void;
  /** Whether the core advertised workbench state to draw at all. */
  workbenchAvailable(): boolean;
  /** Whether the workbench currently owns the cursor keys. */
  workbenchOpen(): boolean;
  openWorkbench(): void;
  closeWorkbench(): void;
  /**
   * The delegate the cursor is on, when its lifecycle says it may be stopped.
   * `undefined` otherwise — which is what makes the stop command's
   * availability the projection's answer rather than the panel's opinion.
   */
  stoppableDelegateId(): string | undefined;
  /** Ask the core to stop one delegate. The core's events say what became of it. */
  stopDelegate(id: string): void;
}

export function build(): CommandRegistry<Screen> {
  const registry = new CommandRegistry<Screen>();

  const setMode = (mode: Mode): Command<Screen> => ({
    id: `mode.${mode}`,
    title: `Mode: ${mode.toUpperCase()}`,
    group: "Mode",
    keywords: [mode, "mode"],
    // Intent, not an assertion. The label moves when `mode.changed` arrives.
    run: (screen) => screen.wantMode(mode),
  });

  registry.add(
    {
      id: "mode.next",
      title: "Next mode",
      group: "Mode",
      keywords: ["tab", "act", "plan", "ask"],
      run: (screen) => screen.stepMode(false),
    },
    {
      id: "mode.previous",
      title: "Previous mode",
      group: "Mode",
      keywords: ["shift+tab"],
      run: (screen) => screen.stepMode(true),
    },
    setMode("act"),
    setMode("plan"),
    setMode("ask"),
    {
      id: "session.cancel",
      title: "Cancel what it is doing",
      group: "Session",
      keywords: ["stop", "ctrl+c"],
      enabled: (screen) => screen.busy(),
      run: async (screen) => {
        const id = screen.sessionId();
        if (id) await screen.call("session.cancel", { session_id: id });
      },
    },
    {
      id: "session.retry",
      title: "Send the unsent message again",
      group: "Session",
      keywords: ["retry", "again", "failed"],
      enabled: (screen) => screen.hasUnsent(),
      // Explicitly, and only for a send the core never accepted. A turn that
      // was accepted and then failed is not resent: the tools it already ran
      // would run again, and "retry everything" is how one refusal becomes
      // two edits.
      run: (screen) => screen.retry(),
    },
    {
      id: "view.tail",
      title: "Jump to the newest output",
      group: "View",
      keywords: ["bottom", "end", "follow", "latest"],
      run: (screen) => screen.toTail(),
    },
    {
      id: "workbench.show",
      title: "Show the workbench",
      group: "View",
      keywords: ["agents", "tasks", "delegates", "background", "workbench",
                 "ctrl+b"],
      // Offered only where the core advertised something to show: a client
      // pointed at an older core must not offer a panel that would be empty
      // forever, and must otherwise behave exactly as it does today.
      enabled: (screen) => screen.workbenchAvailable(),
      run: (screen) => screen.openWorkbench(),
    },
    {
      id: "workbench.close",
      title: "Close the workbench",
      group: "View",
      keywords: ["agents", "tasks", "workbench"],
      enabled: (screen) => screen.workbenchOpen(),
      run: (screen) => screen.closeWorkbench(),
    },
    {
      id: "agents.stop",
      title: "Stop the selected background agent",
      group: "Agents",
      keywords: ["delegate", "stop", "background", "kill"],
      // The availability is the lifecycle's answer: a delegate may be asked
      // to stop while it is running, and at no other time. The request goes
      // to the core, and what the delegate becomes is what the core's next
      // `delegate.updated` says — never a state this client painted.
      enabled: (screen) => screen.stoppableDelegateId() !== undefined,
      run: (screen) => {
        const id = screen.stoppableDelegateId();
        if (id) screen.stopDelegate(id);
      },
    },
    {
      id: "model.choose",
      title: "Choose the model",
      group: "Session",
      keywords: ["model", "provider", "switch"],
      run: (screen) => screen.openModels(),
    },
    {
      id: "palette.open",
      title: "Commands",
      group: "Session",
      keywords: ["palette", "ctrl+k"],
      run: (screen) => screen.openPalette(),
    },
    {
      id: "app.quit",
      title: "Quit",
      group: "Session",
      keywords: ["exit", "close"],
      run: (screen) => screen.quit(),
    },
  );

  // Only what a person is actually told about gets a hint. `escape` is real
  // and unadvertised, which is allowed; what is not allowed is the reverse.
  //
  // `end` and `ctrl+r` are bound and deliberately hintless: the footer has
  // room for four things, and both are announced where they matter — `end`
  // beside the new-output marker, `ctrl+r` beside the message that failed.
  //
  // The workbench sits ahead of the palette on purpose: on a narrow terminal
  // the footer keeps only its first two hints, and the key that reaches the
  // agents and tasks is the one that must survive that cut.
  registry.bind(
    { key: "tab", command: "mode.next", hint: "Mode" },
    { key: "shift+tab", command: "mode.previous" },
    { key: "ctrl+b", command: "workbench.show", hint: "Work" },
    { key: "ctrl+k", command: "palette.open", hint: "Commands" },
    { key: "ctrl+d", command: "app.quit", hint: "Quit" },
    { key: "end", command: "view.tail" },
    { key: "ctrl+r", command: "session.retry" },
  );

  return registry;
}
