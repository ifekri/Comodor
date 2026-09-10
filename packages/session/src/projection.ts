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

import type { EventName, Mode, ModelResult, Session } from "@comodor/protocol";

/** Which provider and model answer, as the core reports them. */
export type ModelInfo = ModelResult;

/**
 * One usage report. Every field is optional because the core reports only
 * what the provider measured: a local model has no honest cost, and a client
 * shows nothing there rather than a guessed zero.
 */
export interface UsageInfo {
  readonly contextUsed?: number | undefined;
  readonly contextLimit?: number | undefined;
  readonly fill?: number | undefined;
  readonly inputTokens?: number | undefined;
  readonly outputTokens?: number | undefined;
  readonly costUsd?: number | undefined;
}

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

/**
 * How much of one tool's streamed output the projection keeps.
 *
 * The same number the core's journal keeps, and for the same reason: a
 * command that prints for a minute must not grow a client's memory for a
 * minute per call. The tail is kept because the end of a command's output is
 * the part that says how it went, and the flag says the shortened transcript
 * is shortened rather than letting it pass for all there was. A resync then
 * converges: both sides hold the same last 64,000 characters.
 */
export const OUTPUT_CAP = 64_000;

/** The task states the `todo_write` tool owns. No others exist. */
export type TaskState = "pending" | "active" | "done" | "blocked";

/**
 * One item of the agent's own plan.
 *
 * No id, deliberately: the tool replaces the whole list on every update, and
 * an index is not an identity across a replacement. Tasks are read-only
 * presentation — nothing a client can do to one needs to name it.
 */
export interface Task {
  readonly text: string;
  readonly state: TaskState;
}

/**
 * Where one background delegate has got to.
 *
 * `running` and `stopping` are live; the other four are terminal and a
 * delegate never comes back from one. `lost` is the honest state of a
 * delegate that was running when the core's process died — after a reload it
 * must not look like work still in flight.
 */
export type DelegateState =
  | "running" | "stopping"
  | "done" | "failed" | "stopped" | "lost";

/** One background delegate, as the core last described it. */
export interface Delegate {
  readonly id: string;
  readonly label: string;
  readonly state: DelegateState;
  readonly steps: number;
  readonly toolCalls: number;
  readonly tokens: number;
  /** Seconds, as of this record. Terminal records: the final count. */
  readonly elapsed: number;
  /** The core's epoch seconds, so a client can tick a running one's clock. */
  readonly startedAt: number;
  readonly error?: string | undefined;
}

export type Connection =
  | { readonly kind: "starting" }
  | { readonly kind: "ready" }
  | { readonly kind: "resynchronising" }
  | { readonly kind: "lost"; readonly reason: string };

/** Which sort of thing is waiting on the person. */
export type InteractionKind = "question" | "permission";

/**
 * Where an interaction has got to, on the client's side of it.
 *
 * `waiting` is the core's: something is asking and nothing has been said yet.
 * The other two are the client's own, and exist so a decision cannot be sent
 * twice — `submitting` while a reply is in flight, `failed` when the core
 * refused it. A failure leaves the interaction in place rather than removing
 * it, because the core is still waiting and a card that vanished on an error
 * is a card nobody can retry.
 */
export type InteractionState = "waiting" | "submitting" | "failed";

export interface Interaction {
  readonly kind: InteractionKind;
  /** The core's request id, which is what a reply is keyed on. */
  readonly id: string;
  /** Arrival order, so two waiting at once present in a stable order. */
  readonly at: number;
  /** The request as the core sent it. Never interpreted here. */
  readonly request: Record<string, unknown>;
  readonly state: InteractionState;
  /** Why a reply was refused. Present only with `failed`. */
  readonly error?: string | undefined;
}

