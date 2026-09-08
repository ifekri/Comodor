/**
 * One Comodor session, as a client holds it.
 *
 * A projection, not a second source of truth. The core is the authority on
 * every value here; this is a cache of what it last said, kept so a renderer
 * has something to draw between events. Where the two could disagree, the
 * core wins — and where the client has an opinion of its own (a prompt not yet
 * accepted, a mode not yet confirmed) that opinion is kept in a field that
 * says so rather than written into the confirmed state.
 *
 * It lives in a package rather than beside the terminal components because
 * none of it is about a terminal. Correlating a delta to its message, keeping
 * two tools' output apart, deciding a snapshot is stale — a desktop client
 * would need every one of those, and would otherwise reimplement them
 * slightly differently.
 *
 * Three rules it follows:
 *
 * **Never invent a transition the core did not report.** Pressing Tab does not
 * change the mode here.
 *
 * **Correlate on ids, never on position.** A delta goes to the message its
 * `message_id` names. "The last unfinished message" is right until two
 * messages overlap, and the core produces overlapping tools already.
 *
 * **Say when it does not know.** A gap in the sequence is reported, not
 * smoothed over: a projection that quietly carried on would be missing a
 * message nobody could see was missing.
 */

import type { EventName, Mode, Session } from "@comodor/protocol";

export type Speaker = "you" | "comodor";

/** Where a message got to. `pending` is the client's own, before the core answers. */
export type MessageState =
  | "pending" | "failed_to_send"
  | "streaming" | "completed" | "cancelled" | "failed";

export interface Line {
  readonly id: string;
  readonly turnId: string;
  /** Arrival order, shared with tools, so the two can be drawn interleaved. */
  readonly at: number;
  readonly speaker: Speaker;
  /** Grows as deltas arrive. */
  readonly text: string;
  /** Extended thinking, kept apart so a client can hide it. */
  readonly reasoning: string;
  readonly state: MessageState;
  /** Why it failed, when it did. Shown; never a stack trace. */
  readonly error?: string | undefined;
}

export type ToolState = "running" | "completed" | "failed";

export interface ToolRun {
  readonly id: string;
  readonly turnId: string;
  /** Arrival order, shared with lines. See `timeline`. */
  readonly at: number;
  readonly name: string;
  readonly summary: string;
  readonly state: ToolState;
  /** Streamed output, in arrival order, for this call and no other. */
  readonly output: string;
  readonly outputTruncated: boolean;
  readonly error?: string | undefined;
  readonly elapsedMs?: number | undefined;
}

export type Connection =
  | { readonly kind: "starting" }
  | { readonly kind: "ready" }
  | { readonly kind: "resynchronising" }
  | { readonly kind: "lost"; readonly reason: string };

export interface State {
  readonly connection: Connection;
  readonly session?: Session | undefined;
  readonly lines: readonly Line[];
  readonly tools: readonly ToolRun[];
  /** The most recent notification, shown until the next one replaces it. */
  readonly notice?: { level: string; text: string } | undefined;
  readonly question?: Record<string, unknown> | undefined;
  readonly permission?: Record<string, unknown> | undefined;
  /**
   * The highest sequence number applied. Everything at or below it is already
   * in this state; a snapshot taken at or below it is stale and is dropped.
   */
  readonly revision: number;
  /**
   * How many things have been added, ever. Not an index into anything — only
   * a total order, so a message and a tool that arrived one after the other
   * can be drawn one after the other.
   */
  readonly arrivals: number;
  /**
   * Set when the sequence skipped a number. The projection is then knowingly
   * incomplete and the only honest repair is to ask the core again.
   */
  readonly gap: boolean;
}

export const initial: State = {
  connection: { kind: "starting" },
  lines: [],
  tools: [],
  revision: 0,
  arrivals: 0,
  gap: false,
};

/** What the core answers `session.snapshot` with. */
export interface Snapshot {
  session: Session;
  revision: number;
  messages: Array<{
    message_id: string; turn_id: string; role: string; text: string;
    reasoning?: string; status: string;
  }>;
  tools: Array<{
    call_id: string; turn_id: string; name: string; summary?: string;
    state: string; output?: string; output_truncated?: boolean;
    error?: string; elapsed_ms?: number;
  }>;
  question?: Record<string, unknown>;
  permission?: Record<string, unknown>;
}

export type Action =
  | { type: "connected"; session: Session }
  | { type: "resynchronising" }
  | { type: "lost"; reason: string }
  /** The person's prompt, before the core has accepted it. */
  | { type: "sending"; localId: string; text: string }
  | { type: "accepted"; localId: string; turnId: string }
  | { type: "rejected"; localId: string; reason: string }
  | { type: "retrying"; localId: string }
  | { type: "snapshot"; snapshot: Snapshot }
  | { type: "event"; name: EventName; params: Record<string, unknown>;
      seq: number };

