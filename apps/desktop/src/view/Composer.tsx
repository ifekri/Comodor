/**
 * Where the person writes. Send and Cancel are the window's commands: the
 * buttons and the keys run the same two.
 */

import { type KeyboardEvent, type MutableRefObject, type ReactNode, useLayoutEffect, useState } from "react";

import { COMMAND_IDS, commands, type ConversationContext, keyName } from "../commands.ts";
import type { ComposerHandle } from "../shell/session-store.ts";

export function Composer({ busy, ready, cancellable, onSend, onCancel, handle, leading, sendHint, trailing, placeholder }: {
  busy: boolean;
  ready: boolean;
  /** Whether a cancel can reach the Core now: not while it is being checked. */
  cancellable: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
  /** Where the shell finds this composer's draft and its Send (D2 palette). */
  handle?: MutableRefObject<ComposerHandle | null> | undefined;
  /** The shell's controls before Send and after Cancel, in the prompt's footer (D2). */
  leading?: ReactNode;
  /** Shown right after Send: its key, as the shell names it. */
  sendHint?: ReactNode;
  trailing?: ReactNode;
  /** The field's hint; D1's own when none is given. */
  placeholder?: string | undefined;
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
  useLayoutEffect(() => {
    if (!handle) return;
    handle.current = { hasText: draft.trim() !== "", send: context.send };
    return () => {
      handle.current = null;
    };
  });

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const name = keyName(event);
    const command = name === undefined ? undefined : commands.forKey(name);
    if (!command) return;
    event.preventDefault();
    run(command.id);
  };

  return (
    <footer className="composer" data-testid="composer">
      <textarea value={draft} rows={3} placeholder={placeholder ?? "Ask Comodor…"} aria-label="Message"
                onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} />
      <div className="composer-actions">
        {leading}
        <button type="button" className="composer-send" disabled={!ready} onClick={() => run(COMMAND_IDS.send)}>
          <span className="composer-label">{commands.get(COMMAND_IDS.send)?.title}</span>
        </button>
        {sendHint}
        {busy && (
          <button type="button" className="composer-cancel" disabled={!cancellable} onClick={() => run(COMMAND_IDS.cancel)}>
            <span className="composer-label">{commands.get(COMMAND_IDS.cancel)?.title}</span>
          </button>
        )}
        {trailing}
      </div>
    </footer>
  );
}
