/**
 * The page's connection to its Core, through the native side.
 *
 * One bridge connection carries the Core's status for the page's whole life.
 * When the status is `ready`, a `CoreClient` is started over it — its hello is
 * answered natively from the cached handshake. When the Core goes, the native
 * side closes the connection; the next `ready` brings a fresh connection, a
 * new generation, and a new client. Nothing from an old one reaches it.
 */

import { CoreClient } from "@comodor/client";

import { connect, type BridgeConnection, type CoreStatus, type NativeApi } from "./bridge.ts";

export interface ConnectionState {
  readonly status: CoreStatus | null;
  /** A started client while the Core is ready; null otherwise. */
  readonly client: CoreClient | null;
}

export class Connection {
  private state: ConnectionState = { status: null, client: null };
  private readonly listeners = new Set<() => void>();
  private bridge: BridgeConnection | null = null;
  private attaching: Promise<BridgeConnection> | null = null;
  private starting = false;
  private disposed = false;

  constructor(private readonly api: NativeApi) {}

  get snapshot(): ConnectionState {
    return this.state;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Attach to the native side, and learn the current status. */
  async open(): Promise<void> {
    await this.attached();
    const current = await this.api.invoke<CoreStatus>("status");
    if (!this.state.status) this.setStatus(current);
  }

  dispose(): void {
    this.disposed = true;
    this.bridge?.close();
    this.listeners.clear();
  }

  private update(next: Partial<ConnectionState>): void {
    this.state = { ...this.state, ...next };
    for (const listener of this.listeners) listener();
  }

  private setStatus(status: CoreStatus): void {
    if (this.disposed) return;
    this.update({ status });
    // A status can arrive while `connect` itself is still being answered;
    // the client starts once that connection is recorded, never beside it.
    if (status.state === "ready") void Promise.resolve().then(() => this.startClient());
  }

  /** The open bridge connection, or a new one. */
  private attached(): Promise<BridgeConnection> {
    if (this.bridge && !this.bridge.closedReason) return Promise.resolve(this.bridge);
    if (!this.attaching) {
      this.attaching = connect(this.api, (status) => this.setStatus(status))
        .then((bridge) => {
          this.bridge = bridge;
          return bridge;
        })
        .finally(() => {
          this.attaching = null;
        });
    }
    return this.attaching;
  }

  private async startClient(): Promise<void> {
    if (this.starting || this.state.client?.open) return;
    this.starting = true;
    try {
      const bridge = await this.attached();
      const client = new CoreClient(bridge, {
        client: { name: "comodor-desktop", version: "0.1.0" },
        capabilities: ["questions", "permissions"],
      });
      client.onClose(() => {
        if (this.state.client !== client) return;
        this.update({ client: null });
        // The status may already say the next Core is ready; it will not say
        // so again, so the next client starts here.
        if (this.state.status?.state === "ready") void Promise.resolve().then(() => this.startClient());
      });
      await client.start();
      if (this.disposed) return;
      // The test build's scenarios compare what the window shows with what
      // the Core says; fixed at build time, so a release build has none of it.
      if (import.meta.env.MODE === "e2e") {
        (window as unknown as Record<string, unknown>)["__comodorClient"] = client;
      }
      this.update({ client });
    } catch {
      // The Core went while the client was starting. The status says so, and
      // the next `ready` starts a new client.
    } finally {
      this.starting = false;
    }
  }
}
