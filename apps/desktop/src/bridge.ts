/**
 * The page's side of the native bridge (contracts/native-bridge.md).
 *
 * The window never talks to the Core directly. It talks to the native side,
 * which owns the Core's process and relays protocol lines both ways. This file
 * turns that relay into the `Transport` `@comodor/client` already speaks, so
 * `CoreClient` runs over it unchanged.
 *
 * Three kinds of message arrive on the one IPC channel:
 *
 * - `line` — a protocol envelope from the Core, already mapped back to this
 *   page's own request ids. Handed to `CoreClient` as is.
 * - `status` — the Core's lifecycle as the native side sees it: starting,
 *   ready, failed, closing. Never a protocol line.
 * - `closed` — the Core connection ended. The line stream ends with it, which
 *   is how `CoreClient` learns its far end has gone.
 *
 * `close()` only detaches this page. Stopping the Core is the native side's
 * decision, never the page's: a `shutdown` the page sends is refused there.
 */

import type { Transport } from "@comodor/client";

/** A failure as the native side classifies it (contracts/core-supervision.md). */
export interface CoreFailure {
  readonly class: string;
  readonly message: string;
}

/** The Core's lifecycle, as the `status` command and channel report it. */
export interface CoreStatus {
  readonly state: string;
  /** For display only: a path that is not UTF-8 loses bytes in it. */
  readonly workspace: string | null;
  /** Which workspace, losslessly; it changes exactly when the folder does. */
  readonly workspace_id: string | null;
  readonly failure: CoreFailure | null;
  readonly restart_count: number;
  readonly restart_limit: number;
  readonly closing: { readonly seconds_remaining: number } | null;
  readonly stop_outcome: "orderly" | "forced" | null;
  readonly core: { readonly name: string; readonly version: string } | null;
  readonly notice: string | null;
}

export type Inbound =
  | { readonly kind: "line"; readonly line: string }
  | { readonly kind: "status"; readonly status: CoreStatus }
  | { readonly kind: "closed"; readonly reason: string };

/** What the page needs from Tauri, injectable so tests need no window. */
export interface NativeApi {
  invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
  /** A channel object the native side writes `Inbound` messages to. */
  channel(onMessage: (message: Inbound) => void): unknown;
}

export interface BridgeConnection extends Transport {
  /** This connection's generation: answers for any other are dropped natively. */
  readonly generation: number;
  /** Why the connection ended, or "" while it is open. */
  readonly closedReason: string;
}

/** Open a new connection: a new generation, a fresh line stream. */
export async function connect(
  api: NativeApi,
  onStatus: (status: CoreStatus) => void,
): Promise<BridgeConnection> {
  const pending: string[] = [];
  let wake: (() => void) | undefined;
  let closedReason = "";

  const end = (reason: string): void => {
    if (closedReason) return;
    closedReason = reason || "closed";
    wake?.();
  };
  const enqueue = (line: string): void => {
    if (closedReason) return;
    pending.push(line);
    wake?.();
  };

  const channel = api.channel((message) => {
    if (message.kind === "line") enqueue(message.line);
    else if (message.kind === "status") onStatus(message.status);
    else end(message.reason);
  });
  const { generation } = await api.invoke<{ generation: number }>("connect", { on: channel });

  return {
    generation,
    get closedReason() {
      return closedReason;
    },

    async *lines(): AsyncIterable<string> {
      for (;;) {
        const next = pending.shift();
        if (next !== undefined) {
          yield next;
          continue;
        }
        if (closedReason) return;
        await new Promise<void>((resolve) => {
          wake = resolve;
        });
        wake = undefined;
      }
    },

    write(line: string): void {
      if (closedReason) throw new Error(closedReason);
      api.invoke("send_line", { generation, line }).catch((problem: unknown) => {
        // The native side refused the line, so the Core never saw it. The
        // request's own answer is an error, delivered here so the caller is
        // told at once rather than left waiting for a reply that will never
        // come. It is this page's own message, never one claimed for the Core.
        enqueue(refusal(line, String(problem)));
      });
    },

    close(): void {
      end("closed by this page");
    },
  };
}

/** An error answer for a refused request, keyed on that request's own id. */
function refusal(line: string, reason: string): string {
  let id: unknown = null;
  try {
    id = (JSON.parse(line) as Record<string, unknown>)["id"] ?? null;
  } catch {
    id = null;
  }
  return JSON.stringify({
    version: 2,
    type: "error",
    id,
    error: { code: "not_allowed", message: reason },
  });
}
