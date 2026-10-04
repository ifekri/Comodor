/**
 * One session, while the Core is ready: the status strip, the conversation,
 * whatever is waiting on the person, the mode, and the composer.
 */

import type { CoreClient } from "@comodor/client";
import { presented } from "@comodor/session";

import type { CoreStatus } from "../bridge.ts";
import { type Kept, useSession } from "../state.ts";
import { Composer } from "./Composer.tsx";
import { Conversation } from "./Conversation.tsx";
import { FormCard } from "./FormCard.tsx";
import { ModeControl } from "./ModeControl.tsx";
import { PermissionCard } from "./PermissionCard.tsx";
import { StatusStrip } from "./StatusStrip.tsx";

export function SessionView({ client, kept, status }: {
  client: CoreClient;
  kept: Kept;
  status: CoreStatus;
}) {
  const session = useSession(client, kept);
  const { state } = session;
  const waiting = presented(state);
  // What answers, as the Core said at connect and since (`model.changed`).
  const model = state.model ?? null;
  return (
    <>
      <StatusStrip status={status} model={model} />
      {!state.session
        ? <p className="quiet">Opening the session…</p>
        : (
          <div className="session" data-testid="session">
            <ModeControl intent={session.intent} onChoose={session.chooseMode} />
            <Conversation state={state} />
            {waiting?.kind === "question" && (
              <FormCard key={waiting.id} interaction={waiting}
                        onAnswer={(params) => session.decide("question.answer", params)} />
            )}
            {waiting?.kind === "permission" && (
              <PermissionCard key={waiting.id} interaction={waiting}
                              onReply={(choice) => session.decide("permission.reply", { choice })} />
            )}
            <Composer busy={state.session.busy} ready={state.connection.kind === "ready"}
                      onSend={session.send} onCancel={session.cancel} />
          </div>
        )}
    </>
  );
}
