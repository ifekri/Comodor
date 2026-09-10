/**
 * Talking to a Comodor core.
 *
 * Two layers, split so the interesting one can be tested without a process.
 *
 * `CoreClient` owns the conversation: the handshake, correlating a response
 * to the request that asked for it, and handing events to whoever subscribed.
 * It is given a `Transport` — anything with a readable line stream and a way
 * to write one — so a test drives it with two arrays and no operating system.
 *
 * `spawnCore` is the only part that knows about a child process, and it is
 * deliberately thin: spawn, wire the streams, kill it on the way out. A future
 * socket or WebSocket is a second `Transport` and changes nothing above it.
 *
 * The one rule it enforces on the way in: **stdout is protocol**. Anything the
 * core writes to stderr is handed to `onDiagnostic` and never parsed, because
 * a core that prints a warning must not look like a core that broke.
 */

import {
  PROTOCOL_VERSION,
  ProtocolError,
  decode,
  request,
  type Envelope,
  type EventName,
  type Method,
} from "@comodor/protocol";

export interface Transport {
  /** Every complete line the far end has written, in order. */
  lines(): AsyncIterable<string>;
  /** One line, terminated. */
  write(line: string): void;
  /** Stop, and release whatever is underneath. */
  close(): Promise<void> | void;
}

export interface PeerInfo {
  name: string;
  version: string;
}

export interface Handshake {
  protocol_version: number;
  core: PeerInfo;
  capabilities: string[];
}

/**
 * One event, and where it sits in its session's sequence.
 *
 * `seq` is passed on rather than swallowed because reconciling a snapshot
 * with a live stream is the client's job, not the transport's: only the thing
 * holding the projection knows which events it has already applied.
 */
export type EventListener = (
  name: EventName, params: Record<string, unknown>, seq: number,
) => void;

export interface CoreClientOptions {
  client?: PeerInfo;
  capabilities?: string[];
  /** Lines the core wrote to stderr. Diagnostics, never protocol. */
  onDiagnostic?: (text: string) => void;
  /** The reader stopped: the core exited, or the pipe broke. */
  onClosed?: (reason: string) => void;
  /** How long a single request may wait. Zero waits forever. */
  timeoutMs?: number;
}

/**
 * A disconnect listener, registered whenever a client has one drawn.
 *
 * `CoreClientOptions.onClosed` exists for the constructor's owner; a UI that
 * mounts after the client was built needs to subscribe later, or a core that
 * dies while the screen is idle keeps the screen frozen forever.
 */
export type CloseListener = (reason: string) => void;

interface Pending {
  resolve: (result: Record<string, unknown>) => void;
  reject: (problem: Error) => void;
  timer?: ReturnType<typeof setTimeout>;
}

/** How long a request waits before giving up, when nothing says otherwise. */
export const DEFAULT_TIMEOUT_MS = 30_000;

export class CoreClient {
  readonly transport: Transport;
  private readonly options: CoreClientOptions;
  private readonly pending = new Map<string, Pending>();
  private readonly listeners = new Set<EventListener>();
  private readonly closeListeners = new Set<CloseListener>();
  private next = 0;
  /** The reader loop. Awaited on close so nothing is still parsing after it. */
  private reading: Promise<void> = Promise.resolve();
  private closedReason = "";

  handshake?: Handshake;

  constructor(transport: Transport, options: CoreClientOptions = {}) {
    this.transport = transport;
    this.options = options;
  }

  /** Whether the far end is still there. */
  get open(): boolean {
    return this.closedReason === "";
  }

  /** Start reading, then say hello. Nothing else may be called before this. */
  async start(): Promise<Handshake> {
    this.reading = this.read();
    const result = await this.call("client.hello", {
      protocol_version: PROTOCOL_VERSION,
      client: this.options.client ?? { name: "comodor-client", version: "0" },
      capabilities: this.options.capabilities ?? ["questions", "permissions"],
    });
    this.handshake = result as unknown as Handshake;
    if (this.handshake.protocol_version !== PROTOCOL_VERSION) {
      // The core answering with a different version than it was asked for
      // would mean the handshake did not do its job. Refuse rather than
      // proceed and discover it at the first message that does not fit.
      throw new ProtocolError("unsupported_version",
        `the core answered with protocol ${this.handshake.protocol_version}`);
    }
    return this.handshake;
  }

