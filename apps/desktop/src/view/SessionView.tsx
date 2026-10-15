/**
 * One session, while the Core is ready: the conversation, whatever is waiting
 * on the person, the mode, and the composer. The status strip is the shell's
 * status bar now; this view publishes what the shell shows of the session.
 */

import { useContext, useLayoutEffect, useMemo, useRef } from "react";

import type { CoreClient } from "@comodor/client";
import type { Mode } from "@comodor/modes";
import { presented, type State } from "@comodor/session";

import type { CoreStatus } from "../bridge.ts";
import { type Kept, useSession } from "../state.ts";
import { Composer } from "./Composer.tsx";
import { Conversation } from "./Conversation.tsx";
import { FormCard } from "./FormCard.tsx";
import { ModeControl } from "./ModeControl.tsx";
import { PermissionCard } from "./PermissionCard.tsx";
import { ShellRun } from "../shell/run-context.ts";
import type { ComposerHandle, SessionStore, SharedSession } from "../shell/session-store.ts";
import { SetupNotice } from "./SetupNotice.tsx";

/** Background delegates, in one line: how many, and in which states. */
function Delegates({ state }: { state: State }) {
  if (state.delegates.length === 0) return null;
  const counts = new Map<string, number>();
  for (const delegate of state.delegates) {
    counts.set(delegate.state, (counts.get(delegate.state) ?? 0) + 1);
  }
  const total = state.delegates.length;
  const parts = [...counts].map(([name, count]) => `${count} ${name}`).join(", ");
  return (
    <p className="delegates" data-testid="delegates">
      {total} background {total === 1 ? "task" : "tasks"}: {parts}
    </p>
  );
}

export function SessionView({ client, kept, status, onCheckAgain, store }: {
  client: CoreClient;
  kept: Kept;
  status: CoreStatus;
  onCheckAgain: () => void;
  /** Where the shell reads this session; cleared when the view goes. */
  store?: SessionStore | undefined;
}) {
  const session = useSession(client, kept, status.workspace_id, status.state, status.check_epoch);
  const { state } = session;
  const waiting = presented(state);
  // What answers, as the Core said at connect and since (`model.changed`).
  const model = state.model ?? null;
  // As the Core reports it: an unconfigured provider cannot answer (R11).
  const unconfigured = model !== null && model.configured === false;
  const held = session.gated;
  // Inside the shell a mode button runs the mode's command (FR-010).
  const run = useContext(ShellRun);
  const chooseMode = (mode: Mode) => (run ? run(`mode.${mode}`) : session.chooseMode(mode));
  const composer = useRef<ComposerHandle | null>(null);
  const busy = state.session?.busy ?? false;
  const shown = Boolean(state.session);
  // The workspace this session was opened for: its values belong to it, and
  // a new workspace's are reported by the Core that opens it (FR-028).
  const workspaceId = useRef(status.workspace_id).current;
  const restartCount = useRef(status.restart_count).current;
  const shared = useMemo<SharedSession>(() => ({
    client, workspaceId, restartCount, model, workspace: session.workspace, gated: held, busy, intent: session.intent, shown,
    composer: () => composer.current, cancel: session.cancel, chooseMode: session.chooseMode,
  }), [client, workspaceId, restartCount, model, session.workspace, held, busy, session.intent, shown, session.cancel,
      session.chooseMode]);
  useLayoutEffect(() => {
    store?.set(shared);
  }, [store, shared]);
  // Nothing of this session outlives it: a new Core or client starts empty.
  useLayoutEffect(() => () => store?.set(null), [store]);
  return (
    <>
      {!state.session
        ? state.connection.kind === "lost"
          ? <p className="quiet" data-testid="session-lost">
              The session could not be opened: {state.connection.reason}
            </p>
          : <p className="quiet">Opening the session…</p>
        : (
          <div className="session" data-testid="session">
            <ModeControl intent={session.intent} held={held} onChoose={chooseMode} />
            {state.connection.kind === "lost" && (
              <p className="recovery" data-testid="session-unread">
                The session could not be read again: {state.connection.reason}
              </p>
            )}
            {unconfigured && <SetupNotice onCheckAgain={onCheckAgain} />}
            {session.recovery.map((note) => (
              <p key={note} className="recovery" data-testid="recovery">{note}</p>
            ))}
            <Delegates state={state} />
            <Conversation state={state} />
            {waiting?.kind === "question" && (
              <FormCard key={waiting.id} interaction={waiting} held={held}
                        onAnswer={(params) => session.decide("question.answer", params)} />
            )}
            {waiting?.kind === "permission" && (
              <PermissionCard key={waiting.id} interaction={waiting} held={held}
                              onReply={(choice) => session.decide("permission.reply", { choice })} />
            )}
            <Composer busy={state.session.busy}
                      ready={!held && model?.configured === true}
                      cancellable={!held}
                      onSend={session.send} onCancel={session.cancel} handle={composer} />
          </div>
        )}
    </>
  );
}
