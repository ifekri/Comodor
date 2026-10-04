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
}

/** What survives a Core restart within this window (R12). */
export interface Kept {
  storedId: string | undefined;
  unsentTurn: string | undefined;
}

function sessionOf(params: Record<string, unknown>): string | undefined {
  if (typeof params["session_id"] === "string") return params["session_id"];
  const session = params["session"] as Record<string, unknown> | undefined;
  return typeof session?.["id"] === "string" ? session["id"] : undefined;
}

export function useSession(client: CoreClient, kept: Kept): SessionView {
  const [state, dispatch] = useReducer(reduce, initial);
  const [intent, setIntent] = useState<ModeIntent>(beginIntent("act"));
  const latest = useRef(state);
  latest.current = state;
  const inFlight = useRef<string | undefined>(undefined);

  const resync = useCallback(async (id: string, fresh: boolean) => {
    dispatch({ type: "resynchronising" });
    try {
      const answer = await client.call("session.snapshot", { session_id: id });
      const snapshot = answer["snapshot"] as Snapshot;
      dispatch({ type: "snapshot", snapshot });
      const mode = (snapshot.session?.mode ?? "act") as Mode;
      setIntent((was) => (fresh ? beginIntent(mode) : intentConfirmed(was, mode)));
    } catch (problem) {
      dispatch({ type: "lost", reason: (problem as Error).message });
    }
  }, [client]);

  useEffect(() => {
    let alive = true;
    const stop = client.on((name: EventName, params, seq) => {
      if (!alive) return;
      // One window, one session: another session's events are not this one's.
      const owner = sessionOf(params);
      const current = latest.current.session?.id;
      if (owner && current && owner !== current) return;
      dispatch({ type: "event", name, params, seq });
      if (name === "mode.changed") {
        setIntent((was) => intentConfirmed(was, params["mode"] as Mode));
      }
      if (name === "message.completed" && params["turn_id"] === kept.unsentTurn
          && params["status"] === "completed") {
        kept.unsentTurn = undefined;
      }
    });
    const unlost = client.onClose((reason) => {
      if (alive) dispatch({ type: "lost", reason });
    });
    void (async () => {
      try {
        let session: Session;
        if (kept.storedId) {
          session = (await client.call("session.open", { session_id: kept.storedId }))["session"] as Session;
        } else {
          session = (await client.call("session.create"))["session"] as Session;
        }
        if (!alive) return;
        kept.storedId = session.id;
        dispatch({ type: "connected", session });
        await resync(session.id, true);
        if (!alive) return;
        const info = await client.call("model.get");
        if (alive) dispatch({ type: "modelInfo", model: info as never });
      } catch (problem) {
        if (alive) dispatch({ type: "lost", reason: (problem as Error).message });
      }
    })();
    return () => {
      alive = false;
      stop();
      unlost();
    };
  }, [client, kept, resync]);

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

  return { state, intent, send, cancel, decide, chooseMode };
}