export interface State {
  readonly connection: Connection;
  readonly session?: Session | undefined;
  /**
   * What answers this session, as the core last said it — provider, model,
   * and whether it could respond right now. Populated from `model.get` at
   * connect and kept current by `model.changed`; absent only on a core too
   * old to answer, where the header shows nothing rather than a guess.
   */
  readonly model?: ModelInfo | undefined;
  readonly lines: readonly Line[];
  readonly tools: readonly ToolRun[];
  /**
   * The agent's task list, whole. Every `tasks.updated` replaces it — the
   * tool's own semantics — so a task the model removed is gone here too.
   */
  readonly tasks: readonly Task[];
  /**
   * Every background delegate the core has described, in the order they were
   * first announced. Terminal records stay: the panel answers "what happened
   * to those three background tasks?", and a `lost` one that vanished would
   * look like a delegate that never existed.
   */
  readonly delegates: readonly Delegate[];
  /**
   * The latest usage report the core sent: how full the context is and what
   * the conversation has cost. Whole-report replacement — the numbers
   * describe a moment, and merging two moments would show a fill and a cost
   * that were never true together. Absent on a core too old to send it.
   */
  readonly usage?: UsageInfo | undefined;
  /** The most recent notification, shown until the next one replaces it. */
  readonly notice?: { level: string; text: string } | undefined;
  /**
   * Everything waiting on the person, oldest first.
   *
   * A list rather than one slot per kind, because two can be live at once: a
   * batch of read-only tools runs in parallel and each may ask a question, and
   * a delegate shares its parent's bus. One slot would strand whichever
   * arrived second, and a stranded prompt is a tool that looks hung.
   */
  readonly interactions: readonly Interaction[];
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
  tasks: [],
  delegates: [],
  interactions: [],
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
    reasoning?: string; status: string; started_seq?: number;
  }>;
  tools: Array<{
    call_id: string; turn_id: string; name: string; summary?: string;
    state: string; output?: string; output_truncated?: boolean;
    error?: string; elapsed_ms?: number; started_seq?: number;
  }>;
  /** The agent's task list, whole. Absent from a core too old to keep one. */
  tasks?: Array<{ text: string; state: string }>;
  /** Every background delegate, terminal ones included. */
  delegates?: Array<{
    id: string; label: string; state: string; steps: number;
    tool_calls: number; tokens: number; elapsed: number;
    started_at: number; error?: string;
  }>;
  /** The first of each kind, for a snapshot from a core that carries one. */
  question?: Record<string, unknown>;
  permission?: Record<string, unknown>;
  /** Everything waiting, oldest first. Preferred over the two above. */
  interactions?: Array<{
    kind: InteractionKind;
    question?: Record<string, unknown>;
    permission?: Record<string, unknown>;
  }>;
  /** The latest usage report, when the core has sent one. */
  usage?: Record<string, unknown> | undefined;
}

export type Action =
  | { type: "connected"; session: Session }
  /** What answers: the `model.get` answer at connect, from the core. */
  | { type: "modelInfo"; model: ModelInfo }
  | { type: "resynchronising" }
  | { type: "lost"; reason: string }
  /** The person's prompt, before the core has accepted it. */
  | { type: "sending"; localId: string; text: string }
  | { type: "accepted"; localId: string; turnId: string }
  | { type: "rejected"; localId: string; reason: string }
  | { type: "retrying"; localId: string }
  /** A decision is on its way to the core. At most one per interaction. */
  | { type: "submitting"; id: string }
  /** The core refused it. The interaction stays, and stays answerable. */
  | { type: "submitFailed"; id: string; reason: string }
  | { type: "snapshot"; snapshot: Snapshot }
  /**
   * A snapshot of a *different* session — the user opened another
   * conversation. `revision` is per-session, so the staleness guard has no
   * meaning across the switch: the new session's snapshot replaces the
   * projection whole, whatever number it carries.
   */
  | { type: "switched"; snapshot: Snapshot }
  | { type: "event"; name: EventName; params: Record<string, unknown>;
      seq: number };

