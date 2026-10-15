/**
 * What the Core panel shows (data-model §5; FR-008, FR-028): only values the
 * native side or the Core reported for the current Core. Session values count
 * only while they belong to the current client and the current workspace
 * (`workspace_id`); the handshake only for the current client. Nothing is
 * computed, guessed or carried from an earlier Core: unreported is `null`,
 * which the panel says as "not reported yet".
 */

import type { CoreClient } from "@comodor/client";

import type { CoreStatus } from "../bridge.ts";
import type { SharedSession } from "./session-store.ts";

export interface CoreReport {
  readonly state: string;
  /** As the Core reported it; until then, the folder the native side started it in. */
  readonly workspace: string | null;
  readonly core: string | null;
  readonly protocolVersion: number | null;
  readonly provider: string | null;
  readonly model: string | null;
  readonly configured: boolean | null;
  readonly restarts: { readonly count: number; readonly limit: number };
  readonly failure: { readonly class: string; readonly message: string } | null;
}

/** The session's values, if they were reported for this client and this workspace. */
export function currentSession(status: CoreStatus, client: CoreClient | null,
                               session: SharedSession | null): SharedSession | null {
  if (session === null || client === null) return null;
  // Only while this Core runs: a restart or a stop clears them at once.
  if (status.state !== "ready" && status.state !== "checking") return null;
  if (session.client !== client || session.workspaceId !== status.workspace_id) return null;
  // A status naming another Core (a restart) clears them until it reports.
  if (session.restartCount !== status.restart_count) return null;
  return session;
}

export function coreReport(status: CoreStatus, client: CoreClient | null,
                           session: SharedSession | null): CoreReport {
  const live = currentSession(status, client, session);
  const running = status.state === "ready" || status.state === "checking";
  // The handshake is the client's: it counts only while that client is this Core's.
  const handshake = live !== null ? live.client.handshake : undefined;
  const peer = handshake?.core ?? (running ? status.core : null);
  return {
    state: status.state,
    workspace: live?.workspace ?? status.workspace,
    core: peer ? `${peer.name} ${peer.version}` : null,
    protocolVersion: handshake?.protocol_version ?? null,
    provider: live?.model?.provider ?? null,
    model: live?.model?.model ?? null,
    configured: live?.model ? live.model.configured : null,
    restarts: { count: status.restart_count, limit: status.restart_limit },
    failure: status.state === "failed" ? status.failure : null,
  };
}
