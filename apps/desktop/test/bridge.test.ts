/**
 * T012: the page's `Transport` over the native bridge
 * (contracts/native-bridge.md §The page's `Transport`).
 *
 * The native side is a fake here: `invoke` records what the page asked for,
 * and the IPC channel is a callback the test drives. No window, no Core.
 */

import { describe, expect, test } from "bun:test";

import { connect, type CoreStatus, type Inbound, type NativeApi } from "../src/bridge.ts";

interface Recorded {
  command: string;
  args: Record<string, unknown> | undefined;
}

function fakeNative(options: { refuseSend?: string } = {}) {
  const calls: Recorded[] = [];
  let deliver: ((message: Inbound) => void) | undefined;
  const api: NativeApi = {
    async invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
      calls.push({ command, args });
      if (command === "connect") return { generation: 7 } as T;
      if (command === "send_line" && options.refuseSend) throw options.refuseSend;
      return {} as T;
    },
    channel(onMessage) {
      deliver = onMessage;
      return { id: "channel" };
    },
  };
  const push = (message: Inbound): void => {
    if (!deliver) throw new Error("connect has not opened a channel yet");
    deliver(message);
  };
  return { api, calls, push };
}

async function collect(lines: AsyncIterable<string>): Promise<string[]> {
  const out: string[] = [];
  for await (const line of lines) out.push(line);
  return out;
}

describe("the bridge Transport", () => {
  test("connect opens the channel and learns its generation", async () => {
    const native = fakeNative();
    const bridge = await connect(native.api, () => {});
    expect(bridge.generation).toBe(7);
    expect(native.calls[0]).toEqual({ command: "connect", args: { on: { id: "channel" } } });
  });

  test("lines() yields line messages in order, and a closed message ends it", async () => {
    const native = fakeNative();
    const bridge = await connect(native.api, () => {});
    const seen = collect(bridge.lines());
    native.push({ kind: "line", line: "one" });
    native.push({ kind: "line", line: "two" });
    native.push({ kind: "closed", reason: "the Core stopped" });
    native.push({ kind: "line", line: "after the end" });
    expect(await seen).toEqual(["one", "two"]);
    expect(bridge.closedReason).toBe("the Core stopped");
  });

  test("status messages go to the status listener, never into the line stream", async () => {
    const native = fakeNative();
    const statuses: CoreStatus[] = [];
    const bridge = await connect(native.api, (status) => statuses.push(status));
    const seen = collect(bridge.lines());
    const status = { state: "ready" } as unknown as CoreStatus;
    native.push({ kind: "status", status });
    native.push({ kind: "closed", reason: "done" });
    expect(await seen).toEqual([]);
    expect(statuses).toEqual([status]);
  });

  test("write() sends the line with this page's generation", async () => {
    const native = fakeNative();
    const bridge = await connect(native.api, () => {});
    bridge.write('{"version":2,"type":"request","id":"1","method":"model.get","params":{}}');
    expect(native.calls[1]).toEqual({
      command: "send_line",
      args: {
        generation: 7,
        line: '{"version":2,"type":"request","id":"1","method":"model.get","params":{}}',
      },
    });
  });

  test("a refused line becomes an error answer for that request, on this page only", async () => {
    const native = fakeNative({ refuseSend: "shutdown is the native side's to send" });
    const bridge = await connect(native.api, () => {});
    const seen = collect(bridge.lines());
    bridge.write('{"version":2,"type":"request","id":"9","method":"shutdown","params":{}}');
    await Promise.resolve();
    await Promise.resolve();
    native.push({ kind: "closed", reason: "end" });
    const [answer] = await seen;
    const parsed = JSON.parse(answer ?? "{}") as Record<string, unknown>;
    expect(parsed["type"]).toBe("error");
    expect(parsed["id"]).toBe("9");
    expect((parsed["error"] as Record<string, unknown>)["message"])
      .toBe("shutdown is the native side's to send");
  });

  test("close() detaches the page and calls no stop command", async () => {
    const native = fakeNative();
    const bridge = await connect(native.api, () => {});
    const seen = collect(bridge.lines());
    await bridge.close();
    expect(await seen).toEqual([]);
    expect(native.calls.map((call) => call.command)).toEqual(["connect"]);
  });
});
