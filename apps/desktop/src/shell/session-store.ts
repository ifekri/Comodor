/**
 * The open session, as the shell reads it. `SessionView` owns the session
 * (D1's `useSession`) and publishes what the shell's status bar, commands and
 * Core panel need; nothing is kept once the session view goes, so a new Core
 * or a new client starts from nothing (FR-028).
 */

import type { CoreClient } from "@comodor/client";
import type { Mode } from "@comodor/modes";
import type { Delegate, ModeIntent, Task } from "@comodor/session";

import type { ModelInfo } from "../view/StatusStrip.tsx";

/** What the composer offers the shell: its draft's presence and its Send. */
export interface ComposerHandle {
  readonly hasText: boolean;
  /** Exactly what the Send button does. */
  send(): void;
}

export interface SharedSession {
  /** The client these values came through; a new client means a new Core. */
  readonly client: CoreClient;
  /** The workspace (its native id) these values were reported for. */
  readonly workspaceId: string | null;
  /** The restart count of the Core these values came from: another count is another Core. */
  readonly restartCount: number;
  /** As the Core reported it (`model.get`, `model.changed`); null until then. */
  readonly model: ModelInfo | null;
  /** As the Core reported it (`workspace.get`); null until then. */
  readonly workspace: string | null;
  /** D1's gate: nothing may reach the Core while it holds. */
  readonly gated: boolean;
  readonly busy: boolean;
  readonly intent: ModeIntent;
  /** Whether a session is shown (opened and read). */
  readonly shown: boolean;
  /** The open session's id, as the Core reported it; null until a session is shown. */
  readonly sessionId: string | null;
  /** The first message the person sent in this session, as the conversation holds it. */
  readonly firstMessage: string | null;
  /** How many conversation lines and tool runs the session holds: none is an empty conversation. */
  readonly entries: number;
  /** The Core's task list for this session, whole and read-only. */
  readonly tasks: readonly Task[];
  /** The Core's background delegates for this session, read-only. */
  readonly delegates: readonly Delegate[];
  readonly composer: () => ComposerHandle | null;
  cancel(): void;
  chooseMode(mode: Mode): void;
}

export class SessionStore {
  private value: SharedSession | null = null;
  private readonly listeners = new Set<() => void>();

  get = (): SharedSession | null => this.value;

  set(value: SharedSession | null): void {
    if (value === this.value) return;
    this.value = value;
    for (const listener of this.listeners) listener();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
}