  on(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** The reader ended, at most once, for whoever needs to know now. */
  onClose(listener: CloseListener): () => void {
    this.closeListeners.add(listener);
    return () => this.closeListeners.delete(listener);
  }

  /** One request, and the result it is answered with. */
  call(method: Method, params: Record<string, unknown> = {}):
      Promise<Record<string, unknown>> {
    if (!this.open) {
      return Promise.reject(new ProtocolError("internal_error", this.closedReason));
    }
    this.next += 1;
    const id = String(this.next);
    return new Promise((resolve, reject) => {
      const wait = this.options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
      const entry: Pending = { resolve, reject };
      if (wait > 0) {
        entry.timer = setTimeout(() => {
          this.pending.delete(id);
          reject(new ProtocolError("internal_error",
            `${method} was not answered within ${wait}ms`));
        }, wait);
        // A pending request must not be the reason a process stays alive.
        entry.timer.unref?.();
      }
      this.pending.set(id, entry);
      try {
        this.transport.write(JSON.stringify(request(id, method, params)));
      } catch (problem) {
        this.settle(id).reject(problem as Error);
      }
    });
  }

  async close(): Promise<void> {
    if (this.open) {
      try {
        // Best effort: a core that has already gone will not answer, and
        // that is not a failure worth reporting on the way out.
        await this.call("shutdown");
      } catch {
        /* it is going away either way */
      }
    }
    await this.transport.close();
    this.fail("closed");
    // The reader ends when the transport does. Awaited so a caller that
    // closes and then inspects state is not racing a line still being parsed.
    await this.reading;
  }

  // -- the reader -------------------------------------------------------- //

  private async read(): Promise<void> {
    try {
      for await (const line of this.transport.lines()) {
        if (!line.trim()) continue;
        let message: Envelope;
        try {
          message = decode(line);
        } catch (problem) {
          // A line this client cannot read is a fault at the far end, and
          // stopping would turn one bad line into a dead session.
          this.options.onDiagnostic?.(
            `unreadable line from the core: ${(problem as Error).message}`);
          continue;
        }
        this.deliver(message);
      }
      this.fail("the core closed its output");
    } catch (problem) {
      this.fail(`the connection failed: ${(problem as Error).message}`);
    }
  }

  private deliver(message: Envelope): void {
    if (message.type === "event") {
      for (const listener of this.listeners) {
        try {
          listener(message.event, message.params, message.seq);
        } catch (problem) {
          // One broken listener must not stop the others, or take the
          // reader down with it.
          this.options.onDiagnostic?.(
            `an event listener threw: ${(problem as Error).message}`);
        }
      }
      return;
    }
    if (message.type === "response") {
      this.settle(message.id).resolve(message.result);
      return;
    }
    if (message.type === "error") {
      const { code, message: text, data } = message.error;
      const problem = new ProtocolError(code, text, data ?? {});
      if (message.id === null) {
        // Nothing to correlate it to: the core could not read far enough to
        // find an id. It belongs in the log, not attached to a random call.
        this.options.onDiagnostic?.(`the core refused a line: ${text}`);
        return;
      }
      this.settle(message.id).reject(problem);
      return;
    }
    this.options.onDiagnostic?.("the core sent a request; this client answers none");
  }

  private settle(id: string): Pending {
    const entry = this.pending.get(id);
    this.pending.delete(id);
    if (!entry) {
      return { resolve: () => {}, reject: () => {} };
    }
    if (entry.timer) clearTimeout(entry.timer);
    return entry;
  }

  private fail(reason: string): void {
    if (!this.open) return;
    this.closedReason = reason;
    for (const [id] of [...this.pending]) {
      this.settle(id).reject(new ProtocolError("internal_error", reason));
    }
    this.options.onClosed?.(reason);
    for (const listener of this.closeListeners) {
      try {
        listener(reason);
      } catch {
        // One broken listener must not stop the others, exactly as with
        // events: a freeze here is how a dead core looks alive.
      }
    }
  }
}

export { ProtocolError };
export type { EventName, Method };
