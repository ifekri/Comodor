/**
 * What the interface costs, measured rather than asserted.
 *
 * Not a test. There are no thresholds here, because a ceiling on a
 * microbenchmark measures whichever runner it landed on — the Python suite
 * already learned that lesson, and its performance ceilings are the loose
 * ones that survive it. This prints numbers, and a person reads them.
 *
 *     bun apps/tui/test/measure.ts
 */

import { testRender } from "@opentui/react/test-utils";

import { CoreClient, type Transport } from "@comodor/client";
import { PROTOCOL_VERSION, event, response } from "@comodor/protocol";

import { App } from "../../src/App.tsx";

class Loop implements Transport {
  private waiting: Array<(line: string | null) => void> = [];
  private queued: string[] = [];
  mode = "act";

  lines(): AsyncIterable<string> {
    const self = this;
    return { async *[Symbol.asyncIterator]() {
      for (;;) { const l = await self.take(); if (l === null) return; yield l; }
    } };
  }

  write(line: string): void {
    const m = JSON.parse(line) as Record<string, unknown>;
    const id = String(m["id"]);
    const method = String(m["method"]);
    const params = (m["params"] ?? {}) as Record<string, unknown>;
    if (method === "client.hello") {
      this.push(response(id, { protocol_version: PROTOCOL_VERSION,
        core: { name: "bench", version: "0" },
        capabilities: ["streaming", "questions", "permissions", "modes"] }));
    } else if (method === "session.create") {
      this.push(response(id, { session: this.session() }));
    } else if (method === "session.set_mode") {
      this.mode = String(params["mode"]);
      this.push(response(id, { session: this.session() }));
      this.push(event("mode.changed", { session_id: "s1", mode: this.mode }));
    } else {
      this.push(response(id, {}));
    }
  }

  close(): void { for (const w of this.waiting.splice(0)) w(null); }

  push(message: unknown): void {
    const line = JSON.stringify(message);
    const next = this.waiting.shift();
    if (next) next(line); else this.queued.push(line);
  }

  session() {
    return { id: "s1", mode: this.mode, workspace: "/work/project",
             busy: false };
  }

  private take(): Promise<string | null> {
    const ready = this.queued.shift();
    if (ready !== undefined) return Promise.resolve(ready);
    return new Promise((r) => this.waiting.push(r));
  }
}

