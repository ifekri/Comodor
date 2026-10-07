/**
 * The real native API: Tauri's `invoke` and IPC `Channel`.
 *
 * The only file that imports Tauri. Everything else takes a `NativeApi`, so
 * tests run without a window.
 */

import { Channel, invoke } from "@tauri-apps/api/core";

import type { Inbound, NativeApi } from "./bridge.ts";

export const tauriApi: NativeApi = {
  invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
    return invoke<T>(command, args);
  },
  channel(onMessage: (message: Inbound) => void): unknown {
    const channel = new Channel<Inbound>();
    channel.onmessage = onMessage;
    return channel;
  },
};