export function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "connected":
      return { ...state, connection: { kind: "ready" }, session: action.session };

    case "modelInfo":
      return { ...state, model: action.model };

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

    case "submitting":
      // Marked before the reply is sent, not after. Two presses inside one
      // round trip are otherwise two replies, and a permission granted twice
      // is not a harmless duplicate — the second arrives for a request the
      // core has already closed and is refused, which reads as a broken
      // interface rather than as the no-op it was.
      return editInteraction(state, action.id, (interaction) =>
        interaction.state === "submitting"
          ? interaction
          : { ...interaction, state: "submitting", error: undefined });

    case "submitFailed":
      // Still waiting, still answerable. The core did not take the decision,
      // so removing the card would strand the request it is still holding.
      return editInteraction(state, action.id, (interaction) =>
        interaction.state === "submitting"
          ? { ...interaction, state: "failed", error: action.reason }
          : interaction);

    case "snapshot":
      return applySnapshot(state, action.snapshot);

    case "switched":
      // The staleness guard is scoped to a session's own sequence: a snapshot
      // of another session is not older state, it is the whole truth of the
      // one now on screen. Applying it through `applySnapshot` would drop any
      // reopened session whose revision is smaller than the one being left.
      return applySnapshot({ ...initial, connection: state.connection },
                           action.snapshot);

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

  // One ordering domain, owned by the core.
  //
  // Every item carries the session sequence at which it entered the timeline,
  // so messages and tools merge into the order the live stream had. Mapping
  // the two arrays in turn — every message, then every tool — looks fine on a
  // snapshot of one short turn and rebuilds every longer session wrong: an
  // answer, the tool it called, and the summary of that tool would come back
  // as both answers followed by the tool between them.
  const placed: Array<{ startedSeq: number; line?: Line; tool?: ToolRun }> = [
    ...snapshot.messages.map((message) => ({
      startedSeq: message.started_seq ?? 0,
      line: {
        id: message.message_id,
        turnId: message.turn_id,
        at: 0,
        speaker: message.role === "user" ? "you" as const : "comodor" as const,
        text: message.text,
        reasoning: message.reasoning ?? "",
        state: messageState(message.status),
      },
    })),
    ...snapshot.tools.map((tool) => ({
      startedSeq: tool.started_seq ?? 0,
      tool: {
        id: tool.call_id,
        turnId: tool.turn_id,
        at: 0,
        name: tool.name,
        summary: tool.summary ?? "",
        state: toolState(tool.state),
        output: tool.output ?? "",
        outputTruncated: Boolean(tool.output_truncated),
        error: tool.error,
        elapsedMs: tool.elapsed_ms,
      },
    })),
  ];
  // Stable, so an equal sequence keeps the person's prompt ahead of the answer
  // to it and a message ahead of a tool that started on the same number.
  placed.sort((left, right) => left.startedSeq - right.startedSeq);

  const lines: Line[] = [];
  const tools: ToolRun[] = [];
  let at = 0;
  for (const entry of placed) {
    at += 1;
    if (entry.line) lines.push({ ...entry.line, at });
    else if (entry.tool) tools.push({ ...entry.tool, at });
  }

  return {
    ...state,
    connection: { kind: "ready" },
    session: snapshot.session,
    lines,
    tools,
    tasks: restoredTasks(snapshot),
    delegates: restoredDelegates(snapshot),
    interactions: restoredInteractions(snapshot, at),
    usage: restoredUsage(snapshot),
    revision: snapshot.revision,
    arrivals: at,
    gap: false,
  };
}

/** The usage a snapshot carries, or none — mapped field by field. */
function restoredUsage(snapshot: Snapshot): UsageInfo | undefined {
  const raw = snapshot.usage;
  if (!raw) return undefined;
  return usageOf(raw);
}

/** One report's fields, converted; absent fields stay absent, not zero. */
function usageOf(params: Record<string, unknown>): UsageInfo {
  const number = (value: unknown): number | undefined =>
    typeof value === "number" && Number.isFinite(value) ? value : undefined;
  return {
    contextUsed: number(params["context_used"]),
    contextLimit: number(params["context_limit"]),
    fill: number(params["fill"]),
    inputTokens: number(params["input_tokens"]),
    outputTokens: number(params["output_tokens"]),
    costUsd: number(params["cost_usd"]),
  };
}

