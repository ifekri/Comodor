/**
 * The session, as this window holds it (data-model.md §7).
 *
 * Everything about the conversation is the Core's, projected by the
 * unchanged `@comodor/session` reducer: the client is subscribed, then a
 * session is created (or the stored one reopened after a restart), then its
 * snapshot is taken. A gap in the event sequence is answered with a fresh
 * snapshot. The window adds only presentation and connection facts: which
 * conversation to reopen (`storedId`), and which accepted turn never
 * completed (`unsentTurn`).
 */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import type { CoreClient } from "@comodor/client";
import type { Mode } from "@comodor/modes";
import type { EventName, Session } from "@comodor/protocol";
import {
  beginIntent,
  canSubmit,
  initial,
  intentConfirmed,
  intentDue,
  intentSending,
  type ModeIntent,
  reduce,
  refuseIntent,
  type Snapshot,
  type State,
  wantMode,
} from "@comodor/session";

export interface SessionView {
  readonly state: State;
  readonly intent: ModeIntent;
  /** The person's prompt. */
  send(text: string): void;
  /** Stop whatever the session is doing. */
  cancel(): void;
  /** One decision on the request waiting first. */
  decide(method: "question.answer" | "permission.reply", params: Record<string, unknown>): void;
  /** Aim at a mode; the Core decides. */
  chooseMode(mode: Mode): void;
  /** What the window says about a restart: why the conversation looks as it does. */
  readonly recovery: readonly string[];
  /** The workspace as the Core reports it (`workspace.get`), once known. */
  readonly workspace: string | null;
}

/** What survives a Core restart, and a reload of this window, within one
 * launch (R12). */
export interface Kept {
  /** The stored conversation a new Core reopens. */
  storedId: string | undefined;
  /** The live session of the Core the page last held; a reload finds it. */
  liveId: string | undefined;
  unsentTurn: string | undefined;
  /** The workspace (its native id) the stored conversation belongs to. */
  workspace: string | undefined;
}

const KEPT_KEY = "comodor.kept";
type KeptFields = { -readonly [K in keyof Kept]: Kept[K] };

/**
 * The window's `Kept`, mirrored into `storage` — the window's session
 * storage, which a reload of its content keeps and a new launch does not.
 * Without storage it lives in memory only.
 */
export function keptIn(storage: Storage | undefined): Kept {
  const text = (value: unknown) => (typeof value === "string" ? value : undefined);
  let saved: Record<string, unknown> = {};
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(KEPT_KEY) ?? "{}");
    if (parsed !== null && typeof parsed === "object") saved = parsed as Record<string, unknown>;
  } catch {
    saved = {};
  }
  const fields: KeptFields = {
    storedId: text(saved["storedId"]), liveId: text(saved["liveId"]),
    unsentTurn: text(saved["unsentTurn"]), workspace: text(saved["workspace"]),
  };
  const save = () => {
    try {
      storage?.setItem(KEPT_KEY, JSON.stringify(fields));
    } catch {
      // Kept in memory only, then: a reload starts from the live session.
    }
  };
  const kept = {} as Kept;
  for (const key of Object.keys(fields) as (keyof Kept)[]) {
    Object.defineProperty(kept, key, {
      enumerable: true,
      get: () => fields[key],
      set: (value: string | undefined) => {
        fields[key] = value;
        save();
      },
    });
  }
  return kept;
}

function sessionOf(params: Record<string, unknown>): string | undefined {
  if (typeof params["session_id"] === "string") return params["session_id"];
  const session = params["session"] as Record<string, unknown> | undefined;
  return typeof session?.["id"] === "string" ? session["id"] : undefined;
}

