/**
 * Modes, for a client that has to draw them.
 *
 * What this is **not** is a policy. The core decides what a mode permits and
 * refuses anything else; nothing here can grant a capability, and a client
 * that lied about the current mode would change a label and nothing more.
 *
 * What a client genuinely needs is the presentation: the order to cycle in,
 * a name to show, and a sentence explaining what the mode means — none of
 * which the core sends, and all of which would otherwise be written three
 * times over once there is a terminal, a desktop and a web client.
 *
 * The cycle mirrors `src/comodor/safety/modes.py` and a test pins it against
 * the schema, which is generated from the same source the core reads. `chat`
 * exists and is deliberately not in the cycle: it predates `ask`, and landing
 * on it by pressing Tab would surprise somebody who only knows the three.
 */

export type Mode = "act" | "plan" | "ask" | "chat";

/** The three a person cycles through, in order. */
export const CYCLE: readonly Mode[] = ["act", "plan", "ask"] as const;

/** Every mode the core will accept, cycle or not. */
export const ALL: readonly Mode[] = ["act", "plan", "ask", "chat"] as const;

export interface ModeInfo {
  readonly id: Mode;
  /** Shown in the switcher. Upper case because it is a state, not a verb. */
  readonly label: string;
  /** One line, for a tooltip or a status bar. */
  readonly summary: string;
  /** The semantic token a renderer maps to a colour. Never a colour itself. */
  readonly token: `mode.${Mode}`;
}

export const MODES: Readonly<Record<Mode, ModeInfo>> = {
  act: {
    id: "act",
    label: "ACT",
    summary: "Reads, writes and runs commands, asking before it changes things.",
    token: "mode.act",
  },
  plan: {
    id: "plan",
    label: "PLAN",
    summary: "Reads and plans. It cannot write, run commands or change anything.",
    token: "mode.plan",
  },
  ask: {
    id: "ask",
    label: "ASK",
    summary: "Talks it through. Read-only, and it can still ask you questions.",
    token: "mode.ask",
  },
  chat: {
    id: "chat",
    label: "CHAT",
    summary: "Conversation only, with every tool switched off.",
    token: "mode.chat",
  },
};

export function isMode(value: unknown): value is Mode {
  return typeof value === "string" && (ALL as readonly string[]).includes(value);
}

/** The next mode a key press produces. Unknown or `chat` lands on the first. */
export function next(current: Mode | string, back = false): Mode {
  const at = CYCLE.indexOf(current as Mode);
  if (at < 0) return CYCLE[0] as Mode;
  const step = back ? -1 : 1;
  const index = (at + step + CYCLE.length) % CYCLE.length;
  return CYCLE[index] as Mode;
}

export function describe(mode: Mode | string): ModeInfo {
  return isMode(mode) ? MODES[mode] : MODES.act;
}
