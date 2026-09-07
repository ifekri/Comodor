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
 */

import { CommandRegistry, type Command } from "@comodor/commands";
import { next as nextMode, type Mode } from "@comodor/modes";

export interface Screen {
  /** The core, for anything that has to be asked rather than decided here. */
  call(method: string, params?: Record<string, unknown>): Promise<unknown>;
  sessionId(): string | undefined;
  mode(): Mode;
  busy(): boolean;
  openPalette(): void;
  closePalette(): void;
  paletteOpen(): boolean;
  quit(): void;
  note(text: string): void;
}

export function build(): CommandRegistry<Screen> {
  const registry = new CommandRegistry<Screen>();

  const setMode = (mode: Mode): Command<Screen> => ({
    id: `mode.${mode}`,
    title: `Mode: ${mode.toUpperCase()}`,
    group: "Mode",
    keywords: [mode, "mode"],
    run: async (screen) => {
      const id = screen.sessionId();
      if (!id) return;
      // Asked, not assumed. The label moves when `mode.changed` arrives.
      await screen.call("session.set_mode", { session_id: id, mode });
    },
  });

  registry.add(
    {
      id: "mode.next",
      title: "Next mode",
      group: "Mode",
      keywords: ["tab", "act", "plan", "ask"],
      run: async (screen) => {
        const id = screen.sessionId();
        if (!id) return;
        await screen.call("session.set_mode",
          { session_id: id, mode: nextMode(screen.mode()) });
      },
    },
    {
      id: "mode.previous",
      title: "Previous mode",
      group: "Mode",
      keywords: ["shift+tab"],
      run: async (screen) => {
        const id = screen.sessionId();
        if (!id) return;
        await screen.call("session.set_mode",
          { session_id: id, mode: nextMode(screen.mode(), true) });
      },
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
  registry.bind(
    { key: "tab", command: "mode.next", hint: "Mode" },
    { key: "shift+tab", command: "mode.previous" },
    { key: "ctrl+k", command: "palette.open", hint: "Commands" },
    { key: "ctrl+d", command: "app.quit", hint: "Quit" },
  );

  return registry;
}
