/**
 * One session, while the Core is ready: the status strip, the conversation,
 * whatever is waiting on the person, the mode, and the composer.
 */

import type { CoreClient } from "@comodor/client";
import { presented, type State } from "@comodor/session";

import type { CoreStatus } from "../bridge.ts";
import { type Kept, useSession } from "../state.ts";
import { Composer } from "./Composer.tsx";
import { Conversation } from "./Conversation.tsx";
import { FormCard } from "./FormCard.tsx";
import { ModeControl } from "./ModeControl.tsx";
import { PermissionCard } from "./PermissionCard.tsx";
import { SetupNotice } from "./SetupNotice.tsx";
import { StatusStrip } from "./StatusStrip.tsx";

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

export function SessionView({ client, kept, status, onCheckAgain }: {
  client: CoreClient;
  kept: Kept;
  status: CoreStatus;
  onCheckAgain: () => void;
}) {
  const session = useSession(client, kept);
  const { state } = session;
  const waiting = presented(state);
  // What answers, as the Core said at connect and since (`model.changed`).
  const model = state.model ?? null;
  // As the Core reports it: an unconfigured provider cannot answer (R11).
  const unconfigured = model !== null && model.configured === false;
  return (
    <>
      <StatusStrip status={status} model={model} />
      {!state.session
        ? <p className="quiet">Opening the session…</p>
        : (
          <div className="session" data-testid="session">
            <ModeControl intent={session.intent} onChoose={session.chooseMode} />
            {unconfigured && <SetupNotice onCheckAgain={onCheckAgain} />}
            {session.recovery.map((note) => (
              <p key={note} className="recovery" data-testid="recovery">{note}</p>
            ))}
            <Delegates state={state} />
            <Conversation state={state} />
            {waiting?.kind === "question" && (
              <FormCard key={waiting.id} interaction={waiting}
                        onAnswer={(params) => session.decide("question.answer", params)} />
            )}
            {waiting?.kind === "permission" && (
              <PermissionCard key={waiting.id} interaction={waiting}
                              onReply={(choice) => session.decide("permission.reply", { choice })} />
            )}
            <Composer busy={state.session.busy} ready={state.connection.kind === "ready" && !unconfigured}
                      onSend={session.send} onCancel={session.cancel} />
          </div>
        )}
    </>
  );
}
