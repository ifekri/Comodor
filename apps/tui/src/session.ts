/**
 * What the screen knows, and how a protocol event changes it.
 *
 * Kept apart from the components on purpose. The core is the authority on
 * every value here — this is a cache of what it last said, not a second copy
 * of the truth — and separating the reducer from the rendering is what lets
 * the ordering guarantees be tested without a terminal.
 *
 * The one rule the reducer follows: **never invent a transition the core did
 * not report.** Pressing Tab does not change the mode here; it sends
 * `session.set_mode` and waits for `mode.changed`. A client that moved its own
 * label first would show the wrong mode for as long as a refusal took to
 * arrive, and would show the wrong mode forever if the refusal was final.
 */

import type { EventName, Mode, Session } from "@comodor/protocol";

export type Speaker = "you" | "comodor";

export interface Line {
  readonly id: string;
  readonly speaker: Speaker;
  /** Grows as deltas arrive. */
  text: string;
  /** Extended thinking, kept apart so a client can hide it. */
  reasoning: string;
  done: boolean;
}

export interface ToolRun {
  readonly id: string;
  readonly name: string;
  summary: string;
  state: "running" | "done" | "failed";
  error?: string;
}

export type Connection =
  | { readonly kind: "starting" }
  | { readonly kind: "ready" }
  | { readonly kind: "lost"; readonly reason: string };

export interface State {
  readonly connection: Connection;
  readonly session?: Session;
  readonly lines: readonly Line[];
  readonly tools: readonly ToolRun[];
  /** The most recent notification, shown until the next one replaces it. */
  // `| undefined` because these are genuinely cleared, and
  // `exactOptionalPropertyTypes` is right that "absent" and "set to
  // undefined" are different things.
  readonly notice?: { level: string; text: string } | undefined;
  readonly question?: Record<string, unknown> | undefined;
  readonly permission?: Record<string, unknown> | undefined;
}

export const initial: State = {
  connection: { kind: "starting" },
  lines: [],
  tools: [],
};

export type Action =
  | { type: "connected"; session: Session }
  | { type: "lost"; reason: string }
  | { type: "said"; text: string }
  | { type: "event"; name: EventName; params: Record<string, unknown> };

export function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "connected":
      return { ...state, connection: { kind: "ready" }, session: action.session };

    case "lost":
      return { ...state, connection: { kind: "lost", reason: action.reason } };

    case "said":
      // The person's own line, added at once. This is the one thing the
      // client is the authority on: they typed it, and waiting for the core
      // to echo it back would make typing feel broken.
      return {
        ...state,
        lines: [...state.lines, {
          id: `you-${state.lines.length}`, speaker: "you",
          text: action.text, reasoning: "", done: true,
        }],
      };

    case "event":
      return apply(state, action.name, action.params);
  }
}

function apply(state: State, name: EventName,
               params: Record<string, unknown>): State {
  const text = String(params["text"] ?? "");

  switch (name) {
    case "session.created":
    case "session.updated":
      return { ...state, session: params["session"] as Session };

    case "mode.changed": {
      if (!state.session) return state;
      return {
        ...state,
        session: { ...state.session, mode: params["mode"] as Mode },
      };
    }

    case "message.started":
      return {
        ...state,
        lines: [...state.lines, {
          id: String(params["message_id"] ?? state.lines.length),
          speaker: "comodor", text: "", reasoning: "", done: false,
        }],
      };

    case "message.delta": {
      const channel = String(params["channel"] ?? "");
      return editLast(state, (line) => channel === "reasoning"
        ? { ...line, reasoning: line.reasoning + text }
        : { ...line, text: line.text + text });
    }

    case "message.completed":
      return editLast(state, (line) => ({
        ...line,
        // The completed event carries the whole answer. Preferring it over
        // the accumulated deltas means a dropped delta is corrected rather
        // than left as a gap nobody can see.
        text: text || line.text,
        done: true,
      }));

    case "tool.started":
      return {
        ...state,
        tools: [...state.tools, {
          id: String(params["call_id"] ?? ""),
          name: String(params["name"] ?? ""),
          summary: String(params["summary"] ?? ""),
          state: "running",
        }],
      };

    case "tool.completed":
      return editTool(state, String(params["call_id"] ?? ""), (tool) => ({
        ...tool,
        state: "done",
        summary: String(params["summary"] ?? tool.summary),
      }));

    case "tool.failed":
      return editTool(state, String(params["call_id"] ?? ""), (tool) => ({
        ...tool,
        state: "failed",
        error: String(params["error"] ?? ""),
      }));

    case "question.requested":
      return { ...state, question: params };

    case "question.resolved":
      return { ...state, question: undefined };

    case "permission.requested":
      return { ...state, permission: params };

    case "permission.resolved":
      return { ...state, permission: undefined };

    case "notification.created":
      return {
        ...state,
        notice: { level: String(params["level"] ?? "info"), text },
      };

    default:
      // `tool.output` and `model.changed` are carried but not drawn yet.
      // Ignoring an event this client does not use is how a newer core stays
      // compatible with an older client.
      return state;
  }
}

function editLast(state: State, change: (line: Line) => Line): State {
  const at = lastIndex(state.lines, (line) => line.speaker === "comodor"
    && !line.done);
  if (at < 0) return state;
  const lines = [...state.lines];
  lines[at] = change(lines[at] as Line);
  return { ...state, lines };
}

function editTool(state: State, id: string,
                  change: (tool: ToolRun) => ToolRun): State {
  const at = lastIndex(state.tools, (tool) => tool.id === id);
  if (at < 0) return state;
  const tools = [...state.tools];
  tools[at] = change(tools[at] as ToolRun);
  return { ...state, tools };
}

function lastIndex<T>(items: readonly T[], match: (item: T) => boolean): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (match(items[index] as T)) return index;
  }
  return -1;
}