/**
 * The task list a snapshot carries, sanitized the way the tool's own parsing
 * does: a state outside the four words is `pending`, and an entry with no
 * text is not a task.
 */
function restoredTasks(snapshot: Snapshot): Task[] {
  if (!Array.isArray(snapshot.tasks)) return [];
  const built: Task[] = [];
  for (const entry of snapshot.tasks) {
    if (!entry || typeof entry !== "object") continue;
    const text = String(entry.text ?? "");
    if (!text) continue;
    built.push({ text, state: taskState(String(entry.state ?? "")) });
  }
  return built;
}

/**
 * The delegates a snapshot carries, whole records in the order listed.
 *
 * No forward-only guard here, unlike the event fold: a snapshot *is* the
 * core's current account, revision-checked as a whole, so what it says
 * replaces what was held even where an event could not.
 */
function restoredDelegates(snapshot: Snapshot): Delegate[] {
  if (!Array.isArray(snapshot.delegates)) return [];
  const built: Delegate[] = [];
  for (const entry of snapshot.delegates) {
    const delegate = delegateOf(entry);
    if (delegate) built.push(delegate);
  }
  return built;
}

/** One wire record as the client holds it, or nothing when it has no id. */
function delegateOf(entry: unknown): Delegate | undefined {
  if (!entry || typeof entry !== "object") return undefined;
  const record = entry as Record<string, unknown>;
  const id = String(record["id"] ?? "");
  if (!id) return undefined;
  const error = String(record["error"] ?? "");
  return {
    id,
    label: String(record["label"] ?? ""),
    state: delegateState(String(record["state"] ?? "")),
    steps: Number(record["steps"] ?? 0),
    toolCalls: Number(record["tool_calls"] ?? 0),
    tokens: Number(record["tokens"] ?? 0),
    elapsed: Number(record["elapsed"] ?? 0),
    startedAt: Number(record["started_at"] ?? 0),
    error: error || undefined,
  };
}

function taskState(state: string): TaskState {
  return state === "active" || state === "done" || state === "blocked"
    ? state
    : "pending";
}

function delegateState(state: string): DelegateState {
  return state === "stopping" || state === "done" || state === "failed"
    || state === "stopped" || state === "lost"
    ? state
    // Fail-safe the way an unknown message status maps to `streaming`: a word
    // from a newer core is shown as work in flight rather than dropped, since
    // hiding a delegate that exists is the worse mistake. Stopping it is
    // harmless — the core answers honestly when there was nothing to stop.
    : "running";
}

/**
 * What a snapshot says is waiting, as the list this projection keeps.
 *
 * A core that carries the list is read from it. One that carries only the two
 * singular fields — the shape before the list existed — still restores what it
 * can, permission first, because that is the one blocking a tool that is
 * already running.
 *
 * Restored as `waiting` rather than as whatever the client was doing before:
 * a snapshot is the core's account, and a reply that was in flight when the
 * connection was repaired is not in flight any more.
 */
function restoredInteractions(snapshot: Snapshot, after: number): Interaction[] {
  const found: Array<{ kind: InteractionKind;
                       request: Record<string, unknown> | undefined }> = [];
  if (snapshot.interactions) {
    for (const entry of snapshot.interactions) {
      found.push({ kind: entry.kind,
                   request: entry.kind === "question" ? entry.question
                                                      : entry.permission });
    }
  } else {
    found.push({ kind: "permission", request: snapshot.permission });
    found.push({ kind: "question", request: snapshot.question });
  }

  const built: Interaction[] = [];
  for (const entry of found) {
    const request = entry.request;
    if (!request) continue;
    const id = String(request["id"] ?? "");
    if (!id) continue;
    built.push({ kind: entry.kind, id, at: (after += 1), request,
                 state: "waiting" });
  }
  return built;
}