export function useSession(client: CoreClient, kept: Kept, workspace: string | null): SessionView {
  const [state, dispatch] = useReducer(reduce, initial);
  const [intent, setIntent] = useState<ModeIntent>(beginIntent("act"));
  const latest = useRef(state);
  latest.current = state;
  const inFlight = useRef<string | undefined>(undefined);
  const [recovery, setRecovery] = useState<string[]>([]);
  const [coreWorkspace, setCoreWorkspace] = useState<string | null>(null);

  const resync = useCallback(async (id: string, fresh: boolean) => {
    dispatch({ type: "resynchronising" });
    try {
      const answer = await client.call("session.snapshot", { session_id: id });
      const snapshot = answer["snapshot"] as Snapshot;
      dispatch({ type: "snapshot", snapshot });
      // An idle session has no turn a restart could interrupt — one that
      // ended while this page was not listening included.
      if (snapshot.session?.busy === false) kept.unsentTurn = undefined;
      const mode = (snapshot.session?.mode ?? "act") as Mode;
      setIntent((was) => (fresh ? beginIntent(mode) : intentConfirmed(was, mode)));
    } catch (problem) {
      dispatch({ type: "lost", reason: (problem as Error).message });
    }
  }, [client, kept]);

  useEffect(() => {
    let alive = true;
    // Until this connection's first snapshot is applied, events wait: one
    // applied before it would make the snapshot look older than the window
    // and be dropped with it. Replayed after it, the reducer drops those the
    // snapshot already covers.
    let based = false;
    const early: { name: EventName; params: Record<string, unknown>; seq: number }[] = [];
    const handle = (name: EventName, params: Record<string, unknown>, seq: number) => {
      // One window, one session: another session's events are not this one's.
      const owner = sessionOf(params);
      const current = latest.current.session?.id;
      if (owner && current && owner !== current) return;
      dispatch({ type: "event", name, params, seq });
      if (name === "mode.changed") {
        setIntent((was) => intentConfirmed(was, params["mode"] as Mode));
      }
      // The turn is over, however it ended: it is no longer one a restart
      // could have interrupted.
      if (name === "session.updated"
          && (params["session"] as Record<string, unknown> | undefined)?.["busy"] === false) {
        kept.unsentTurn = undefined;
      }
    };
    const stop = client.on((name: EventName, params, seq) => {
      if (!alive) return;
      if (based) handle(name, params, seq);
      else early.push({ name, params, seq });
    });
    let closed = false;
    const unlost = client.onClose((reason) => {
      closed = true;
      if (alive) dispatch({ type: "lost", reason });
    });
    void (async () => {
      try {
        const notes: string[] = [];
        // Another workspace is another conversation: nothing from the last
        // one is reopened in it, or called interrupted there.
        if (kept.workspace !== (workspace ?? undefined)) {
          kept.storedId = undefined;
          kept.liveId = undefined;
          kept.unsentTurn = undefined;
          kept.workspace = workspace ?? undefined;
        }
        // A reload of this window finds its live session in the same Core;
        // a new Core has none until one is opened.
        const live = await client.call("session.list")
          .then((answer) => (answer["sessions"] as Session[] | undefined) ?? [])
          .catch(() => [] as Session[]);
        let session: Session | undefined = live.find((one) => one.id === kept.liveId);
        if (session) {
          // A reload: the same Core, the same conversation.
        } else if (kept.storedId) {
          // After a restart: the stored conversation is reopened. Opening
          // gives a live session with an id of its own; the stored record
          // keeps its id, which is what a later restart opens again.
          session = await client.call("session.open", { session_id: kept.storedId })
            .then((answer) => answer["session"] as Session)
            .catch(() => undefined);
          // A connection that went meanwhile says nothing about what is
          // stored: the next client tries again.
          if (!alive || closed) return;
          if (!session) {
            notes.push("The previous conversation could not be reopened, so a new one was started.");
            kept.storedId = undefined;
          }
          if (kept.unsentTurn !== undefined) {
            notes.push("The answer to your last message was interrupted when the Core stopped. "
                       + "It was not saved, and it was not sent again.");
            kept.unsentTurn = undefined;
          }
        } else {
          // A reload that kept nothing: the Core's live session, if any.
          session = live[0];
          if (session) kept.storedId = session.id;
        }
        if (!session) {
          session = (await client.call("session.create"))["session"] as Session;
          kept.storedId = session.id;
        }
        kept.liveId = session.id;
        if (!alive) return;
        setRecovery(notes);
        dispatch({ type: "connected", session });
        await resync(session.id, true);
        based = true;
        for (const { name, params, seq } of early.splice(0)) handle(name, params, seq);
        if (!alive) return;
        const info = await client.call("model.get");
        if (alive) dispatch({ type: "modelInfo", model: info as never });
        // Where the Core works, as it says (FR-020): its project root, which
        // may differ from the folder it was started in.
        const where = await client.call("workspace.get");
        if (alive && typeof where["path"] === "string") setCoreWorkspace(where["path"]);
      } catch (problem) {
        if (alive) dispatch({ type: "lost", reason: (problem as Error).message });
      }
    })();
    return () => {
      alive = false;
      stop();
      unlost();
    };
  }, [client, kept, workspace, resync]);

  // A hole in the sequence means an event never arrived, and no later event
  // repairs that: the Core is asked for the whole session again.
  useEffect(() => {
    const id = state.session?.id;
    if (state.gap && id) void resync(id, false);
  }, [state.gap, state.session?.id, resync]);

  // One mode request in flight; the current aim is what goes out next.
  useEffect(() => {
    const id = state.session?.id;
    const next = intentDue(intent);
    if (!id || next === undefined) return;
    setIntent((was) => intentSending(was, next));
    void client.call("session.set_mode", { session_id: id, mode: next })
      .catch((problem: unknown) => {
        setIntent((was) => refuseIntent(was, (problem as Error).message));
        dispatch({ type: "event", name: "notification.created", seq: 0,
                   params: { level: "warning", text: (problem as Error).message } });
      });
  }, [client, intent, state.session?.id]);

  const send = useCallback((text: string) => {
    const id = latest.current.session?.id;
    const trimmed = text.trim();
    if (!id || !trimmed) return;
    const localId = `you-${latest.current.arrivals + 1}`;
    dispatch({ type: "sending", localId, text: trimmed });
    client.call("session.send", { session_id: id, text: trimmed })
      .then((answer) => {
        const turnId = String(answer["turn_id"] ?? "");
        kept.unsentTurn = turnId;
        dispatch({ type: "accepted", localId, turnId });
      })
      .catch((problem: unknown) => {
        dispatch({ type: "rejected", localId, reason: (problem as Error).message });
      });
  }, [client, kept]);

  const cancel = useCallback(() => {
    const id = latest.current.session?.id;
    if (id) void client.call("session.cancel", { session_id: id }).catch(() => {});
  }, [client]);

  const decide = useCallback((method: "question.answer" | "permission.reply",
                              params: Record<string, unknown>) => {
    const waiting = latest.current.interactions[0];
    if (!waiting || !canSubmit(latest.current, waiting.id)) return;
    // Two clicks inside one tick both read the projection before it is
    // re-rendered; the latch refuses the second.
    if (inFlight.current === waiting.id) return;
    inFlight.current = waiting.id;
    const id = waiting.id;
    dispatch({ type: "submitting", id });
    client.call(method, { ...params, id }).catch((problem: unknown) => {
      inFlight.current = undefined;
      dispatch({ type: "submitFailed", id, reason: (problem as Error).message });
    });
  }, [client]);

  const chooseMode = useCallback((mode: Mode) => {
    setIntent((was) => wantMode(was, mode));
  }, []);

  return { state, intent, send, cancel, decide, chooseMode, recovery, workspace: coreWorkspace };
}
