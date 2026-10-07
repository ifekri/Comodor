/**
 * Where the person writes. Send and Cancel are the window's commands: the
 * buttons and the keys run the same two.
 */

import { type KeyboardEvent, useState } from "react";

import { COMMAND_IDS, commands, type ConversationContext, keyName } from "../commands.ts";

export function Composer({ busy, ready, cancellable, onSend, onCancel }: {
  busy: boolean;
  ready: boolean;
  /** Whether a cancel can reach the Core now: not while it is being checked. */
  cancellable: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState("");
  const context: ConversationContext = {
    busy,
    ready,
    cancellable,
    send: () => {
      if (draft.trim() === "") return;
      onSend(draft);
      setDraft("");
    },
    cancel: onCancel,
  };
  const run = (id: string) => void commands.run(id, context);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const name = keyName(event);
    const command = name === undefined ? undefined : commands.forKey(name);
    if (!command) return;
    event.preventDefault();
    run(command.id);
  };

  return (
    <footer className="composer" data-testid="composer">
      <textarea value={draft} rows={3} placeholder="Ask Comodor…" aria-label="Message"
                onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} />
      <div className="composer-actions">
        <button type="button" disabled={!ready} onClick={() => run(COMMAND_IDS.send)}>
          {commands.get(COMMAND_IDS.send)?.title}
        </button>
        {busy && (
          <button type="button" disabled={!cancellable} onClick={() => run(COMMAND_IDS.cancel)}>
            {commands.get(COMMAND_IDS.cancel)?.title}
          </button>
        )}
      </div>
    </footer>
  );
}