function messageState(status: string): MessageState {
  // `streaming` is what the core says about a message it has started and not
  // finished. Treating it as anything else stops a client listening to an
  // answer that is still arriving.
  if (status === "streaming") return "streaming";
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


    case "model.changed": {
      // The core's own announcement after `model.set`, whichever client asked.
      // A header painted from local state would claim a switch a refusal left
      // unmade; only this event moves it.
      return {
        ...state,
        model: {
          provider: String(params["provider"] ?? ""),
          model: String(params["model"] ?? ""),
          configured: Boolean(params["configured"]),
        },
      };
    }

    case "usage.updated":
      return { ...state, usage: usageOf(params) };

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
      return editTool(state, callId, (tool) => appendOutput(tool, text));

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
      return raise(state, "question", params);

    case "question.resolved":
      return settle(state, params);

    case "permission.requested":
      return raise(state, "permission", params);

    case "permission.resolved":
      return settle(state, params);

    case "notification.created":
      return {
        ...state,
        notice: { level: String(params["level"] ?? "info"), text },
      };

    case "tasks.updated": {
      // Replacement, never addition — the semantics the `todo_write` tool
      // itself has: it sends the complete list every time. Merging would keep
      // a task the model removed and reorder one the model reordered, and a
      // plan panel that disagrees with the plan is worse than none.
      const raw = params["tasks"];
      if (!Array.isArray(raw)) return state;
      const tasks: Task[] = [];
      for (const entry of raw) {
        if (!entry || typeof entry !== "object") continue;
        const item = entry as Record<string, unknown>;
        const taskText = String(item["text"] ?? "");
        if (!taskText) continue;
        tasks.push({ text: taskText,
                     state: taskState(String(item["state"] ?? "")) });
      }
      return { ...state, tasks };
    }

    case "delegate.updated": {
      const delegate = delegateOf(params["delegate"]);
      return delegate ? foldDelegate(state, delegate) : state;
    }

    default:
      // An event this client does not use. Ignoring it by name is how a newer
      // core stays compatible with an older client.
      return state;
  }
}

/**
 * One delegate record, folded forward-only.
 *
 * Replaced whole rather than merged field by field: half-merging two records
 * could pair a new state with an old error, a sentence the core never said.
 * And never backwards — a late `running` behind a `stopping`, or anything
 * behind a terminal state, is dropped. The core's manager announces
 * monotonically; this is the same rule kept on the client, because a
 * snapshot-and-stream race is exactly where a late event could otherwise
 * re-describe a stopped delegate as alive.
 */
const DELEGATE_PROGRESS: Record<string, number> = {
  running: 0, stopping: 1, done: 2, failed: 2, stopped: 2, lost: 2,
};

const DELEGATE_TERMINAL: readonly DelegateState[] =
  ["done", "failed", "stopped", "lost"];

function foldDelegate(state: State, delegate: Delegate): State {
  const at = state.delegates.findIndex((each) => each.id === delegate.id);
  if (at < 0) {
    return { ...state, delegates: [...state.delegates, delegate] };
  }
  const held = state.delegates[at] as Delegate;
  if (DELEGATE_TERMINAL.includes(held.state)) return state;
  if ((DELEGATE_PROGRESS[delegate.state] ?? 0)
      < (DELEGATE_PROGRESS[held.state] ?? -1)) return state;
  const delegates = [...state.delegates];
  delegates[at] = delegate;
  return { ...state, delegates };
}

/**
 * Output appended, bounded the way the core's journal bounds its own copy:
 * the tail kept, the flag set, and a client that streamed a megabyte holds
 * the same last 64,000 characters a resync would have given it.
 */
