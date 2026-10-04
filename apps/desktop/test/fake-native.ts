/**
 * The native side, in memory, for window tests: the bridge commands over a
 * `FakeCore`. `connect` opens the page's channel and pumps the Core's lines
 * into it; `send_line` hands a line to the Core; the other commands answer
 * from what the test set.
 */

import type { CoreStatus, Inbound, NativeApi } from "../src/bridge.ts";

import { FakeCore } from "./fake-core.ts";

export interface Call {
  readonly command: string;
  readonly args: Record<string, unknown> | undefined;
}

export function status(overrides: Partial<CoreStatus> = {}): CoreStatus {
  return {
    state: "ready",
    workspace: "/work/project",
    failure: null,
    restart_count: 0,
    restart_limit: 3,
    closing: null,
    stop_outcome: null,
    core: { name: "comodor-core", version: "test" },
    notice: null,
    ...overrides,
  };
}

export class FakeNative {
  readonly calls: Call[] = [];
  core: FakeCore;
  current: CoreStatus;
  diagnostics = "";
  /** What `choose_workspace` answers. */
  chosen: string | null = null;
  private deliver: ((message: Inbound) => void) | undefined;
  private generation = 0;
  /** The generation whose lines reach the Core; none once its Core went. */
  private live: number | undefined;

  constructor(initial: CoreStatus = status(), core: FakeCore = new FakeCore()) {
    this.current = initial;
    this.core = core;
  }

  /** A status change, as the native side reports it. */
  push(next: CoreStatus): void {
    this.current = next;
    this.deliver?.({ kind: "status", status: next });
  }

  /**
   * The Core is restarted: the old one ends (the page's connection closes),
   * the status says so, and `next` is the Core the next connection reaches.
   */
  restart(next: FakeCore, count = 1): void {
    this.replace(next, { ...this.current, state: "restarting", restart_count: count },
                 { ...this.current, state: "ready", restart_count: count });
  }

  /**
   * One Core replaced by `next`, in the order the native side keeps: the
   * status (`during`), then the page's connection closed, then — once the
   * next Core is ready — `after`. A line from the old generation is refused.
   */
  replace(next: FakeCore, during: CoreStatus, after: CoreStatus): void {
    this.push(during);
    const old = this.core;
    this.core = next;
    this.live = undefined;
    this.deliver?.({ kind: "closed", reason: "the Core stopped" });
    old.end();
    this.push(after);
  }

  commands(name: string): Call[] {
    return this.calls.filter((call) => call.command === name);
  }

  readonly api: NativeApi = {
    invoke: async <T>(command: string, args?: Record<string, unknown>): Promise<T> => {
      this.calls.push({ command, args });
      switch (command) {
        case "connect": {
          this.generation += 1;
          this.live = this.generation;
          const deliver = args?.["on"] as (message: Inbound) => void;
          this.deliver = deliver;
          deliver({ kind: "status", status: this.current });
          void (async () => {
            for await (const line of this.core.lines()) deliver({ kind: "line", line });
            deliver({ kind: "closed", reason: "the Core stopped" });
          })();
          return { generation: this.generation } as T;
        }
        case "send_line":
          if (args?.["generation"] !== this.live) throw new Error("the generation is not current");
          this.core.write(String(args?.["line"]));
          return {} as T;
        case "status":
          return this.current as T;
        case "diagnostics":
          return this.diagnostics as T;
        case "choose_workspace":
          return this.chosen as T;
        default:
          return {} as T;
      }
    },
    channel: (onMessage) => onMessage,
  };
}

/** A window whose Core is ready and whose session has been opened. */
export async function openWindow(
  render: (native: FakeNative) => Promise<{ container: HTMLElement }>,
  until: <T>(found: () => T | null | undefined | false, what?: string) => Promise<T>,
  native: FakeNative = new FakeNative(),
): Promise<{ native: FakeNative; container: HTMLElement }> {
  const view = await render(native);
  await until(() => native.core.requests("session.snapshot").length > 0, "the session snapshot");
  await until(() => view.container.querySelector('[data-testid="composer"]'), "the composer");
  return { native, container: view.container };
}
