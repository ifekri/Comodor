/**
 * The client, driven without a process.
 *
 * A fake transport is two queues, so correlation, the handshake, events and
 * every way a connection ends can be tested exactly and instantly. What is
 * left for a real core is in `tests/test_core_stdio.py`.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  PROTOCOL_VERSION,
  errorEnvelope,
  event,
  response,
} from "@comodor/protocol";

import { CoreClient, ProtocolError, type Transport } from "../src/index.ts";

/** A transport whose far end is a function you call. */
class Loopback implements Transport {
  readonly written: string[] = [];
  private waiting: Array<(line: string | null) => void> = [];
  private queued: string[] = [];
  private done = false;
  /** Called with each decoded request, so a test can answer it. */
  onRequest?: (message: Record<string, unknown>) => void;

  lines(): AsyncIterable<string> {
    const self = this;
    return {
      async *[Symbol.asyncIterator]() {
        for (;;) {
          const line = await self.take();
          if (line === null) return;
          yield line;
        }
      },
    };
  }

  write(line: string): void {
    this.written.push(line);
    this.onRequest?.(JSON.parse(line) as Record<string, unknown>);
  }

  close(): void {
    this.finish();
  }

  /** The far end says something. */
  push(message: unknown): void {
    const line = JSON.stringify(message);
    const next = this.waiting.shift();
    if (next) next(line);
    else this.queued.push(line);
  }

  /** The far end goes away. */
  finish(): void {
    if (this.done) return;
    this.done = true;
    for (const waiter of this.waiting.splice(0)) waiter(null);
  }

  private take(): Promise<string | null> {
    const ready = this.queued.shift();
    if (ready !== undefined) return Promise.resolve(ready);
    if (this.done) return Promise.resolve(null);
    return new Promise((resolve) => this.waiting.push(resolve));
  }
}

/** A transport that answers the handshake and whatever else is scripted. */
function scripted(answers: Record<string, Record<string, unknown>> = {}) {
  const transport = new Loopback();
  transport.onRequest = (message) => {
    const id = String(message["id"]);
    const method = String(message["method"]);
    if (method === "client.hello") {
      transport.push(response(id, {
        protocol_version: PROTOCOL_VERSION,
        core: { name: "fake-core", version: "0" },
        capabilities: ["streaming", "questions"],
      }));
      return;
    }
    const scriptedAnswer = answers[method];
    if (scriptedAnswer) transport.push(response(id, scriptedAnswer));
  };
  return transport;
}

test("the handshake reports what the core said it can do", async () => {
  const transport = scripted();
  const client = new CoreClient(transport);

  const shook = await client.start();

  assert.equal(shook.protocol_version, PROTOCOL_VERSION);
  assert.equal(shook.core.name, "fake-core");
  assert.ok(shook.capabilities.includes("streaming"));
});

test("the first thing written is the handshake", async () => {
  const transport = scripted();
  await new CoreClient(transport).start();

  const first = JSON.parse(transport.written[0] ?? "{}") as Record<string, unknown>;
  assert.equal(first["method"], "client.hello");
});

test("a core answering with another version is refused", async () => {
  // The handshake exists to catch this. Proceeding would mean discovering it
  // at whatever message first does not fit.
  const transport = new Loopback();
  transport.onRequest = (message) => {
    transport.push(response(String(message["id"]), {
      protocol_version: 99,
      core: { name: "wrong", version: "0" },
      capabilities: [],
    }));
  };

  await assert.rejects(new CoreClient(transport).start(),
    (problem: ProtocolError) => problem.code === "unsupported_version");
});

test("two calls in flight are answered to the right callers", async () => {
  // Correlation is the one thing a client cannot get away with almost doing.
  const transport = new Loopback();
  const seen: string[] = [];
  transport.onRequest = (message) => {
    const id = String(message["id"]);
    const method = String(message["method"]);
    if (method === "client.hello") {
      transport.push(response(id, {
        protocol_version: PROTOCOL_VERSION,
        core: { name: "fake", version: "0" }, capabilities: [],
      }));
      return;
    }
    seen.push(id);
    // Answered out of order on purpose.
    if (seen.length === 2) {
      transport.push(response(seen[1] as string, { which: "second" }));
      transport.push(response(seen[0] as string, { which: "first" }));
    }
  };

  const client = new CoreClient(transport);
  await client.start();
  const [first, second] = await Promise.all([
    client.call("workspace.get"),
    client.call("model.get"),
  ]);

  assert.equal(first["which"], "first");
  assert.equal(second["which"], "second");
});