function appendOutput(tool: ToolRun, text: string): ToolRun {
  let output = tool.output + text;
  let truncated = tool.outputTruncated;
  if (output.length > OUTPUT_CAP) {
    output = output.slice(-OUTPUT_CAP);
    truncated = true;
  }
  return { ...tool, output, outputTruncated: truncated };
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

/**
 * Something is now waiting on the person.
 *
 * Keyed by the core's request id, so a redelivery of the same request — a
 * resync, an event that arrived twice — replaces the entry rather than adding
 * a second card nobody can tell apart. A *different* request is added
 * alongside: two can genuinely be live at once, and dropping the first to make
 * room for the second would strand a prompt the core is still blocked on.
 */
function raise(state: State, kind: InteractionKind,
               request: Record<string, unknown>): State {
  const id = String(request["id"] ?? "");
  if (!id) return state;
  const held = state.interactions.find((each) => each.id === id);
  if (held) {
    return {
      ...state,
      interactions: state.interactions.map((each) => each.id === id
        // The request the core now reports, and a clean slate for answering
        // it: whatever was in flight before belongs to a state that is gone.
        ? { ...each, kind, request, state: "waiting", error: undefined }
        : each),
    };
  }
  return {
    ...state,
    interactions: [...state.interactions, {
      kind, id, at: state.arrivals + 1, request, state: "waiting",
    }],
  };
}

/** Something stopped waiting. Removed by id, so a second request survives. */
function settle(state: State, params: Record<string, unknown>): State {
  const id = String(params["id"] ?? "");
  if (!id) return state;
  const left = state.interactions.filter((each) => each.id !== id);
  return left.length === state.interactions.length
    ? state
    : { ...state, interactions: left };
}

function editInteraction(state: State, id: string,
                         change: (each: Interaction) => Interaction): State {
  if (!id) return state;
  const at = state.interactions.findIndex((each) => each.id === id);
  if (at < 0) return state;
  const interactions = [...state.interactions];
  interactions[at] = change(interactions[at] as Interaction);
  return { ...state, interactions };
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

// --------------------------------------------------------------------------- //
// reading the workbench
// --------------------------------------------------------------------------- //

/**
 * Whether this delegate may be asked to stop.
 *
 * Renderer-independent on purpose: which states a control applies to is a
 * fact about the lifecycle, not about a terminal, and a desktop client must
 * not work it out again slightly differently. `stopping` is not stoppable —
 * the stop is already asked for — and neither is anything terminal.
 */
export function stoppable(delegate: Delegate): boolean {
  return delegate.state === "running";
}

/** The delegates still in flight, by the core's account. */
export function runningDelegates(state: State): readonly Delegate[] {
  return state.delegates.filter((delegate) =>
    delegate.state === "running" || delegate.state === "stopping");
}

/** How many tasks the agent has finished, for a "2 of 5" that cannot drift. */
export function tasksDone(tasks: readonly Task[]): number {
  return tasks.filter((task) => task.state === "done").length;
}

// --------------------------------------------------------------------------- //
// what is waiting on the person
// --------------------------------------------------------------------------- //

/**
 * The interaction to present, or nothing.
 *
 * Oldest first, which is the order the core lists them in and the one a person
 * expects: what has been waiting longest is what is shown. Presenting the
 * newest instead would let a second request hide the first for as long as both
 * were live, and the hidden one is the one that times out.
 */
export function presented(state: State): Interaction | undefined {
  return state.interactions[0];
}

/** The question being presented, if the thing waiting is a question. */
export function presentedQuestion(state: State): Record<string, unknown> | undefined {
  const head = presented(state);
  return head && head.kind === "question" ? head.request : undefined;
}

/** The permission being presented, if the thing waiting is a permission. */
export function presentedPermission(state: State): Record<string, unknown> | undefined {
  const head = presented(state);
  return head && head.kind === "permission" ? head.request : undefined;
}

/** How many things are waiting, for a hint that says "and one more". */
export function waitingCount(state: State): number {
  return state.interactions.length;
}

/**
 * Whether a decision may be sent for this interaction right now.
 *
 * The gate against a double reply, and the reason the state is in the
 * projection rather than in a component: a second Enter, a click while a key
 * is in flight, and a key that arrives after the core resolved it all have to
 * be refused by the same rule rather than by three components each keeping
 * their own idea of whether they had already sent.
 */
export function canSubmit(state: State, id: string): boolean {
  const found = state.interactions.find((each) => each.id === id);
  return found !== undefined && found.state !== "submitting";
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
