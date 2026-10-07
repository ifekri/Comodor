/**
 * The window's commands, from `@comodor/commands`: each action is one
 * command, reached the same way by its button and by its key.
 */

import { CommandRegistry } from "@comodor/commands";

export const COMMAND_IDS = {
  send: "conversation.send",
  cancel: "conversation.cancel",
} as const;

export interface ConversationContext {
  readonly [key: string]: unknown;
  readonly send: () => void;
  readonly cancel: () => void;
  readonly busy: boolean;
  /** Whether the session can take a prompt now: not while it is being read. */
  readonly ready: boolean;
  /** Whether a cancel can reach the Core now: not while it is being checked. */
  readonly cancellable: boolean;
}

export const commands = new CommandRegistry<ConversationContext>()
  .add(
    {
      id: COMMAND_IDS.send,
      title: "Send",
      group: "Conversation",
      // A prompt sent while the session is being read would be overwritten
      // by the snapshot that answers it; the draft waits instead.
      enabled: (context) => context.ready,
      run: (context) => context.send(),
    },
    {
      id: COMMAND_IDS.cancel,
      title: "Cancel",
      group: "Conversation",
      keywords: ["stop", "interrupt"],
      enabled: (context) => context.busy && context.cancellable,
      run: (context) => context.cancel(),
    },
  )
  .bind(
    { key: "enter", command: COMMAND_IDS.send, hint: "Enter send" },
    { key: "escape", command: COMMAND_IDS.cancel, hint: "Esc cancel" },
  );

/** The registry's name for a key event, or none. Shift+Enter is a newline. */
export function keyName(event: { key: string; shiftKey: boolean; ctrlKey: boolean;
                                  altKey: boolean; metaKey: boolean }): string | undefined {
  if (event.ctrlKey || event.altKey || event.metaKey) return undefined;
  if (event.key === "Enter" && !event.shiftKey) return "enter";
  if (event.key === "Escape") return "escape";
  return undefined;
}