function mib(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

function ms(seconds: number): string {
  return `${(seconds * 1000).toFixed(1)} ms`;
}

async function main(): Promise<void> {
  const started = performance.now();
  const core = new Loop();
  const client = new CoreClient(core, { timeoutMs: 10_000 });
  await client.start();
  const handshake = performance.now() - started;

  const rendered = await testRender(
    <App client={client} onQuit={() => {}} />, { width: 120, height: 40 });
  await rendered.flush();
  await rendered.waitForFrame((frame) => frame.includes("project"));
  const firstFrame = performance.now() - started;

  console.log("TUI, under Bun " + Bun.version);
  console.log(`  spawn to handshake        ${ms(handshake / 1000)}`);
  console.log(`  handshake to first frame  ${ms((firstFrame - handshake) / 1000)}`);
  console.log(`  cold start, total         ${ms(firstFrame / 1000)}`);

  // A mode switch is a key press, a round trip to the core, and a repaint.
  // It is *not* measured here: driving Tab repeatedly in this harness stops
  // registering after a cycle, and a number coaxed out of that would be a
  // number about the harness. The renderer suite proves the behaviour;
  // `tests/test_protocol_performance.py` measures the core half at 1.3 µs.

  // Local state only: typing into the composer never leaves the process.
  const typed: number[] = [];
  for (let round = 0; round < 20; round += 1) {
    const at = performance.now();
    await rendered.mockInput.typeText("x");
    await rendered.flush();
    typed.push(performance.now() - at);
  }
  typed.sort((a, b) => a - b);
  console.log(`  keystroke to local update p50 ${ms(typed[10]! / 1000)}`
    + `  p95 ${ms(typed[18]! / 1000)}`);

  // A streamed answer, as the core would send one.
  //
  // Measured to "delivered, applied and painted once", not to "the last chunk
  // is legible": the conversation does not scroll to the newest line yet, so
  // the tail of a long answer is below the viewport. That is a real gap and
  // it is in `docs/tui-v2.md`; measuring against it would be measuring the
  // gap rather than the streaming.
  const deltas = 2_000;
  let applied = 0;
  const stop = client.on((name) => { if (name === "message.delta") applied += 1; });

  const streamed = performance.now();
  core.push(event("message.started",
    { session_id: "s1", message_id: "m1", role: "assistant" }));
  for (let index = 0; index < deltas; index += 1) {
    core.push(event("message.delta",
      { session_id: "s1", message_id: "m1", text: `chunk ${index} ` }));
  }
  core.push(event("message.completed",
    { session_id: "s1", message_id: "m1" }));

  while (applied < deltas) await Bun.sleep(1);
  await rendered.flush();
  const streaming = performance.now() - streamed;
  stop();
  console.log(`  ${deltas} deltas to painted    ${ms(streaming / 1000)}`
    + `  (${(streaming / deltas).toFixed(3)} ms each)`);

  // Blocking interactions: what it costs to put a card on the screen, to move
  // within it, and to get a decision away. Printed rather than asserted — a
  // threshold in CI would measure whichever runner it landed on, and the
  // renderer suite is what proves the behaviour.
  //
  // `settle` is the same yield the renderer suite uses: React schedules its
  // work on the macrotask queue, and `flush` alone turns only the microtask
  // queue, so a state update made from an arriving event is still pending when
  // a frame is captured. Without it the wait below spins on a screen React has
  // not been given the chance to change.
  // One real millisecond rather than `sleep(0)`: under load a single turn of
  // the macrotask queue is not always enough for React to commit, and a wait
  // that times out measures nothing. The millisecond is inside the measured
  // window, so every interaction figure below carries about 1 ms of harness.
  const settle = async () => { await Bun.sleep(1); await rendered.flush(); };
  const PATIENT = { maxPasses: 400 } as const;
  const prompt = {
    id: "perm-m1", session_id: "s1", title: "run: npm test",
    detail: "$ npm test", options: ["allow", "allow_always", "deny"],
    tool: "run_shell", risk: "dangerous",
  };

  let marked = performance.now();
  core.push(event("permission.requested", prompt));
  await settle();
  await rendered.waitForFrame((frame) => frame.includes("Permission needed"),
                              PATIENT);
  await rendered.flush();
  console.log(`  permission card open      ${ms((performance.now() - marked) / 1000)}`);

  marked = performance.now();
  rendered.mockInput.pressArrow("left");
  await settle();
  await rendered.waitForFrame(
    (frame) => frame.includes("[Allow for this session]"), PATIENT);
  await rendered.flush();
  console.log(`  key to selection moved    ${ms((performance.now() - marked) / 1000)}`);

  marked = performance.now();
  rendered.mockInput.pressEnter();
  await settle();
  await rendered.waitForFrame((frame) => frame.includes("sending"), PATIENT);
  await rendered.flush();
  console.log(`  decision to submitted     ${ms((performance.now() - marked) / 1000)}`);

  core.push(event("permission.resolved",
    { id: "perm-m1", session_id: "s1", choice: "deny" }));
  await settle();
  await rendered.waitForFrame((frame) => !frame.includes("Permission needed"),
                              PATIENT);
  await rendered.flush();

  const form = {
    id: "ask-m1", session_id: "s1", title: "one question",
    questions: [{ header: "approach", prompt: "Which approach?",
                  multiple: false,
                  options: [{ id: "Refactor", label: "Refactor" },
                            { id: "Replace", label: "Replace" }] }],
  };
  marked = performance.now();
  core.push(event("question.requested", form));
  await settle();
  await rendered.waitForFrame((frame) => frame.includes("Which approach?"),
                              PATIENT);
  await rendered.flush();
  console.log(`  question form open        ${ms((performance.now() - marked) / 1000)}`);

  core.push(event("question.resolved", { id: "ask-m1", session_id: "s1" }));
  await settle();
  await rendered.waitForFrame((frame) => !frame.includes("Which approach?"),
                              PATIENT);
  await rendered.flush();

  // One mode transition, key to repainted confirmation and back. A single
  // press rather than a repeat: see the note above about Tab in this harness.
  marked = performance.now();
  rendered.mockInput.pressTab();
  await settle();
  await rendered.waitForFrame((frame) => frame.includes("[PLAN]"), PATIENT);
  await rendered.flush();
  console.log(`  mode key to confirmed     ${ms((performance.now() - marked) / 1000)}`);

  const rss = process.memoryUsage().rss;
  console.log(`  resident after all of it  ${mib(rss)}`);
  const before = process.cpuUsage();
  await Bun.sleep(3_000);
  const after = process.cpuUsage(before);
  console.log(`  CPU over 3 s idle         `
    + `${((after.user + after.system) / 1e6).toFixed(3)} s`);

  await client.close();
  process.exit(0);
}

void main();