export function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "connected":
      return { ...state, connection: { kind: "ready" }, session: action.session };

    case "resynchronising":
      return { ...state, connection: { kind: "resynchronising" } };

    case "lost":
      return { ...state, connection: { kind: "lost", reason: action.reason } };

    case "sending":
      // Shown at once, and shown as *pending*. Waiting for the core to echo it
      // would make typing feel broken; claiming it was accepted would be a
      // lie the moment the send is refused.
      return {
        ...state,
        arrivals: state.arrivals + 1,
        lines: [...state.lines, {
          id: action.localId, turnId: "", at: state.arrivals + 1,
          speaker: "you", text: action.text, reasoning: "", state: "pending",
        }],
      };

    case "accepted":
      return editLine(state, action.localId, (line) => ({
        ...line, turnId: action.turnId, state: "completed",
      }));

    case "rejected":
      // The text stays on screen. A composer that cleared itself into a
      // failed request is a composer that ate somebody's paragraph.
      return editLine(state, action.localId, (line) => ({
        ...line, state: "failed_to_send", error: action.reason,
      }));

    case "retrying":
      return editLine(state, action.localId, (line) => ({
        ...line, state: "pending", error: undefined,
      }));

    case "snapshot":
      return applySnapshot(state, action.snapshot);

    case "event":
      return applyEvent(state, action);
  }
}

/**
 * Replace the projection with what the core says, and remember how far that
 * goes.
 *
 * A snapshot at or below the current revision is *older* than what is already
 * applied and is dropped: it would undo events that have arrived since. That
 * is the race this whole mechanism exists for — the snapshot is built on one
 * thread while a turn streams on another, and either can reach the client
 * first.
 */
function applySnapshot(state: State, snapshot: Snapshot): State {
  if (snapshot.revision < state.revision) return state;

  // A snapshot arrives as two lists, and the order within each is the order
  // things happened. Interleaving them exactly would need the core to number
  // them across both; what it guarantees is that a turn's messages and that
  // turn's tools are each in order, which is enough to draw them grouped by
  // turn without inventing an order the core never stated.
  let at = 0;
  const lines: Line[] = snapshot.messages.map((message) => ({
    id: message.message_id,
    turnId: message.turn_id,
    at: (at += 1),
    speaker: message.role === "user" ? "you" : "comodor",
    text: message.text,
    reasoning: message.reasoning ?? "",
    state: messageState(message.status),
  }));

  const tools: ToolRun[] = snapshot.tools.map((tool) => ({
    id: tool.call_id,
    turnId: tool.turn_id,
    at: (at += 1),
    name: tool.name,
    summary: tool.summary ?? "",
    state: toolState(tool.state),
    output: tool.output ?? "",
    outputTruncated: Boolean(tool.output_truncated),
    error: tool.error,
    elapsedMs: tool.elapsed_ms,
  }));

  return {
    ...state,
    connection: { kind: "ready" },
    session: snapshot.session,
    lines,
    tools,
    question: snapshot.question,
    permission: snapshot.permission,
    revision: snapshot.revision,
    arrivals: at,
    gap: false,
  };
}

function messageState(status: string): MessageState {
  return status === "cancelled" || status === "failed" || status === "completed"
    ? status
    : "streaming";
}

function toolState(state: string): ToolState {
  return state === "completed" || state === "failed" ? state : "running";
}

/**
 * One event, if it is one this projection has not already seen.
 *
 * Three cases, and each is answered explicitly rather than by falling through:
 * an event at or below the revision has been applied (a duplicate, or one that
 * predates a snapshot) and is dropped; an event exactly one above continues
 * the sequence; anything higher means something never arrived, which is
 * recorded so a caller can resynchronise instead of drawing a session with a
 * hole in it.
 */
function applyEvent(state: State, action: Extract<Action, { type: "event" }>): State {
  const { seq } = action;
  if (seq > 0 && seq <= state.revision) return state;

  const missed = seq > 0 && state.revision > 0 && seq > state.revision + 1;
  const next = apply(state, action.name, action.params);
  return {
    ...next,
    revision: seq > 0 ? Math.max(next.revision, seq) : next.revision,
    gap: next.gap || missed,
  };
}