test("an error envelope rejects the call it names", async () => {
  const transport = new Loopback();
  transport.onRequest = (message) => {
    const id = String(message["id"]);
    if (message["method"] === "client.hello") {
      transport.push(response(id, {
        protocol_version: PROTOCOL_VERSION,
        core: { name: "fake", version: "0" }, capabilities: [],
      }));
      return;
    }
    transport.push(errorEnvelope(id, "unknown_session", "no session 'x'"));
  };

  const client = new CoreClient(transport);
  await client.start();

  await assert.rejects(client.call("session.get", { session_id: "x" }),
    (problem: ProtocolError) => problem.code === "unknown_session");
});

test("an error with no id is logged, not attached to a random call", async () => {
  const transport = scripted({ "workspace.get": { path: "/tmp" } });
  const notes: string[] = [];
  const client = new CoreClient(transport, {
    onDiagnostic: (text) => notes.push(text),
  });
  await client.start();

  transport.push(errorEnvelope(null, "parse_error", "a bad line"));
  const answer = await client.call("workspace.get");

  assert.equal(answer["path"], "/tmp");
  assert.ok(notes.some((note) => note.includes("a bad line")));
});

test("events reach every listener and unsubscribing stops them", async () => {
  const transport = scripted();
  const client = new CoreClient(transport);
  await client.start();

  const seen: string[] = [];
  const stop = client.on((name) => seen.push(name));
  transport.push(event("message.started",
    { session_id: "s", message_id: "m", role: "assistant" }));
  await tick();

  stop();
  transport.push(event("message.completed", { session_id: "s", message_id: "m" }));
  await tick();

  assert.deepEqual(seen, ["message.started"]);
});

test("one listener that throws does not stop the others", async () => {
  const transport = scripted();
  const notes: string[] = [];
  const client = new CoreClient(transport, {
    onDiagnostic: (text) => notes.push(text),
  });
  await client.start();

  const seen: string[] = [];
  client.on(() => { throw new Error("boom"); });
  client.on((name) => seen.push(name));
  transport.push(event("mode.changed", { session_id: "s", mode: "plan" }));
  await tick();

  assert.deepEqual(seen, ["mode.changed"]);
  assert.ok(notes.some((note) => note.includes("boom")));
});

test("an unreadable line is reported and the session keeps going", async () => {
  const transport = scripted({ "model.get": { provider: "fake" } });
  const notes: string[] = [];
  const client = new CoreClient(transport, {
    onDiagnostic: (text) => notes.push(text),
  });
  await client.start();

  // Not via `push`, which would encode it as JSON.
  (transport as unknown as { push(m: unknown): void }).push("not an envelope");
  const answer = await client.call("model.get");

  assert.equal(answer["provider"], "fake");
  assert.ok(notes.some((note) => note.includes("unreadable")));
});

test("the core going away fails every call still waiting", async () => {
  const transport = scripted();
  const client = new CoreClient(transport);
  await client.start();

  const waiting = client.call("session.list");
  transport.finish();

  await assert.rejects(waiting,
    (problem: ProtocolError) => /closed its output/.test(problem.message));
  assert.equal(client.open, false);
});

test("a call after the core is gone fails at once", async () => {
  const transport = scripted();
  const client = new CoreClient(transport);
  await client.start();
  transport.finish();
  await tick();

  await assert.rejects(client.call("session.list"));
});

test("a call that is never answered gives up rather than hanging", async () => {
  const transport = new Loopback();
  transport.onRequest = (message) => {
    if (message["method"] === "client.hello") {
      transport.push(response(String(message["id"]), {
        protocol_version: PROTOCOL_VERSION,
        core: { name: "fake", version: "0" }, capabilities: [],
      }));
    }
    // Everything else is ignored, as a wedged core would.
  };
  const client = new CoreClient(transport, { timeoutMs: 25 });
  await client.start();

  await assert.rejects(client.call("session.list"),
    (problem: ProtocolError) => /not answered within/.test(problem.message));
});

test("closing tells the core and then the transport", async () => {
  const transport = scripted({ shutdown: { ok: true } });
  const client = new CoreClient(transport);
  await client.start();

  await client.close();

  const methods = transport.written.map(
    (line) => (JSON.parse(line) as Record<string, unknown>)["method"]);
  assert.deepEqual(methods, ["client.hello", "shutdown"]);
  assert.equal(client.open, false);
});

function tick(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}
