/**
 * A Core in memory, for the window's tests (T014).
 *
 * It stands where the bridge and the real Core stand together: it answers the
 * handshake, keeps one session, and lets a test push events and decide how
 * each request is answered. The desktop's own double — it shares nothing with
 * the terminal interface's tests, so neither can change the other's.
 */

import type { Transport } from "@comodor/client";
import { PROTOCOL_VERSION } from "@comodor/protocol";

type Params = Record<string, unknown>;

export interface SentRequest {
  readonly id: string;
  readonly method: string;
  readonly params: Params;
}

/** What a handler returns: a result, or an error to answer with. */
export type Answer =
  | { readonly result: Params }
  | { readonly error: { readonly code: string; readonly message: string } }
  /** Answered later by the test, through `answer()`. */
  | { readonly hold: true };

export class FakeCore implements Transport {
  readonly sent: SentRequest[] = [];
  session = { id: "s1", mode: "act", workspace: "/work/project", busy: false };
  model = { provider: "fake", model: "fake-1", configured: true };
  turns = 0;
  snapshot: Params = {
    session: this.session, revision: 0, messages: [], tools: [],
  };
  /** Per-method overrides of the default answers. */
  readonly handlers = new Map<string, (params: Params, id: string) => Answer>();

  private seq = 0;
  /** The sessions live in this Core: created or opened in it. */
  private live = new Set<string>();
  private queued: string[] = [];
  private wake: (() => void) | undefined;
  private done = false;

  lines(): AsyncIterable<string> {
    const self = this;
    return {
      async *[Symbol.asyncIterator]() {
        for (;;) {
          const next = self.queued.shift();
          if (next !== undefined) {
            yield next;
            continue;
          }
          if (self.done) return;
          await new Promise<void>((resolve) => {
            self.wake = resolve;
          });
          self.wake = undefined;
        }
      },
    };
  }

  write(line: string): void {
    const message = JSON.parse(line) as Params;
    const request: SentRequest = {
      id: String(message["id"]),
      method: String(message["method"]),
      params: (message["params"] ?? {}) as Params,
    };
    this.sent.push(request);
    const handler = this.handlers.get(request.method);
    const answer = handler
      ? handler(request.params, request.id)
      : this.defaultAnswer(request);
    if ("hold" in answer) return;
    if ("error" in answer) this.error(request.id, answer.error.code, answer.error.message);
    else this.respond(request.id, answer.result);
  }

  close(): void {
    this.end();
  }

  // -- what a test drives ---------------------------------------------------- //

  /** An event from the Core, numbered in this session's sequence. */
  emit(event: string, params: Params, seq?: number): void {
    this.seq = seq ?? this.seq + 1;
    this.push({ version: PROTOCOL_VERSION, type: "event", event, seq: this.seq, params });
  }

  respond(id: string, result: Params): void {
    this.push({ version: PROTOCOL_VERSION, type: "response", id, result });
  }

  error(id: string, code: string, message: string): void {
    this.push({ version: PROTOCOL_VERSION, type: "error", id, error: { code, message } });
  }

  /** The connection ends, as it does when the Core's process exits. */
  end(): void {
    this.done = true;
    this.wake?.();
  }

  /** Every request for one method, in order. */
  requests(method: string): SentRequest[] {
    return this.sent.filter((request) => request.method === method);
  }

  // -- the defaults ---------------------------------------------------------- //

  private defaultAnswer(request: SentRequest): Answer {
    switch (request.method) {
      case "client.hello":
        return { result: {
          protocol_version: PROTOCOL_VERSION,
          core: { name: "comodor-core", version: "test" },
          capabilities: ["streaming", "questions", "permissions", "modes",
                         "tool_events", "tasks", "delegates", "usage"],
        } };
      case "session.create":
      case "session.open":
        this.live.add(this.session.id);
        return { result: { session: this.session } };
      case "session.list":
        // Only what is live in this Core, as the real one answers.
        return { result: { sessions: this.live.has(this.session.id) ? [this.session] : [] } };
      case "session.snapshot": {
        const at = Number(this.snapshot["revision"] ?? 0);
        if (at > this.seq) this.seq = at;
        return { result: { snapshot: this.snapshot } };
      }
      case "session.send":
        this.turns += 1;
        return { result: { accepted: true, turn_id: `t${this.turns}` } };
      case "session.cancel":
        return { result: { cancelled: true } };
      case "session.set_mode":
        return { result: { session: { ...this.session, mode: String(request.params["mode"]) } } };
      case "model.get":
        return { result: this.model };
      case "workspace.get":
        return { result: { path: this.session.workspace } };
      case "question.answer":
      case "permission.reply":
        return { result: {} };
      default:
        return { error: { code: "unknown_method", message: `no method named ${request.method}` } };
    }
  }

  private push(message: Params): void {
    if (this.done) return;
    this.queued.push(JSON.stringify(message));
    this.wake?.();
  }
}