function apply(state: State, name: EventName,
               params: Record<string, unknown>): State {
  const text = String(params["text"] ?? "");
  const messageId = String(params["message_id"] ?? "");
  const callId = String(params["call_id"] ?? "");

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

    case "message.started": {
      if (!messageId) return state;
      // A second start for an id already held is a fault at the core, not a
      // second message. Restarting the one that exists keeps the projection
      // consistent; appending would leave two entries a renderer cannot
      // tell apart and a key nobody could use.
      if (state.lines.some((line) => line.id === messageId)) {
        return editLine(state, messageId, (line) => ({
          ...line, text: "", reasoning: "", state: "streaming",
        }));
      }
      return {
        ...state,
        arrivals: state.arrivals + 1,
        lines: [...state.lines, {
          id: messageId,
          turnId: String(params["turn_id"] ?? ""),
          at: state.arrivals + 1,
          speaker: "comodor", text: "", reasoning: "", state: "streaming",
        }],
      };
    }

    case "message.delta": {
      // Routed by id. A delta for a message this client has never been told
      // about is dropped rather than appended to whatever is nearest: the
      // second is how one answer ends up inside another.
      const channel = String(params["channel"] ?? "");
      return editLine(state, messageId, (line) => channel === "reasoning"
        ? { ...line, reasoning: line.reasoning + text }
        : { ...line, text: line.text + text });
    }

    case "message.completed": {
      const status = String(params["status"] ?? "completed");
      return editLine(state, messageId, (line) => ({
        ...line,
        // The completed event carries the whole answer where there is one, so
        // a dropped delta is corrected rather than left as a gap nobody sees.
        text: text || line.text,
        state: messageState(status),
        error: params["error"] === undefined
          ? undefined : String(params["error"]),
      }));
    }

    case "tool.started": {
      if (!callId) return state;
      if (state.tools.some((tool) => tool.id === callId)) return state;
      return {
        ...state,
        arrivals: state.arrivals + 1,
        tools: [...state.tools, {
          id: callId,
          turnId: String(params["turn_id"] ?? ""),
          at: state.arrivals + 1,
          name: String(params["name"] ?? ""),
          summary: String(params["summary"] ?? ""),
          state: "running",
          output: "",
          outputTruncated: false,
        }],
      };
    }

    case "tool.output":
      // Appended to the call it names. This is the whole reason the core tags
      // output at its origin: two tools running at once produce interleaved
      // events, and "whichever started most recently" would put half of each
      // under the other.
      return editTool(state, callId, (tool) => ({
        ...tool, output: tool.output + text,
      }));

    case "tool.completed":
      return editTool(state, callId, (tool) => ({
        ...tool,
        state: "completed",
        summary: String(params["summary"] ?? tool.summary),
        elapsedMs: typeof params["elapsed_ms"] === "number"
          ? params["elapsed_ms"] : tool.elapsedMs,
      }));

    case "tool.failed":
      return editTool(state, callId, (tool) => ({
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
      // An event this client does not use. Ignoring it by name is how a newer
      // core stays compatible with an older client.
      return state;
  }
}

function editLine(state: State, id: string,
                  change: (line: Line) => Line): State {
  if (!id) return state;
  const at = state.lines.findIndex((line) => line.id === id);
  if (at < 0) return state;
  const lines = [...state.lines];
  lines[at] = change(lines[at] as Line);
  return { ...state, lines };
}

function editTool(state: State, id: string,
                  change: (tool: ToolRun) => ToolRun): State {
  if (!id) return state;
  const at = state.tools.findIndex((tool) => tool.id === id);
  if (at < 0) return state;
  const tools = [...state.tools];
  tools[at] = change(tools[at] as ToolRun);
  return { ...state, tools };
}

// --------------------------------------------------------------------------- //
// reading the projection
// --------------------------------------------------------------------------- //

/** The tools belonging to one turn, in the order they started. */
export function toolsOfTurn(state: State, turnId: string): readonly ToolRun[] {
  return state.tools.filter((tool) => tool.turnId === turnId);
}

/** Whether anything is still streaming, by the core's account and not a timer. */
export function streaming(state: State): boolean {
  return state.lines.some((line) => line.state === "streaming");
}

/** Prompts the person typed that the core never accepted. */
export function unsent(state: State): readonly Line[] {
  return state.lines.filter((line) => line.state === "failed_to_send");
}

/**
 * Messages and tools in the order they happened.
 *
 * A turn is an answer, the tools it called, and another answer. Drawing every
 * message and then every tool — which is what two separate arrays invite —
 * puts the closing summary above the work it is summarising, and a reader has
 * no way to tell which tools belonged to which part.
 *
 * Ordered on arrival rather than by turn so that this stays true whatever
 * shape a turn turns out to have.
 */
export type Entry =
  | { readonly kind: "line"; readonly at: number; readonly line: Line }
  | { readonly kind: "tool"; readonly at: number; readonly tool: ToolRun };

export function timeline(state: State): readonly Entry[] {
  const entries: Entry[] = [
    ...state.lines.map((line): Entry => ({ kind: "line", at: line.at, line })),
    ...state.tools.map((tool): Entry => ({ kind: "tool", at: tool.at, tool })),
  ];
  entries.sort((left, right) => left.at - right.at);
  return entries;
}
