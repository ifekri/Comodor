/**
 * The interface, in an actual OpenTUI renderer.
 *
 * Reducer tests prove the logic and cannot prove the thing this migration
 * exists for. The previous interface advertised `ctrl+s` and `esc` for
 * commands that did nothing, and every unit test around it passed — because
 * what was broken was the join between a key arriving from a terminal and a
 * command running, and nothing exercised that join.
 *
 * So these drive the real renderer: real key bytes through `mockInput`, real
 * clicks through `mockMouse`, and assertions against the characters actually
 * on the screen. They need Bun, because OpenTUI binds its renderer through
 * `bun:ffi`.
 *
 *     bun test apps/tui/test/renderer.test.tsx
 *
 * The core is a loopback in memory rather than a process: what is under test
 * is the interface, and a real core is exercised by `tests/test_core_stdio.py`
 * and by `orphan.test.ts` beside this file.
 */

import { describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";

import { CoreClient, type Transport } from "@comodor/client";
import { PROTOCOL_VERSION, response, event } from "@comodor/protocol";

import { App } from "../../src/App.tsx";

// --------------------------------------------------------------------------- //
// a core, in memory
// --------------------------------------------------------------------------- //

/** Answers the handshake and keeps a session whose mode it actually tracks. */
class FakeCore implements Transport {
  readonly sent: Array<Record<string, unknown>> = [];
  mode = "act";
  /** Turns accepted so far, so `session.send` hands back a real correlator. */
  turns = 0;
  turn = "";
  /** Set by a test to make every send fail, as a busy session does. */
  refuseSends = false;
  /** Set by a test to make every permission reply fail, as a stale one does. */
  refuseReplies = false;
  /** Set by a test to take the reply but hold back the resolution event. */
  holdResolutions = false;
  /** Whether a turn is running. A prompt is only ever raised inside one. */
  busy = false;
  /** Set by a test to hold mode requests until it releases them. */
  holdModes = false;
  heldModes: Array<{ id: string; mode: string }> = [];
  /** What `model.get` reports and `model.set` changes. */
  model = "fake-1";
  /** What `model.list` offers. A test narrows it to model a thin provider. */
  catalogue: string[] = ["fake-1", "fake-fast", "qwen3:8b"];
  /** What `session.history` lists and `session.open` restores. */
  stored: Array<{ id: string; title: string; messages: number;
                  updatedAt: number;
                  transcript: Array<{ role: string; text: string }> }> = [];
  /** Every live session `session.open` has produced, in order. */
  opened: Array<Record<string, unknown>> = [];
  /** What the handshake advertises. A test narrows it to model an older core. */
  capabilities: string[] = ["streaming", "questions", "permissions", "modes",
                            "tool_events", "tasks", "delegates", "usage"];
  /** What `delegate.stop` answers. False models "it had already settled". */
  stopAnswer = true;
  /** What `session.snapshot` answers with. */
  snapshot: Record<string, unknown> = {
    session: { id: "s1", mode: "act", workspace: "/work/project", busy: false },
    revision: 0, messages: [], tools: [],
  };
  private seq = 0;
  private waiting: Array<(line: string | null) => void> = [];
  private queued: string[] = [];
  private done = false;
  /** Set by a test to intercept a method instead of answering normally. */
  intercept?: (method: string, params: Record<string, unknown>,
                id: string) => boolean;

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
    const message = JSON.parse(line) as Record<string, unknown>;
    this.sent.push(message);
    const id = String(message["id"]);
    const method = String(message["method"]);
    const params = (message["params"] ?? {}) as Record<string, unknown>;

    if (this.intercept?.(method, params, id)) return;

    if (method === "client.hello") {
      this.push(response(id, {
        protocol_version: PROTOCOL_VERSION,
        core: { name: "fake-core", version: "0" },
        capabilities: this.capabilities,
      }));
      return;
    }
    if (method === "session.create") {
      this.push(response(id, { session: this.session() }));
      return;
    }
    if (method === "session.send") {
      this.turns += 1;
      const turnId = `t${this.turns}`;
      this.turn = turnId;
      if (this.refuseSends) {
        this.push({ version: PROTOCOL_VERSION, type: "error", id,
                    error: { code: "not_allowed",
                             message: "that session is already working" } });
        return;
      }
      this.push(response(id, { accepted: true, turn_id: turnId }));
      return;
    }
    if (method === "session.snapshot") {
      // A real core keeps counting from the state it just described, so the
      // events that follow a snapshot are above its revision rather than
      // replaying numbers the client has already applied.
      const at = Number(this.snapshot["revision"] ?? 0);
      if (at > this.seq) this.seq = at;
      this.push(response(id, { snapshot: this.snapshot }));
      return;
    }
    if (method === "question.answer") {
      // A real core resolves the request when it takes the answer, and the
      // card is supposed to go when that arrives — not when Enter is pressed.
      // A fake that answered without resolving would let a client believe it
      // had dismissed the form itself.
      this.push(response(id, { ok: true }));
      this.emit("question.resolved",
        { id: String(params["id"]), session_id: "s1",
          ...(params["cancelled"] ? { cancelled: true } : {}) });
      return;
    }
    if (method === "permission.reply") {
      if (this.refuseReplies) {
        this.push({ version: PROTOCOL_VERSION, type: "error", id,
                    error: { code: "unknown_request",
                             message: "nothing is waiting under that id" } });
        return;
      }
      this.push(response(id, { ok: true }));
      if (!this.holdResolutions) {
        this.emit("permission.resolved",
          { id: String(params["id"]), session_id: "s1",
            choice: String(params["choice"]) });
      }
      return;
    }
    if (method === "session.set_mode") {
      if (this.holdModes) {
        // Held rather than answered, so a test can look at the screen while a
        // request is genuinely in flight.
        this.heldModes.push({ id, mode: String(params["mode"]) });
        return;
      }
      // The core is the authority. The client must not move its own label;
      // it waits for the event, which is what these tests then assert on.
      this.mode = String(params["mode"]);
      this.push(response(id, { session: this.session() }));
      this.push(event("mode.changed",
        { session_id: "s1", mode: this.mode }));
      this.push(event("session.updated", { session: this.session() }));
      return;
    }
    if (method === "delegate.stop") {
      // Answered, and nothing painted: what the delegate becomes is the
      // lifecycle event the test emits next, exactly as a real core's would
      // arrive. A fake that emitted `stopped` here would let a client pass
      // its tests while believing its own request was the terminal state.
      this.push(response(id, { stopped: this.stopAnswer }));
      return;
    }
    if (method === "model.get") {
      this.push(response(id, { provider: "fake", model: this.model,
                               configured: true }));
      return;
    }
    if (method === "session.history") {
      this.push(response(id, {
        sessions: this.stored.map((entry) => ({
          id: entry.id, title: entry.title, messages: entry.messages,
          updated_at: entry.updatedAt, compactions: 0, cost_usd: 0,
        })),
      }));
      return;
    }
    if (method === "session.open") {
      const wanted = String(params["session_id"] ?? "");
      const entry = this.stored.find((item) => item.id === wanted);
      if (!entry) {
        this.push({ version: PROTOCOL_VERSION, type: "error", id,
                    error: { code: "not_allowed",
                             message: `no stored session named '${wanted}'` } });
        return;
      }
      // The live session is new; the transcript it opens with is the store's.
      const live = { id: `live-${wanted}`, mode: "act",
                     workspace: "/work/project", busy: false };
      this.opened.push(live);
      this.snapshot = {
        session: live, revision: entry.transcript.length,
        messages: entry.transcript.map((message, at) => ({
          message_id: `restored-${at + 1}`, turn_id: "restored",
          role: message.role, text: message.text, status: "completed",
          started_seq: at + 1,
        })),
        tools: [],
      };
      this.push(response(id, { session: live }));
      return;
    }
    if (method === "model.list") {
      this.push(response(id, { provider: "fake", model: this.model,
                               configured: true,
                               models: [...this.catalogue] }));
      return;
    }
    if (method === "model.set") {
      const wanted = String(params["model"] ?? "");
      if (!this.catalogue.includes(wanted)) {
        this.push({ version: PROTOCOL_VERSION, type: "error", id,
                    error: { code: "not_allowed",
                             message: `no model named '${wanted}'` } });
        return;
      }
      // The core is the authority here too: the label moves on the event,
      // never on the request.
      this.model = wanted;
      this.push(response(id, { provider: "fake", model: this.model,
                               configured: true }));
      this.emit("model.changed",
        { session_id: "s1", provider: "fake", model: this.model,
          configured: true });
      return;
    }
    this.push(response(id, {}));
  }

  close(): void {
    this.done = true;
    for (const waiter of this.waiting.splice(0)) waiter(null);
  }

  /** Answer every mode request held so far, as the core eventually would. */
  releaseModes(): void {
    for (const held of this.heldModes.splice(0)) {
      this.mode = held.mode;
      this.push(response(held.id, { session: this.session() }));
      this.push(event("mode.changed", { session_id: "s1", mode: this.mode }));
      this.push(event("session.updated", { session: this.session() }));
    }
  }

  /** One event, numbered as a real core numbers them. */
  emit(name: string, params: Record<string, unknown>): void {
    this.seq += 1;
    this.push(event(name as never, params, this.seq));
  }

  push(message: unknown): void {
    const line = JSON.stringify(message);
    const next = this.waiting.shift();
    if (next) next(line);
    else this.queued.push(line);
  }

  /** The workspace the session reports. A test lengthens it to crowd the header. */
  workspace = "/work/project";

  session() {
    return { id: "s1", mode: this.mode, workspace: this.workspace,
             busy: this.busy };
  }

  /** Every method name the client has sent, for asserting on the path taken. */
  methods(): string[] {
    return this.sent.map((message) => String(message["method"]));
  }

  private take(): Promise<string | null> {
    const ready = this.queued.shift();
    if (ready !== undefined) return Promise.resolve(ready);
    if (this.done) return Promise.resolve(null);
    return new Promise((resolve) => this.waiting.push(resolve));
  }
}

async function screen(width = 100, height = 30,
                      sessionId?: string,
                      snapshot?: Record<string, unknown>,
                      capabilities?: string[],
                      mode?: string) {
  const core = new FakeCore();
  if (snapshot) core.snapshot = snapshot;
  if (capabilities) core.capabilities = capabilities;
  // What `session.create` reports. A string rather than a Mode on purpose:
  // the core passes a configured name through as it found it.
  if (mode !== undefined) core.mode = mode;
  const client = new CoreClient(core, { timeoutMs: 5_000 });
  await client.start();

  let quit = false;
  const rendered = await testRender(
    <App client={client} onQuit={() => { quit = true; }} sessionId={sessionId} />,
    { width, height });

  await rendered.flush();
  // The session arrives asynchronously; wait for the workspace to appear
  // rather than for a number of frames. A too-small terminal never shows it
  // — its floor notice is the readiness sign there.
  await rendered.waitForFrame((frame) =>
    frame.includes("project") || frame.includes("Too small"));

  return {
    ...rendered,
    core,
    client,
    quit: () => quit,
    frame: () => rendered.captureCharFrame(),
    /** Every mode the client has asked the core to set, in order. */
    sentModes: () => core.sent
      .filter((message) => message["method"] === "session.set_mode")
      .map((message) =>
        String((message["params"] as Record<string, unknown>)["mode"])),
    /** Every delegate the client has asked the core to stop, in order. */
    sentStops: () => core.sent
      .filter((message) => message["method"] === "delegate.stop")
      .map((message) =>
        String((message["params"] as Record<string, unknown>)["delegate_id"])),
  };
}

/**
 * How long to wait for a mode to appear on screen.
 *
 * A mode change is a round trip — key, `session.set_mode`, `mode.changed`,
 * re-render — and the default twenty render passes is not always enough for
 * the event to have been *read* by the client, never mind painted. Twenty
 * passes happened to be enough until an unrelated string in the mode bar got
 * three characters longer, at which point the third switch in a cycle started
 * arriving one pass late and the test blamed Tab.
 *
 * The lesson is in the number: this waits for the thing it is asserting
 * about, with enough patience that a normal scheduling difference is not
 * read as a broken key.
 */
const MODE_PASSES = { maxPasses: 200 } as const;

/**
 * Press Escape, and let the terminal decide it was one.
 *
 * A lone `ESC` byte is the first byte of every arrow key and function key, so
 * a decoder cannot know it was Escape until either a sequence completes or
 * enough time passes without one. Sending it and immediately sending another
 * key produces `Alt+<that key>` — which is correct terminal behaviour, and is
 * what these tests saw before the wait was added.
 *
 * Real people are slower than a test, so this is a property of the harness
 * rather than of the interface. It is written down because "Escape did
 * nothing" is otherwise a mystery.
 */
async function pressEscape(view: { mockInput: { pressEscape: () => void };
                                   flush: () => Promise<void> }): Promise<void> {
  view.mockInput.pressEscape();
  await Bun.sleep(80);
  await view.flush();
}

/**
 * Let React run the updates a key handler queued, then flush.
 *
 * React schedules its work on the macrotask queue; `flush` turns the
 * microtask queue and paints. So a `setState` made inside a key handler is
 * still queued when `flush` returns, and a test that only awaited frames
 * would spin on a screen React had not been given the chance to change —
 * which is exactly what it looks like when a key does nothing.
 *
 * `sleep(0)` is one turn of that queue, not a guess at a duration. It is a
 * property of the harness, not of the interface: the real client runs a
 * renderer loop that turns it constantly.
 */
async function letReactRun(view: { flush: () => Promise<void> }): Promise<void> {
  await Bun.sleep(0);
  await view.flush();
}

/** Where a piece of text sits on screen, so a click can be aimed at it. */
function locate(frame: string, needle: string): { x: number; y: number } {
  const rows = frame.split("\n");
  for (let y = 0; y < rows.length; y += 1) {
    const x = (rows[y] ?? "").indexOf(needle);
    if (x >= 0) return { x: x + Math.floor(needle.length / 2), y };
  }
  throw new Error(`"${needle}" is not on screen:\n${frame}`);
}

/**
 * Wait for text the way the wall clock measures it, not render passes.
 *
 * `waitForFrame` ends early when the renderer goes quiet — the right call
 * for a key press, wrong for a multi-hop flow: the pickers ask the core,
 * then the open asks again, and between the two round trips the renderer is
 * idle with a frame that predates both. A wall-clock poll still asserts the
 * content; it just cannot mistake "nothing rendering" for "nothing coming".
 */
async function waitForText(view: View, needle: string,
                           timeoutMs = 5_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const frame = view.frame();
    if (frame.includes(needle)) return frame;
    if (Date.now() > deadline) {
      throw new Error(`"${needle}" never appeared:\n${frame}`);
    }
    await Bun.sleep(10);
  }
}

// --------------------------------------------------------------------------- //

describe("the interface starts", () => {
  test("it draws, and shows where it is pointed", async () => {
    const view = await screen();
    const frame = view.frame();

    expect(frame).toContain("Comodor");
    expect(frame).toContain("project");
    // The composer is the thing you can act on, so it is on screen from the
    // first frame rather than after a keystroke.
    expect(frame).toContain("ask for anything");
    view.client.close();
  });

  test("the composer takes what is typed", async () => {
    const view = await screen();
    await view.mockInput.typeText("fix the parser");
    await view.flush();

    expect(view.frame()).toContain("fix the parser");
    view.client.close();
  });
});

describe("modes", () => {
  test.each([100, 160])("Tab walks ACT to PLAN to ASK and back at %i", async (width) => {
    const view = await screen(width as number);
    expect(view.frame()).toContain("[ACT]");

    view.mockInput.pressTab();
    await view.waitForFrame((frame) => frame.includes("[PLAN]"), MODE_PASSES);
    expect(view.core.mode).toBe("plan");

    view.mockInput.pressTab();
    await view.waitForFrame((frame) => frame.includes("[ASK]"), MODE_PASSES);

    view.mockInput.pressTab();
    // Deliberately waiting on the core rather than the label, to tell a mode
    // that did not change from a label that did not render.
    await view.waitForFrame(() => view.core.mode === "act");
    await view.flush();
    expect(view.frame()).toContain("[ACT]");
    view.client.close();
  });

  test("Shift+Tab walks the other way", async () => {
    const view = await screen();

    view.mockInput.pressTab({ shift: true });
    await view.waitForFrame((frame) => frame.includes("[ASK]"), MODE_PASSES);
    expect(view.core.mode).toBe("ask");

    view.mockInput.pressTab({ shift: true });
    await view.waitForFrame((frame) => frame.includes("[PLAN]"), MODE_PASSES);
    view.client.close();
  });

  test("the label follows the core, not the key press", async () => {
    // The client must not move its own label. A core that refuses leaves the
    // interface showing what is true rather than what was hoped for.
    const view = await screen();
    view.core.intercept = (method, _params, id) => {
      if (method !== "session.set_mode") return false;
      view.core.push({ version: PROTOCOL_VERSION, type: "error", id,
                       error: { code: "not_allowed", message: "no" } });
      return true;
    };

    view.mockInput.pressTab();
    await view.flush();
    await view.waitForVisualIdle();

    expect(view.frame()).toContain("[ACT]");
    view.client.close();
  });

  // Every segment, because "the mouse works" is a claim about all three and
  // the one that is already selected is the one most likely to be wired
  // differently by accident.
  for (const [label, mode] of [["PLAN", "plan"], ["ASK", "ask"],
                               ["ACT", "act"]] as const) {
    test(`clicking ${label} asks the core for ${mode}`, async () => {
      const view = await screen();
      // Start somewhere else, so clicking ACT is a real change rather than a
      // no-op that would pass whatever the click did.
      if (mode === "act") {
        view.mockInput.pressTab();
        await view.waitForFrame((frame) => frame.includes("[PLAN]"), MODE_PASSES);
      }

      const at = locate(view.frame(), label);
      await view.mockMouse.click(at.x, at.y);
      await view.waitForFrame((frame) => frame.includes(`[${label}]`),
                              MODE_PASSES);

      expect(view.core.mode).toBe(mode);
      // The same command the keyboard runs, not a second path into the core.
      expect(view.sentModes()[view.sentModes().length - 1]).toBe(mode);
      view.client.close();
    });
  }

  test("a click does not move the label before the core confirms", async () => {
    const view = await screen();
    view.core.intercept = (method, _params, id) => {
      if (method !== "session.set_mode") return false;
      view.core.push({ version: PROTOCOL_VERSION, type: "error", id,
                       error: { code: "not_allowed", message: "no" } });
      return true;
    };

    const at = locate(view.frame(), "PLAN");
    await view.mockMouse.click(at.x, at.y);
    await view.flush();
    await view.waitForVisualIdle();

    expect(view.frame()).toContain("[ACT]");
    view.client.close();
  });

  test("a mode the client does not know is named, not rendered as ACT", async () => {
    // `agent.mode: yolo` in a config file — the user's, or a repository's,
    // which anyone can check out. The core keeps the name and refuses every
    // tool under it; the interface used to die on `MODES["yolo"]` at first
    // paint, which turned a typo into a stack trace. It must draw, say what
    // is wrong, bracket nothing, and let Tab pick a real mode.
    const view = await screen(120, 30, undefined, undefined, undefined, "yolo");
    await view.waitForFrame((frame) => frame.includes("is not a mode"));

    const frame = view.frame();
    expect(frame).toContain('"yolo" is not a mode');
    expect(frame).not.toContain("[ACT]");
    expect(frame).toContain("ask for anything");

    view.mockInput.pressTab();
    await view.waitForFrame((frame) => frame.includes("[ACT]"), MODE_PASSES);
    expect(view.core.mode).toBe("act");
    view.client.close();
  });
});

describe("the command palette", () => {
  test("Ctrl+K opens it", async () => {
    const view = await screen();
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));

    expect(view.frame()).toContain("Mode");
    view.client.close();
  });

  test("Up and Down move the selection, and it is visible", async () => {
    const view = await screen();
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));

    const first = view.frame();
    // The marker says which row is selected without relying on colour.
    expect(first).toContain("›");

    view.mockInput.pressArrow("down");
    await view.flush();
    await view.waitForVisualIdle();
    const second = view.frame();

    expect(second).not.toBe(first);
    expect(markedRow(second)).not.toBe(markedRow(first));

    view.mockInput.pressArrow("up");
    await view.flush();
    await view.waitForVisualIdle();
    expect(markedRow(view.frame())).toBe(markedRow(first));
    view.client.close();
  });

  test("Enter runs the selected command, not the first one", async () => {
    // The bug this pins: Enter used to run results[0] whatever was
    // highlighted, so Down did nothing and the palette lied.
    const view = await screen();
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    // `mode:` rather than `mode`, so every result names a mode outright and
    // the row below the first is one the session is not already in. Picking
    // the mode already confirmed is correctly a no-op — intent that matches
    // the core is not a request — and the test would then be asserting
    // against the one case that sends nothing.
    await view.mockInput.typeText("mode:");
    await view.flush();
    await view.waitForVisualIdle();

    const chosen = markedRow(view.frame());
    view.mockInput.pressArrow("down");
    await view.flush();
    await view.waitForVisualIdle();
    const second = markedRow(view.frame());
    expect(second).not.toBe(chosen);

    view.mockInput.pressEnter();
    await letReactRun(view);
    await view.waitForVisualIdle();
    // The round trip is a render cycle longer than it was: a mode command
    // records intent, and one coordinator turns intent into the request.
    await view.waitForFrame((frame) => frame.includes("[ASK]"), MODE_PASSES);

    // It closed, and it asked the core for the mode the *second* row named.
    expect(view.frame()).not.toContain("type a command");
    const asked = view.sentModes();
    expect(asked.length).toBeGreaterThan(0);
    expect(second.toLowerCase()).toContain(asked[asked.length - 1] as string);
    view.client.close();
  });

  test("Esc closes it without running anything", async () => {
    const view = await screen();
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));

    await pressEscape(view);
    await view.waitForVisualIdle();

    expect(view.frame()).not.toContain("type a command");
    expect(view.core.methods()).not.toContain("session.set_mode");
    view.client.close();
  });

  test("a query that matches nothing says so rather than showing everything",
       async () => {
    const view = await screen();
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("zzzzz");
    await view.flush();
    await view.waitForVisualIdle();

    expect(view.frame()).toContain("Nothing matches");
    view.client.close();
  });
});

describe("the model in the header", () => {
  test("the provider and model come from the core, and move when it says",
       async () => {
    const view = await screen();
    // Asked at connect: the header is not a guess from a config file.
    await view.waitForFrame((frame) => frame.includes("fake · fake-1"));
    expect(view.core.methods()).toContain("model.get");

    // A switch anywhere — this client, another client, the core itself —
    // announces itself the same way, and only then does the label move.
    view.core.emit("model.changed", { session_id: "s1", provider: "fake",
                                      model: "qwen3:8b", configured: true });
    await view.waitForFrame((frame) => frame.includes("fake · qwen3:8b"));
    view.client.close();
  });

  test("a narrow header keeps the model and drops the provider", async () => {
    const view = await screen(60);
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    expect(view.frame()).not.toContain("fake · fake-1");
    view.client.close();
  });
});

describe("the model chooser", () => {
  test("opens from the palette with the core's list, current model marked",
       async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));

    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("model");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    // The chooser's list is a round trip: ask the core, then draw. An idle
    // renderer has no frame to wait on until the answer lands — a wall-clock
    // poll cannot mistake "nothing rendering" for "nothing coming".
    await waitForText(view, "type a model");

    const frame = view.frame();
    // Asked when opened — never cached from some earlier run of the overlay.
    expect(view.core.methods()).toContain("model.list");
    expect(frame).toContain("fake-1");
    expect(frame).toContain("(current)");
    expect(frame).toContain("qwen3:8b");
    view.client.close();
  });

  test("Enter on a highlighted row asks the core; the header waits for it",
       async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("model");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    // The chooser's list is a round trip: ask the core, then draw. An idle
    // renderer has no frame to wait on until the answer lands — a wall-clock
    // poll cannot mistake "nothing rendering" for "nothing coming".
    await waitForText(view, "type a model");

    // The current model opens highlighted; Down picks the row beneath it.
    view.mockInput.pressArrow("down");
    await view.flush();
    await view.waitForVisualIdle();
    expect(markedRow(view.frame())).toContain("fake-fast");
    view.mockInput.pressEnter();
    await letReactRun(view);

    // The overlay closed, the request went out, and the header moved only
    // because the core's own event arrived — the request alone moved nothing
    // on screen.
    expect(view.frame()).not.toContain("type a model");
    await view.waitForFrame((frame) => frame.includes("fake · fake-fast"));
    expect(view.core.model).toBe("fake-fast");
    view.client.close();
  });

  test("a refused switch leaves the header alone and says why", async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    view.core.catalogue = ["fake-1", "ghost-model"];
    view.core.intercept = (method, _params, id) => {
      if (method !== "model.set") return false;
      view.core.push({ version: PROTOCOL_VERSION, type: "error", id,
                       error: { code: "not_allowed",
                                message: "the provider has no such model" } });
      return true;
    };

    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("model");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    // The chooser's list is a round trip: ask the core, then draw. An idle
    // renderer has no frame to wait on until the answer lands — a wall-clock
    // poll cannot mistake "nothing rendering" for "nothing coming".
    await waitForText(view, "type a model");
    view.mockInput.pressArrow("down");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    await letReactRun(view);

    const frame = view.frame();
    expect(frame).toContain("fake · fake-1");
    expect(frame).not.toContain("ghost-model");
    expect(frame).toContain("the provider has no such model");
    view.client.close();
  });

  test("Escape closes it without asking for anything", async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("model");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    // The chooser's list is a round trip: ask the core, then draw. An idle
    // renderer has no frame to wait on until the answer lands — a wall-clock
    // poll cannot mistake "nothing rendering" for "nothing coming".
    await waitForText(view, "type a model");

    await pressEscape(view);
    await view.waitForVisualIdle();

    expect(view.frame()).not.toContain("type a model");
    expect(view.core.methods()).not.toContain("model.set");
    view.client.close();
  });

  test("a click chooses the row it lands on", async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("model");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    // The chooser's list is a round trip: ask the core, then draw. An idle
    // renderer has no frame to wait on until the answer lands — a wall-clock
    // poll cannot mistake "nothing rendering" for "nothing coming".
    await waitForText(view, "type a model");

    const at = locate(view.frame(), "qwen3:8b");
    await view.mockMouse.click(at.x, at.y);
    await view.waitForFrame((frame) => frame.includes("fake · qwen3:8b"));

    expect(view.core.model).toBe("qwen3:8b");
    view.client.close();
  });

  test("a permission card outranks the chooser", async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("model");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    // The chooser's list is a round trip: ask the core, then draw. An idle
    // renderer has no frame to wait on until the answer lands — a wall-clock
    // poll cannot mistake "nothing rendering" for "nothing coming".
    await waitForText(view, "type a model");

    await emitRun(view, "permission.requested", { ...PERMISSION });
    expect(view.frame()).toContain("Permission needed");

    // Enter belongs to the card, not to the model under the cursor.
    view.mockInput.pressEnter();
    await letReactRun(view);
    expect(view.core.methods()).not.toContain("model.set");
    // The card took the press and resolved; the chooser is untouched by it.
    await view.waitForFrame((frame) => !frame.includes("Permission needed"));
    view.client.close();
  });
});

describe("questions", () => {
  const form = {
    id: "ask-1",
    session_id: "s1",
    title: "2 questions before I start",
    questions: [
      { header: "approach", prompt: "Which approach?", multiple: false,
        options: [
          { id: "Refactor", label: "Refactor" },
          { id: "Replace", label: "Replace" },
          { id: "Something else", label: "Something else", free: true },
        ] },
      { header: "when", prompt: "When?", multiple: true,
        options: [
          { id: "Now", label: "Now" },
          { id: "After the release", label: "After the release" },
          { id: "Something else", label: "Something else", free: true },
        ] },
    ],
  };

  async function asked() {
    const view = await screen();
    view.core.push(event("question.requested", form as never));
    await view.waitForFrame((frame) => frame.includes("Which approach?"));
    return view;
  }

  test("a form renders with its options and its position", async () => {
    const view = await asked();
    const frame = view.frame();

    expect(frame).toContain("Which approach?");
    expect(frame).toContain("Refactor");
    expect(frame).toContain("1 of 2");
    view.client.close();
  });

  test("the keyboard chooses an option", async () => {
    const view = await asked();
    view.mockInput.pressArrow("down");
    view.mockInput.pressKey(" ");
    await view.flush();
    await view.waitForVisualIdle();

    // A single-choice question draws a filled radio for what is chosen.
    expect(view.frame()).toContain("(*) Replace");
    view.client.close();
  });

  test("left and right walk between the questions of a form", async () => {
    const view = await asked();
    view.mockInput.pressArrow("right");
    await view.waitForFrame((frame) => frame.includes("When?"));

    expect(view.frame()).toContain("2 of 2");
    view.mockInput.pressArrow("left");
    await view.waitForFrame((frame) => frame.includes("Which approach?"));
    view.client.close();
  });

  test("a multi-select question uses checkboxes and takes several", async () => {
    const view = await asked();
    view.mockInput.pressArrow("right");
    await view.waitForFrame((frame) => frame.includes("When?"));

    view.mockInput.pressKey(" ");
    view.mockInput.pressArrow("down");
    view.mockInput.pressKey(" ");
    await view.flush();
    await view.waitForVisualIdle();

    const frame = view.frame();
    expect(frame).toContain("[x] Now");
    expect(frame).toContain("[x] After the release");
    view.client.close();
  });

  test("a custom answer can be typed and is sent", async () => {
    const view = await asked();
    // Down twice reaches the write-your-own row; space opens the field.
    view.mockInput.pressArrow("down");
    view.mockInput.pressArrow("down");
    view.mockInput.pressKey(" ");
    // Wait for the cursor, not the placeholder: the placeholder is on screen
    // before the row is chosen, so waiting on it returns while the space is
    // still queued and the typing then lands nowhere.
    await view.waitForFrame((frame) => frame.includes("▌"));

    await view.mockInput.typeText("rewrite the parser");
    // Waited for rather than asserted after one flush: the state is set the
    // moment the key arrives, and the paint is a frame behind it.
    await view.waitForFrame((frame) => frame.includes("rewrite the parser"));

    view.mockInput.pressEnter();
    await view.flush();
    await view.waitForVisualIdle();

    const sent = view.core.sent.find(
      (message) => message["method"] === "question.answer");
    expect(sent).toBeDefined();
    const params = sent!["params"] as { answers: Array<Record<string, unknown>> };
    expect(params.answers[0]?.["written"]).toBe("rewrite the parser");
    view.client.close();
  });

  test("Esc cancels the form and says so to the core", async () => {
    const view = await asked();
    await pressEscape(view);
    await view.waitForVisualIdle();

    const sent = view.core.sent.find(
      (message) => message["method"] === "question.answer");
    expect((sent!["params"] as Record<string, unknown>)["cancelled"]).toBe(true);
    expect(view.frame()).not.toContain("Which approach?");
    view.client.close();
  });
});

describe("at every width", () => {
  for (const width of [160, 120, 100, 80, 60]) {
    test(`${width} columns draws without spilling`, async () => {
      const view = await screen(width, 30);
      const frame = view.frame();

      for (const row of frame.split("\n")) {
        expect(row.length).toBeLessThanOrEqual(width);
      }
      // The two things that must never be off screen: what you type into,
      // and which mode you are in.
      expect(frame).toContain("ask for anything");
      expect(frame).toContain("[ACT]");
      view.client.close();
    });
  }

  test("a long workspace path gives way to the model, not the reverse", async () => {
    // What the installed-package smoke hit: at 80 columns, with a path a
    // few characters too long, the header ran out of room on the right and
    // the model read `comodor-` instead of `comodor-demo`. The path is the
    // part that can be shortened without becoming a different fact.
    const core = new FakeCore();
    core.model = "comodor-demo";
    core.workspace = "/home/somebody/.local/share/tmp/a-rather-long-name/somewhere-else";
    const client = new CoreClient(core, { timeoutMs: 5_000 });
    await client.start();
    const view = await testRender(
      <App client={client} onQuit={() => {}} />, { width: 80, height: 24 });
    await view.flush();
    await view.waitForFrame((frame) => frame.includes("comodor-demo"));

    const header = view.captureCharFrame().split("\n")[0] ?? "";
    expect(header).toContain("fake · comodor-demo");
    expect(header).toContain("…");
    expect(header).toContain("somewhere-else");
    expect(header.length).toBeLessThanOrEqual(80);
    client.close();
  });

  test("resizing keeps the composer and the mode on screen", async () => {
    const view = await screen(160, 30);
    view.resize(60, 20);
    await view.flush();
    await view.waitForVisualIdle();

    const frame = view.frame();
    expect(frame).toContain("[ACT]");
    for (const row of frame.split("\n")) {
      expect(row.length).toBeLessThanOrEqual(60);
    }
    view.client.close();
  });
});

describe("at every size", () => {
  // Width and height together: a terminal is a box, and the narrow-and-tall
  // versus wide-and-short corners are where chrome eats the conversation.
  for (const [width, height] of [[160, 50], [120, 40], [100, 30], [80, 24],
                                 [60, 20]] as const) {
    test(`${width}×${height} draws without spilling`, async () => {
      const view = await screen(width, height);
      const frame = view.frame();

      const rows = frame.split("\n");
      // The captured frame carries the harness's trailing line: what matters
      // is that no row is wider than the terminal and every row fits.
      expect(rows.length).toBeLessThanOrEqual(height + 1);
      for (const row of rows) {
        expect(row.length).toBeLessThanOrEqual(width);
      }
      expect(frame).toContain("ask for anything");
      expect(frame).toContain("[ACT]");
      view.client.close();
    });
  }

  test("a genuinely too-small terminal says so instead of colliding",
       async () => {
    const view = await screen(30, 8);
    await view.flush();
    await view.waitForVisualIdle();

    const frame = view.frame();
    expect(frame).toContain("Too small");
    expect(frame).toContain("ctrl+d Quit");
    // Nothing behind the notice may bleed through: no composer, no mode bar.
    expect(frame).not.toContain("ask for anything");
    expect(frame).not.toContain("[ACT]");
    view.client.close();
  });

  test("a blocking decision stays reachable below the floor", async () => {
    // The floor exists to stop collisions — but a permission the core is
    // waiting on outranks it. A tiny terminal cannot be a reason the person
    // cannot say no.
    const view = await screen(30, 8);
    await view.flush();
    await emitRun(view, "permission.requested", { ...PERMISSION });

    const frame = view.frame();
    expect(frame).toContain("Permission needed");
    expect(frame).toContain("[Deny]");

    view.mockInput.pressEnter();
    await letReactRun(view);
    const answered = view.core.sent.filter(
      (message) => message["method"] === "permission.reply");
    expect(answered.length).toBe(1);
    view.client.close();
  });

  test("growing past the floor brings the whole screen back", async () => {
    const view = await screen(30, 8);
    await view.flush();
    await view.waitForVisualIdle();
    expect(view.frame()).toContain("Too small");

    view.resize(100, 30);
    await view.flush();
    await view.waitForVisualIdle();
    const frame = view.frame();
    expect(frame).toContain("ask for anything");
    expect(frame).toContain("[ACT]");
    view.client.close();
  });

  test("a short terminal still fits the chooser without spilling", async () => {
    const view = await screen(80, 14);
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("model");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    await letReactRun(view);
    await view.waitForFrame((frame) => frame.includes("type a model"));

    const frame = view.frame();
    // The overlay is bounded by the height, so its hint row never falls off.
    expect(frame).toContain("esc Close");
    expect(frame.split("\n").length).toBeLessThanOrEqual(15);
    view.client.close();
  });
});

describe("leaving", () => {
  test("Ctrl+D quits", async () => {
    const view = await screen();
    view.mockInput.pressKey("d", { ctrl: true });
    await view.flush();

    expect(view.quit()).toBe(true);
    view.client.close();
  });
});

describe("the core stops answering", () => {
  test("a dead core says so on an idle screen, and quitting stays possible",
       async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    // Killed mid-nothing: the failure mode is a frozen *good* screen, which
    // is worse than a frozen empty one, because it still looks alive.
    view.core.close();
    await view.waitForFrame((frame) =>
      frame.includes("The core is not answering"));

    const frame = view.frame();
    expect(frame).toContain("ctrl+d Quit");
    // Input is off the table: the composer must not pretend it listens.
    view.mockInput.typeText("still here?");
    await view.flush();
    expect(view.frame()).toContain("The core is not answering");
    view.mockInput.pressKey("d", { ctrl: true });
    await view.flush();
    expect(view.quit()).toBe(true);
    view.client.close();
  });

  test("nothing claiming to be in flight survives as live", async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    // A turn mid-stream when the core dies: the in-flight message must not
    // keep drawing its spinner on a dead pipe. The honest state is "lost".
    await emitRun(view, "message.started", { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "half an answer" });
    view.core.close();
    // The reader loop ending is as async as any event: the loss is known on
    // the next turn, so the loop is turned before watching for its frame.
    await letReactRun(view);
    await view.waitForFrame((frame) =>
      frame.includes("The core is not answering"));

    expect(view.frame()).not.toContain("streaming");
    view.client.close();
  });
});

// --------------------------------------------------------------------------- //
// streaming, tools and recovery — the F2 behaviours, in the real renderer
// --------------------------------------------------------------------------- //

type View = Awaited<ReturnType<typeof screen>>;

/** Emit one event and let React settle, so a frame shows what it caused. */
async function emitRun(view: View, name: string,
                       params: Record<string, unknown>): Promise<void> {
  view.core.emit(name, params);
  await letReactRun(view);
}

describe("streaming and recovery", () => {
  test("a streamed answer appears as it arrives", async () => {
    const view = await screen();
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "Parsing the " });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "fixture now" });

    expect(view.frame()).toContain("Parsing the fixture now");
    view.client.close();
  });

  test("parallel tool output stays under the tool that produced it", async () => {
    const view = await screen();
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "alpha" });
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "b", name: "bravo" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "a", text: "A1\n" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "b", text: "B1\n" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "a", text: "A2\n" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "b", text: "B2\n" });

    const frame = view.frame();
    // Each call's block is whole, in order, and carries only its own lines:
    // interleaved output drawn interleaved would put half of A under B.
    const alpha = frame.indexOf("alpha");
    const bravo = frame.indexOf("bravo");
    expect(alpha).toBeGreaterThanOrEqual(0);
    expect(bravo).toBeGreaterThan(alpha);

    const alphaBlock = frame.slice(alpha, bravo);
    expect(alphaBlock).toContain("A1");
    expect(alphaBlock).toContain("A2");
    expect(alphaBlock).not.toContain("B1");
    expect(alphaBlock).not.toContain("B2");

    const bravoBlock = frame.slice(bravo);
    expect(bravoBlock).toContain("B1");
    expect(bravoBlock).toContain("B2");
    expect(bravoBlock).not.toContain("A1");
    view.client.close();
  });

  test("a failed tool says so, and carries why", async () => {
    const view = await screen();
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "run_shell" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "a", text: "boom\n" });
    await emitRun(view, "tool.failed",
                  { turn_id: "t1", call_id: "a", error: "exit code 1" });

    const frame = view.frame();
    expect(frame).toContain("×");
    expect(frame).toContain("exit code 1");
    view.client.close();
  });

  test("a cancelled answer keeps its text and says it stopped", async () => {
    const view = await screen();
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "half an answer" });
    await emitRun(view, "message.completed",
                  { turn_id: "t1", message_id: "m1", text: "half an answer",
                    status: "cancelled" });

    const frame = view.frame();
    expect(frame).toContain("half an answer");
    expect(frame).toContain("stopped");
    view.client.close();
  });

  test("scrolling up pauses follow; new output raises the marker; end returns",
       async () => {
    const view = await screen(100, 30);
    const lines = Array.from({ length: 80 }, (_, at) => `history row ${at}`);
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: lines.join("\n") });
    await emitRun(view, "message.completed",
                  { turn_id: "t1", message_id: "m1",
                    text: lines.join("\n"), status: "completed" });

    // Following: no marker, wherever the box has pinned itself.
    expect(view.frame()).not.toContain("↓ new output");

    // A real PageUp — the mock types unknown names as text, so the escape
    // sequence itself, which the input decoder names `pageup`. Half a
    // viewport per press, so several to reach the top of a long answer.
    for (let press = 0; press < 10; press += 1) {
      view.mockInput.pressKey("\x1B[5~");
      await letReactRun(view);
    }

    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m2" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m2", text: "later words" });
    await letReactRun(view);

    // The viewport must not have been dragged down to the new content —
    // that yank is the behaviour this exists to prevent — and the marker
    // names both the fact and the way back.
    const paused = view.frame();
    expect(paused).toContain("history row 0");
    expect(paused).toContain("↓ new output");
    view.mockInput.pressKey("END");
    await letReactRun(view);
    expect(view.frame()).not.toContain("↓ new output");
    expect(view.frame()).toContain("later words");
    view.client.close();
  });

  test("the mouse wheel pauses follow the same way the keyboard does",
       async () => {
    const view = await screen(100, 30);
    const lines = Array.from({ length: 80 }, (_, at) => `history row ${at}`);
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: lines.join("\n") });
    await emitRun(view, "message.completed",
                  { turn_id: "t1", message_id: "m1",
                    text: lines.join("\n"), status: "completed" });

    await view.mockMouse.scroll(50, 12, "up");
    await letReactRun(view);

    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m2" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m2", text: "later words" });
    await letReactRun(view);

    expect(view.frame()).toContain("↓ new output");
    view.client.close();
  });

  test("clicking the marker returns to the newest output", async () => {
    // The one mouse path the docs could not yet prove. It goes through the
    // same `toTail` the End key calls, and this test is what makes the
    // difference between wired and proven.
    const view = await screen(100, 30);
    const lines = Array.from({ length: 80 }, (_, at) => `history row ${at}`);
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: lines.join("\n") });
    await emitRun(view, "message.completed",
                  { turn_id: "t1", message_id: "m1",
                    text: lines.join("\n"), status: "completed" });

    await view.mockMouse.scroll(50, 12, "up");
    await letReactRun(view);
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m2" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m2", text: "later words" });
    await letReactRun(view);
    expect(view.frame()).toContain("↓ new output");

    const at = locate(view.frame(), "↓ new output");
    await view.mockMouse.click(at.x, at.y);
    await letReactRun(view);

    const frame = view.frame();
    expect(frame).not.toContain("↓ new output");
    expect(frame).toContain("later words");
    view.client.close();
  });

  test("a refused send keeps the text, and ctrl+r sends it again", async () => {
    const view = await screen();
    view.core.refuseSends = true;

    await view.mockInput.typeText("fix the parser");
    await view.flush();
    view.mockInput.pressEnter();
    await letReactRun(view);

    const refused = view.frame();
    expect(refused).toContain("fix the parser");
    expect(refused).toContain("ctrl+r");

    // A second prompt in the same state keeps both, and refuses both.
    await view.mockInput.typeText("and the types");
    await view.flush();
    view.mockInput.pressEnter();
    await letReactRun(view);
    expect(view.frame()).toContain("and the types");

    view.core.refuseSends = false;
    view.mockInput.pressKey("r", { ctrl: true });
    await letReactRun(view);
    // Retry resends the latest unsent prompt — one press, one resend. The
    // earlier refusal is still on screen for the person to retry in turn.
    const sends = view.core.sent
      .filter((message) => message["method"] === "session.send");
    expect(sends.length).toBe(3);
    expect(view.frame()).toContain("not sent");
    view.client.close();
  });

  test("enter sends once, not once per handler", async () => {
    const view = await screen();
    await view.mockInput.typeText("one press, one send");
    await view.flush();
    view.mockInput.pressEnter();
    await letReactRun(view);

    const sends = view.core.sent
      .filter((message) => message["method"] === "session.send");
    expect(sends.length).toBe(1);
    view.client.close();
  });

  test("a remount rebuilds from the snapshot instead of a second session",
       async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 7,
      messages: [
        { message_id: "user-t1", turn_id: "t1", role: "user",
          text: "earlier question", status: "completed" },
        { message_id: "m1", turn_id: "t1", role: "assistant",
          text: "earlier answer", status: "completed" },
      ],
      tools: [
        { call_id: "c1", turn_id: "t1", name: "run_shell", state: "running",
          output: "line one\n" },
      ],
    });
    // The rebuild went to the session the core already had.
    expect(view.core.methods()).not.toContain("session.create");
    expect(view.core.methods()).toContain("session.snapshot");

    const frame = view.frame();
    expect(frame).toContain("earlier question");
    expect(frame).toContain("earlier answer");
    expect(frame).toContain("run_shell");
    expect(frame).toContain("line one");
    view.client.close();
  });
});

// --------------------------------------------------------------------------- //
// rebuilding a session that already exists
// --------------------------------------------------------------------------- //

/** The form a remount has to be able to answer without ever seeing the event. */
const PENDING_FORM = {
  id: "ask-1",
  session_id: "s1",
  title: "2 questions before I start",
  questions: [
    { header: "approach", prompt: "Which approach?", multiple: false,
      options: [
        { id: "Refactor", label: "Refactor" },
        { id: "Replace", label: "Replace" },
        { id: "Something else", label: "Something else", free: true },
      ] },
    { header: "when", prompt: "When?", multiple: true,
      options: [
        { id: "Now", label: "Now" },
        { id: "Something else", label: "Something else", free: true },
      ] },
  ],
};

describe("rebuilding a session", () => {
  test("a remount can answer a question asked before it existed", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 5,
      messages: [],
      tools: [],
      question: PENDING_FORM,
    });

    // The form is what is on screen, and the composer is not: a client that
    // showed the composer here would leave the agent waiting out its timeout
    // on a question the person can see but cannot reach. The session is busy,
    // so the composer would be offering "working…" — its absence is the proof.
    const drawn = view.frame();
    expect(drawn).toContain("Which approach?");
    expect(drawn).not.toContain("working");

    view.mockInput.pressArrow("down");
    view.mockInput.pressKey(" ");
    await letReactRun(view);
    expect(view.frame()).toContain("(*) Replace");

    view.mockInput.pressEnter();
    await letReactRun(view);

    const sent = view.core.sent.find(
      (message) => message["method"] === "question.answer");
    expect(sent).toBeDefined();
    const params = sent!["params"] as { answers: Array<Record<string, unknown>> };
    expect(params.answers[0]?.["header"]).toBe("approach");
    expect(params.answers[0]?.["chosen"]).toEqual(["Replace"]);
    view.client.close();
  });

  test("a remount can write its own answer to a restored question", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 5, messages: [], tools: [], question: PENDING_FORM,
    });

    // Down twice reaches the write-your-own row; space opens the field.
    view.mockInput.pressArrow("down");
    view.mockInput.pressArrow("down");
    view.mockInput.pressKey(" ");
    await view.waitForFrame((frame) => frame.includes("▌"));

    await view.mockInput.typeText("rewrite it");
    await view.waitForFrame((frame) => frame.includes("rewrite it"));
    view.mockInput.pressEnter();
    await letReactRun(view);

    const sent = view.core.sent.find(
      (message) => message["method"] === "question.answer");
    const params = sent!["params"] as { answers: Array<Record<string, unknown>> };
    expect(params.answers[0]?.["written"]).toBe("rewrite it");
    view.client.close();
  });

  test("a remount with nothing waiting shows the composer", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: false },
      revision: 3,
      messages: [{ message_id: "m1", turn_id: "t1", role: "assistant",
                   text: "All done.", status: "completed", started_seq: 2 }],
      tools: [],
    });

    const frame = view.frame();
    expect(frame).toContain("All done.");
    expect(frame).toContain("ask for anything");
    expect(frame).not.toContain("Which approach?");
    view.client.close();
  });

  test("a resolved question takes the restored form away", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 5, messages: [], tools: [], question: PENDING_FORM,
    });
    expect(view.frame()).toContain("Which approach?");

    // Answered elsewhere — another window, or a timeout the core settled.
    await emitRun(view, "question.resolved", { id: "ask-1", session_id: "s1" });

    // The interactive form went with it, and the composer came back.
    const after = view.frame();
    expect(after).not.toContain("Which approach?");
    expect(after).toContain("working");
    view.client.close();
  });

  test("a message the snapshot called streaming keeps streaming", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 5,
      messages: [{ message_id: "m1", turn_id: "t1", role: "assistant",
                   text: "hel", status: "streaming", started_seq: 4 }],
      tools: [],
    });
    expect(view.frame()).toContain("hel");

    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "lo" });
    await emitRun(view, "message.completed",
                  { turn_id: "t1", message_id: "m1", text: "hello",
                    status: "completed" });

    const frame = view.frame();
    expect(frame).toContain("hello");
    // One message, continued — not a second one started below it.
    expect(frame.indexOf("hello")).toBe(frame.lastIndexOf("hello"));
    view.client.close();
  });

  test("a snapshot keeps a turn interleaved on screen", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: false },
      revision: 9,
      messages: [
        { message_id: "A", turn_id: "t1", role: "assistant", text: "Looking.",
          status: "completed", started_seq: 1 },
        { message_id: "B", turn_id: "t1", role: "assistant", text: "Found it.",
          status: "completed", started_seq: 5 },
      ],
      tools: [
        { call_id: "X", turn_id: "t1", name: "read_file", state: "completed",
          started_seq: 3 },
      ],
    });

    const frame = view.frame();
    const at = (needle: string) => frame.indexOf(needle);
    expect(at("Looking.")).toBeGreaterThanOrEqual(0);
    // Answer, then the tool it called, then the answer that follows — the
    // order the turn happened in, not every message before every tool.
    expect(at("read_file")).toBeGreaterThan(at("Looking."));
    expect(at("Found it.")).toBeGreaterThan(at("read_file"));
    view.client.close();
  });

  test.each([["act", "plan"], ["plan", "ask"], ["ask", "act"]])(
    "resuming a session in %s advances from there, not from a default",
    async (resumed, expected) => {
      const view = await screen(100, 30, "s1", {
        session: { id: "s1", mode: resumed, workspace: "/work/project",
                   busy: false },
        revision: 2, messages: [], tools: [],
      });
      view.core.mode = resumed;
      await letReactRun(view);
      expect(view.frame()).toContain(`[${resumed.toUpperCase()}]`);

      view.mockInput.pressTab();
      // A mode command records intent and one coordinator turns that into the
      // request, so React has to run before the round trip can even start.
      await letReactRun(view);
      await view.waitForFrame(() => view.core.mode === expected, MODE_PASSES);

      // One request, for the mode after the one actually resumed.
      expect(view.sentModes()).toEqual([expected]);
      view.client.close();
    });

  test("shift+tab from a resumed mode walks back from there", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "plan", workspace: "/work/project",
                 busy: false },
      revision: 2, messages: [], tools: [],
    });
    view.core.mode = "plan";
    await letReactRun(view);

    view.mockInput.pressTab({ shift: true });
    await letReactRun(view);
    await view.waitForFrame(() => view.core.mode === "act", MODE_PASSES);

    expect(view.sentModes()).toEqual(["act"]);
    view.client.close();
  });
});

// --------------------------------------------------------------------------- //
// permissions — the interaction F2 could carry but not present
// --------------------------------------------------------------------------- //

const PERMISSION = {
  id: "perm-1",
  session_id: "s1",
  title: "run: npm test",
  detail: "$ npm test",
  options: ["allow", "allow_always", "deny"],
  tool: "run_shell",
  risk: "dangerous",
};

/** Every choice the client has sent, in order. */
function replies(view: View): string[] {
  return view.core.sent
    .filter((message) => message["method"] === "permission.reply")
    .map((message) =>
      String((message["params"] as Record<string, unknown>)["choice"]));
}

describe("permissions", () => {
  test("a prompt is drawn with what it is actually for", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    const frame = view.frame();
    expect(frame).toContain("Permission needed");
    expect(frame).toContain("run_shell");
    expect(frame).toContain("runs commands");      // the tier, in words
    expect(frame).toContain("run: npm test");
    expect(frame).toContain("$ npm test");
    expect(frame).toContain("Allow");
    expect(frame).toContain("Allow for this session");
    // Deny is where the cursor starts, and the brackets say so without colour.
    expect(frame).toContain("[Deny]");
    expect(frame).not.toContain("[Allow]");
    view.client.close();
  });

  test("the composer is not what is waiting for input", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    expect(view.frame()).not.toContain("ask for anything");
    view.client.close();
  });

  test("enter sends the highlighted choice, which starts as deny", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    view.mockInput.pressEnter();
    await letReactRun(view);

    expect(replies(view)).toEqual(["deny"]);
    view.client.close();
  });

  test("allowing takes a deliberate move to it", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    // From Deny, one step right wraps to Allow.
    view.mockInput.pressArrow("right");
    await letReactRun(view);
    expect(view.frame()).toContain("[Allow]");

    view.mockInput.pressEnter();
    await letReactRun(view);
    expect(replies(view)).toEqual(["allow"]);
    view.client.close();
  });

  test("left and right walk the choices the core offered", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    view.mockInput.pressArrow("left");
    await letReactRun(view);
    expect(view.frame()).toContain("[Allow for this session]");

    view.mockInput.pressArrow("left");
    await letReactRun(view);
    expect(view.frame()).toContain("[Allow]");

    view.mockInput.pressArrow("left");
    await letReactRun(view);
    expect(view.frame()).toContain("[Deny]");
    expect(replies(view)).toEqual([]);
    view.client.close();
  });

  test("escape denies, and never allows", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    // Even with Allow highlighted: Esc has one meaning here, and it is the
    // safe one. A key that meant "dismiss" would leave the core waiting on a
    // prompt nobody could see any more.
    view.mockInput.pressArrow("right");
    await letReactRun(view);
    await pressEscape(view);
    await letReactRun(view);

    expect(replies(view)).toEqual(["deny"]);
    view.client.close();
  });

  test("escape takes a consent card's own refusal, not a word it does not offer",
       async () => {
    // The same card draws a request for screen access, whose options are
    // durations and "no". Sending "deny" there is not one of them: the core
    // refuses the reply, the card shows a failure, and the worker stays
    // blocked on the prompt Escape was supposed to clear.
    const view = await screen();
    await emitRun(view, "permission.requested", {
      id: "computer_1", session_id: "s1",
      title: "Let Comodor use your screen, mouse and keyboard?",
      options: ["15 minutes", "15 minutes, this app only", "1 hour", "no"],
      tool: "computer", risk: "dangerous",
    });

    expect(view.frame()).toContain("esc no");
    await pressEscape(view);
    await letReactRun(view);

    expect(replies(view)).toEqual(["no"]);
    expect(view.frame()).not.toContain("not sent");
    view.client.close();
  });

  test("escape on a mode proposal keeps the current mode", async () => {
    // A proposal offers mode names with the current one last, so silence means
    // "no change" rather than a switch — and "deny" is not on the list at all.
    const view = await screen();
    await emitRun(view, "permission.requested", {
      id: "mode-1", session_id: "s1", title: "Switch to plan mode?",
      options: ["plan", "ask", "act"], tool: "propose_mode",
    });

    expect(view.frame()).toContain("esc act");
    await pressEscape(view);
    await letReactRun(view);

    expect(replies(view)).toEqual(["act"]);
    expect(view.frame()).not.toContain("not sent");
    view.client.close();
  });

  test("no ordinary key grants anything", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    // The letters a person might press meaning "yes" somewhere else. None of
    // them is a shortcut here, because a key pressed for another reason must
    // not be able to authorise a shell command.
    await view.mockInput.typeText("ayY allowallow1");
    await letReactRun(view);

    expect(replies(view)).toEqual([]);
    expect(view.frame()).toContain("[Deny]");
    view.client.close();
  });

  test("clicking a choice decides it", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    const at = locate(view.frame(), "Allow for this session");
    await view.mockMouse.click(at.x, at.y);
    await letReactRun(view);

    expect(replies(view)).toEqual(["allow_always"]);
    view.client.close();
  });

  test("two enters send one reply", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    view.mockInput.pressEnter();
    view.mockInput.pressEnter();
    await letReactRun(view);
    await letReactRun(view);

    expect(replies(view)).toEqual(["deny"],
      "a permission granted twice is not a harmless duplicate");
    view.client.close();
  });

  test("a click while a key is in flight still sends one reply", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);
    view.core.holdResolutions = true;

    view.mockInput.pressEnter();
    const at = locate(view.frame(), "Allow");
    await view.mockMouse.click(at.x, at.y);
    await letReactRun(view);

    expect(replies(view).length).toBe(1);
    view.client.close();
  });

  test("the card waits for the core rather than dismissing itself", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);
    view.core.holdResolutions = true;

    view.mockInput.pressEnter();
    await letReactRun(view);

    // The reply was accepted, and the card is still up saying so: whether the
    // request is still live is the core's to say, not the client's.
    expect(replies(view)).toEqual(["deny"]);
    expect(view.frame()).toContain("sending");

    await emitRun(view, "permission.resolved",
      { id: "perm-1", session_id: "s1", choice: "deny" });
    expect(view.frame()).not.toContain("Permission needed");
    expect(view.frame()).toContain("ask for anything");
    view.client.close();
  });

  test("a refused reply leaves the card up with the reason", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);
    view.core.refuseReplies = true;

    view.mockInput.pressEnter();
    await letReactRun(view);

    const frame = view.frame();
    expect(frame).toContain("Permission needed");
    expect(frame).toContain("not sent");
    expect(frame).toContain("nothing is waiting under that id");

    // And it can be tried again, because the core may still be waiting.
    view.core.refuseReplies = false;
    view.mockInput.pressEnter();
    await letReactRun(view);
    expect(replies(view)).toEqual(["deny", "deny"]);
    view.client.close();
  });

  test("enter on a permission does not also send a chat message", async () => {
    const view = await screen();
    await view.mockInput.typeText("a message that must not be sent");
    await view.flush();
    await emitRun(view, "permission.requested", PERMISSION);

    view.mockInput.pressEnter();
    await letReactRun(view);

    expect(view.core.methods()).not.toContain("session.send");
    expect(replies(view)).toEqual(["deny"]);
    view.client.close();
  });

  test("ctrl+c cancels the turn instead of leaving with a prompt up", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);
    // A prompt only exists inside a turn, and Ctrl+C is context-sensitive:
    // with work running it stops the work, and only quits when there is none.
    view.core.busy = true;
    await emitRun(view, "session.updated", { session: view.core.session() });

    view.mockInput.pressKey("c", { ctrl: true });
    await letReactRun(view);

    expect(view.quit()).toBe(false);
    expect(view.core.methods()).toContain("session.cancel");
    view.client.close();
  });

  test("tab still changes mode while a prompt is waiting", async () => {
    // Deliberate: the core accepts a mode change with a prompt outstanding,
    // and moving to Plan while deciding whether to let something run is a
    // reasonable thing to want. What must not happen is the prompt losing the
    // keyboard to the composer.
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);

    view.mockInput.pressTab();
    await letReactRun(view);
    await view.waitForFrame(() => view.core.mode === "plan", MODE_PASSES);

    expect(view.sentModes()).toEqual(["plan"]);
    expect(view.frame()).toContain("Permission needed");
    expect(replies(view)).toEqual([]);
    view.client.close();
  });

  test("a second prompt waits behind the first and is shown in turn", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);
    await emitRun(view, "permission.requested",
      { ...PERMISSION, id: "perm-2", title: "run: rm -rf build",
        detail: "$ rm -rf build" });

    expect(view.frame()).toContain("run: npm test");
    expect(view.frame()).toContain("+1 more waiting");

    await emitRun(view, "permission.resolved",
      { id: "perm-1", session_id: "s1", choice: "deny" });

    expect(view.frame()).toContain("run: rm -rf build");
    expect(view.frame()).not.toContain("+1 more waiting");
    view.client.close();
  });

  test("a prompt restored from a snapshot can be answered", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 4,
      messages: [],
      tools: [{ call_id: "c1", turn_id: "t1", name: "run_shell",
                state: "running", started_seq: 3 }],
      permission: PERMISSION,
      interactions: [{ kind: "permission", permission: PERMISSION }],
    });

    // Raised before this client existed, and still answerable — otherwise the
    // tool waits out its timeout on a decision nobody was shown.
    expect(view.frame()).toContain("Permission needed");
    expect(view.frame()).toContain("run: npm test");

    view.mockInput.pressArrow("right");
    await letReactRun(view);
    view.mockInput.pressEnter();
    await letReactRun(view);

    expect(replies(view)).toEqual(["allow"]);
    view.client.close();
  });

  test("a snapshot with nothing waiting shows no card", async () => {
    const view = await screen(100, 30, "s1", {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: false },
      revision: 6,
      messages: [{ message_id: "m1", turn_id: "t1", role: "assistant",
                   text: "All done.", status: "completed", started_seq: 5 }],
      tools: [],
    });

    expect(view.frame()).not.toContain("Permission needed");
    expect(view.frame()).toContain("ask for anything");
    view.client.close();
  });

  test("a prompt resolved elsewhere goes away", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", PERMISSION);
    expect(view.frame()).toContain("Permission needed");

    await emitRun(view, "permission.resolved",
      { id: "perm-1", session_id: "s1", choice: "allow" });

    expect(view.frame()).not.toContain("Permission needed");
    // And a key that arrives now cannot answer a request that has gone.
    view.mockInput.pressEnter();
    await letReactRun(view);
    expect(replies(view)).toEqual([]);
    view.client.close();
  });

  test.each([160, 120, 100, 80, 60])(
    "the card stays usable at %i columns", async (width) => {
      const view = await screen(width as number, 30);
      await emitRun(view, "permission.requested", {
        ...PERMISSION,
        title: "run: a command long enough to have to wrap somewhere in here",
        detail: Array.from({ length: 12 }, (_each, at) => `output line ${at}`).join("\n"),
      });

      const frame = view.frame();
      for (const row of frame.split("\n")) {
        expect(row.length).toBeLessThanOrEqual(width as number);
      }
      // The decision has to survive whatever the prose did.
      expect(frame).toContain("[Deny]");
      expect(frame).toContain("Permission needed");
      expect(frame).toContain("more line");     // the clipped detail says so
      view.client.close();
    });

  test("terminal escapes in a prompt cannot rewrite the card", async () => {
    // The title and the detail come from a tool, which takes them from a
    // model, which takes them from a file. They are display text and nothing
    // in them may move the cursor, clear the screen, or invent a choice.
    const view = await screen();
    await emitRun(view, "permission.requested", {
      ...PERMISSION,
      title: "\x1b[2J\x1b[Hrun: npm test\x1b[31m",
      detail: "\x1b]0;pwned\x07$ npm test\r\n\x1b[6;1H[Allow]",
    });

    const frame = view.frame();
    for (const row of frame.split("\n")) {
      expect(row.length).toBeLessThanOrEqual(100);
    }
    // The real choices are still the only ones on offer, and still in place.
    expect(frame).toContain("[Deny]");
    expect(frame).toContain("Allow for this session");
    expect(frame).toContain("Permission needed");
    expect(replies(view)).toEqual([]);
    view.client.close();
  });

  test("a prompt in another script renders as it was written", async () => {
    const view = await screen();
    await emitRun(view, "permission.requested", {
      ...PERMISSION,
      title: "اجازه برای اجرای آزمون‌ها",
      detail: "$ npm test — پوشهٔ build",
    });

    const frame = view.frame();
    expect(frame).toContain("اجازه");
    expect(frame).toContain("[Deny]");
    view.client.close();
  });
});

// --------------------------------------------------------------------------- //
// the rest of the interaction surface, proven rather than wired
// --------------------------------------------------------------------------- //

describe("mode transitions on screen", () => {
  test("a change in flight is shown as in flight, not as done", async () => {
    const view = await screen();
    view.core.holdModes = true;

    view.mockInput.pressTab();
    await letReactRun(view);
    await letReactRun(view);

    // The core has not answered, so the confirmed mode has not moved — and the
    // screen says a request is outstanding rather than implying it succeeded.
    const pending = view.frame();
    expect(pending).toContain("[ACT]");
    expect(pending).toContain("(PLAN)");
    expect(pending).toContain("asking the core");

    view.core.holdModes = false;
    view.core.releaseModes();
    await letReactRun(view);
    await view.waitForFrame((frame) => frame.includes("[PLAN]"), MODE_PASSES);

    const confirmed = view.frame();
    expect(confirmed).not.toContain("asking the core");
    expect(confirmed).not.toContain("(PLAN)");
    view.client.close();
  });

  test("a refusal is presented, and the mode stays where the core has it",
       async () => {
    const view = await screen();
    view.core.intercept = (method, _params, id) => {
      if (method !== "session.set_mode") return false;
      view.core.push({ version: PROTOCOL_VERSION, type: "error", id,
                       error: { code: "not_allowed",
                                message: "plan is not available in this session" } });
      return true;
    };

    view.mockInput.pressTab();
    await letReactRun(view);
    await letReactRun(view);

    const frame = view.frame();
    expect(frame).toContain("[ACT]");
    expect(frame).toContain("refused");
    expect(frame).toContain("plan is not available in this session");
    // And it does not ask again: a refusal is final until the person moves.
    expect(view.sentModes()).toEqual(["plan"]);
    view.client.close();
  });
});

describe("the mouse, where it is claimed", () => {
  test("clicking a question option chooses it", async () => {
    const view = await screen();
    await emitRun(view, "question.requested", {
      id: "ask-1", session_id: "s1", title: "one question",
      questions: [{ header: "approach", prompt: "Which approach?",
                    multiple: false,
                    options: [{ id: "Refactor", label: "Refactor" },
                              { id: "Replace", label: "Replace" }] }],
    });
    await view.waitForFrame((frame) => frame.includes("Which approach?"));

    const at = locate(view.frame(), "Replace");
    await view.mockMouse.click(at.x, at.y);
    await letReactRun(view);

    expect(view.frame()).toContain("(*) Replace");
    expect(view.frame()).toContain("( ) Refactor");
    view.client.close();
  });

  test("clicking options in a multi-select question keeps both", async () => {
    const view = await screen();
    await emitRun(view, "question.requested", {
      id: "ask-1", session_id: "s1", title: "one question",
      questions: [{ header: "when", prompt: "When?", multiple: true,
                    options: [{ id: "Now", label: "Now" },
                              { id: "Later", label: "Later" }] }],
    });
    await view.waitForFrame((frame) => frame.includes("When?"));

    for (const label of ["Now", "Later"]) {
      const at = locate(view.frame(), label);
      await view.mockMouse.click(at.x, at.y);
      await letReactRun(view);
    }

    expect(view.frame()).toContain("[x] Now");
    expect(view.frame()).toContain("[x] Later");
    view.client.close();
  });

  test("clicking a palette row runs it", async () => {
    const view = await screen();
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    // The query is matched literally, so "mode" rather than a command id.
    await view.mockInput.typeText("mode");
    await letReactRun(view);

    const at = locate(view.frame(), "Mode: ASK");
    await view.mockMouse.click(at.x, at.y);
    await letReactRun(view);
    await view.waitForFrame(() => view.core.mode === "ask", MODE_PASSES);

    expect(view.frame()).not.toContain("type a command");
    expect(view.sentModes()).toEqual(["ask"]);
    view.client.close();
  });
});

describe("a draft is not disturbed by the turn behind it", () => {
  test("selections survive streaming, tool output and notices", async () => {
    const view = await screen();
    await emitRun(view, "question.requested", {
      id: "ask-1", session_id: "s1", title: "two questions",
      questions: [
        { header: "approach", prompt: "Which approach?", multiple: false,
          options: [{ id: "Refactor", label: "Refactor" },
                    { id: "Replace", label: "Replace" }] },
        { header: "when", prompt: "When?", multiple: false,
          options: [{ id: "Now", label: "Now" }] },
      ],
    });
    await view.waitForFrame((frame) => frame.includes("Which approach?"));

    // Choose, then move to the second question.
    view.mockInput.pressArrow("down");
    view.mockInput.pressKey(" ");
    await letReactRun(view);
    view.mockInput.pressArrow("right");
    await letReactRun(view);
    expect(view.frame()).toContain("Question 2 of 2");

    // A turn streams behind the form. None of it is the form's business.
    await emitRun(view, "message.started", { turn_id: "t1", message_id: "m1" });
    for (const chunk of ["still ", "working ", "on it"]) {
      await emitRun(view, "message.delta",
                    { turn_id: "t1", message_id: "m1", text: chunk });
    }
    await emitRun(view, "tool.started",
      { turn_id: "t1", call_id: "c1", name: "read_file" });
    await emitRun(view, "tool.output",
      { turn_id: "t1", call_id: "c1", text: "some output\n" });
    await emitRun(view, "notification.created",
      { level: "info", text: "a note" });
    await emitRun(view, "mode.changed", { session_id: "s1", mode: "act" });

    const frame = view.frame();
    expect(frame).toContain("Question 2 of 2");
    expect(frame).toContain("1/2 answered");
    // The first question's choice is still there, and still the second one
    // being shown: nothing was reset by an unrelated event.
    view.mockInput.pressArrow("left");
    await letReactRun(view);
    expect(view.frame()).toContain("(*) Replace");
    view.client.close();
  });

  test("a resync that redelivers the same request keeps the draft", async () => {
    const form = {
      id: "ask-1", session_id: "s1", title: "one question",
      questions: [{ header: "approach", prompt: "Which approach?",
                    multiple: false,
                    options: [{ id: "Refactor", label: "Refactor" },
                              { id: "Replace", label: "Replace" }] }],
    };
    const view = await screen();
    await emitRun(view, "question.requested", form);
    await view.waitForFrame((frame) => frame.includes("Which approach?"));

    view.mockInput.pressArrow("down");
    await letReactRun(view);
    view.mockInput.pressKey(" ");
    await letReactRun(view);
    expect(view.frame()).toContain("(*) Replace");

    // A hole in the sequence forces a resync, and the snapshot the core
    // answers with still carries the same request. Repairing the stream is no
    // reason to throw away an answer somebody was halfway through.
    view.core.snapshot = {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 60, messages: [], tools: [], question: form,
      interactions: [{ kind: "question", question: form }],
    };
    view.core.push(event("message.delta",
      { turn_id: "t1", message_id: "m1", text: "a chunk that jumped" }, 50));
    await letReactRun(view);
    await letReactRun(view);
    await letReactRun(view);

    expect(view.frame()).toContain("(*) Replace");
    view.client.close();
  });

  test("a resync carrying a different request does not inherit the draft", async () => {
    const first = {
      id: "ask-1", session_id: "s1", title: "the first",
      questions: [{ header: "approach", prompt: "Which approach?",
                    multiple: false,
                    options: [{ id: "Refactor", label: "Refactor" },
                              { id: "Replace", label: "Replace" }] }],
    };
    const view = await screen();
    await emitRun(view, "question.requested", first);
    await view.waitForFrame((frame) => frame.includes("Which approach?"));

    view.mockInput.pressArrow("down");
    await letReactRun(view);
    view.mockInput.pressKey(" ");
    await letReactRun(view);
    expect(view.frame()).toContain("(*) Replace");

    // The core moved on: the first form is gone and a different one is
    // waiting. A selection made for one question is not an answer to another.
    const second = {
      id: "ask-2", session_id: "s1", title: "the second",
      questions: [{ header: "when", prompt: "When should it run?",
                    multiple: false,
                    options: [{ id: "Refactor", label: "Refactor" },
                              { id: "Replace", label: "Replace" }] }],
    };
    view.core.snapshot = {
      session: { id: "s1", mode: "act", workspace: "/work/project", busy: true },
      revision: 60, messages: [], tools: [], question: second,
      interactions: [{ kind: "question", question: second }],
    };
    view.core.push(event("message.delta",
      { turn_id: "t1", message_id: "m1", text: "a chunk that jumped" }, 50));
    await letReactRun(view);
    await letReactRun(view);
    await letReactRun(view);

    const frame = view.frame();
    expect(frame).toContain("When should it run?");
    expect(frame).not.toContain("(*) Replace");
    view.client.close();
  });

  test("a typed answer keeps what was typed", async () => {
    const view = await screen();
    await emitRun(view, "question.requested", {
      id: "ask-1", session_id: "s1", title: "one question",
      questions: [{ header: "approach", prompt: "Which approach?",
                    multiple: false,
                    options: [{ id: "Refactor", label: "Refactor" },
                              { id: "Other", label: "Something else",
                                free: true }] }],
    });
    await view.waitForFrame((frame) => frame.includes("Which approach?"));

    view.mockInput.pressArrow("down");
    await letReactRun(view);
    view.mockInput.pressKey(" ");
    await letReactRun(view);
    await view.waitForFrame((frame) => frame.includes("▌"));
    await view.mockInput.typeText("rewrite the parser");
    await letReactRun(view);
    expect(view.frame()).toContain("rewrite the parser");

    await emitRun(view, "message.delta",
      { turn_id: "t1", message_id: "m1", text: "noise behind the form" });
    await letReactRun(view);

    expect(view.frame()).toContain("rewrite the parser");
    view.client.close();
  });
});

describe("text that is hard to draw", () => {
  test("persian, mixed direction and emoji survive a form and a prompt",
       async () => {
    const view = await screen();
    await emitRun(view, "question.requested", {
      id: "ask-1", session_id: "s1", title: "سؤال",
      questions: [{ header: "approach", prompt: "کدام روش؟ Which approach?",
                    multiple: false,
                    options: [{ id: "بازنویسی", label: "بازنویسی ✓ rewrite" },
                              { id: "Other", label: "چیز دیگر 🎉",
                                free: true }] }],
    });
    await view.waitForFrame((frame) => frame.includes("کدام"));

    const frame = view.frame();
    expect(frame).toContain("بازنویسی");
    expect(frame).toContain("🎉");
    for (const row of frame.split("\n")) {
      expect(row.length).toBeLessThanOrEqual(100);
    }

    // And a written answer in the same mix.
    view.mockInput.pressArrow("down");
    await letReactRun(view);
    view.mockInput.pressKey(" ");
    await letReactRun(view);
    await view.waitForFrame((shown) => shown.includes("▌"));
    await view.mockInput.typeText("سلام hello 🎉");
    await letReactRun(view);
    const typed = view.frame();
    expect(typed).toContain("سلام");
    expect(typed).toContain("hello");
    view.client.close();
  });

  test("a very long prompt and path stay inside the card", async () => {
    const view = await screen(80, 30);
    const long = "a/".repeat(120) + "very-deep-file.ts";
    await emitRun(view, "permission.requested", {
      ...PERMISSION,
      title: `write ${long}`,
      detail: Array.from({ length: 40 }, (_each, at) => `+ ${long} ${at}`).join("\n"),
    });

    const frame = view.frame();
    for (const row of frame.split("\n")) {
      expect(row.length).toBeLessThanOrEqual(80);
    }
    // The decision is still reachable whatever the prose did.
    expect(frame).toContain("[Deny]");
    expect(frame).toContain("Permission needed");
    view.client.close();
  });
});

/** The palette row currently marked as selected. */
function markedRow(frame: string): string {
  for (const row of frame.split("\n")) {
    const at = row.indexOf("›");
    if (at >= 0) return row.slice(at + 1).trim();
  }
  return "";
}

// --------------------------------------------------------------------------- //
// the workbench — tools, tasks and agents, in the real renderer
// --------------------------------------------------------------------------- //

/** One delegate record as the core's relay puts it on the wire. */
function wireAgent(id: string, state: string,
                   extra: Record<string, unknown> = {}) {
  return { id, label: `work ${id}`, state, steps: 0, tool_calls: 0,
           tokens: 0, elapsed: 0,
           started_at: Math.floor(Date.now() / 1000), ...extra };
}

function rowsWithin(frame: string, width: number): void {
  for (const row of frame.split("\n")) {
    expect(row.length).toBeLessThanOrEqual(width);
  }
}

describe("the tool timeline", () => {
  test("a running tool says it is running and shows the tail of its output",
       async () => {
    const view = await screen();
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "run_shell",
                    summary: "run: pytest tests" });
    for (const line of ["line1", "line2", "line3", "line4", "line5"]) {
      await emitRun(view, "tool.output",
                    { turn_id: "t1", call_id: "a", text: `${line}\n` });
    }

    const frame = view.frame();
    expect(frame).toContain("run: pytest tests");
    expect(frame).toContain("running…");
    // The tail, bounded: the newest lines are the ones that say what is
    // happening now, and five hundred more must not push the composer off.
    expect(frame).toContain("line5");
    expect(frame).toContain("line3");
    expect(frame).not.toContain("line1");
    rowsWithin(frame, 100);
    view.client.close();
  });

  test("a finished tool collapses to one row, with what it cost in time",
       async () => {
    const view = await screen();
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "read_file",
                    summary: "read src/app.py" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "a", text: "the file body\n" });
    await emitRun(view, "tool.completed",
                  { turn_id: "t1", call_id: "a", name: "read_file",
                    summary: "read src/app.py", elapsed_ms: 340 });

    const frame = view.frame();
    expect(frame).toContain("read src/app.py");
    expect(frame).toContain("0.3s");
    expect(frame).not.toContain("running…");
    // Compact: a long run leaves dozens of these behind, and every one of
    // them keeping its output is a wall nobody can scan.
    expect(frame).not.toContain("the file body");
    view.client.close();
  });

  test("clicking a finished tool opens its output, and closes it again",
       async () => {
    const view = await screen();
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "read_file",
                    summary: "read src/app.py" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "a", text: "the hidden detail\n" });
    await emitRun(view, "tool.completed",
                  { turn_id: "t1", call_id: "a", elapsed_ms: 120 });
    expect(view.frame()).not.toContain("the hidden detail");

    const at = locate(view.frame(), "read src/app.py");
    view.mockMouse.click(at.x, at.y);
    await letReactRun(view);
    expect(view.frame()).toContain("the hidden detail");

    const again = locate(view.frame(), "read src/app.py");
    view.mockMouse.click(again.x, again.y);
    await letReactRun(view);
    expect(view.frame()).not.toContain("the hidden detail");
    view.client.close();
  });

  test("a failed tool shows the head of its error, bounded", async () => {
    const view = await screen();
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "run_shell",
                    summary: "run: make" });
    await emitRun(view, "tool.failed", {
      turn_id: "t1", call_id: "a",
      error: "boom line 1\nline 2\nline 3\nline 4\nline 5",
    });

    const frame = view.frame();
    expect(frame).toContain("boom line 1");
    expect(frame).toContain("line 3");
    expect(frame).not.toContain("line 5");
    view.client.close();
  });

  test("hostile tool output cannot forge the screen", async () => {
    const view = await screen();
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "read_file",
                    summary: "\x1b[2J\x1b[Hforged summary" });
    await emitRun(view, "tool.output", {
      turn_id: "t1", call_id: "a",
      text: "\x1b]0;hacked\x07\x1b[2J fake [ACT] row\n"
            + "X".repeat(500) + "\n",
    });

    const frame = view.frame();
    rowsWithin(frame, 100);
    // The screen survived: the header, the composer and one real mode bar.
    // The bar is the row carrying the bracketed current mode *and* its two
    // plain neighbours; hostile output may contain the letters "[ACT]" as
    // data, but it cannot produce a second bar.
    expect(frame).toContain("Comodor");
    expect(frame).toContain("ask for anything");
    const modeBars = frame.split("\n")
      .filter((row) => row.includes("[ACT]") && row.includes("PLAN")
                       && row.includes("ASK"));
    expect(modeBars.length).toBe(1);
    view.client.close();
  });
});

describe("the tasks panel", () => {
  test("the task list arrives as a panel, and an update replaces it",
       async () => {
    const view = await screen();
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "read the code", state: "done" },
      { text: "write the tests", state: "active" },
    ] });

    let frame = view.frame();
    expect(frame).toMatch(/Tasks\s+1\/2/);
    expect(frame).toContain("read the code");
    expect(frame).toContain("write the tests");
    // Active first, stable — the item being worked on is never the one a
    // short panel drops.
    expect(frame.indexOf("write the tests"))
      .toBeLessThan(frame.indexOf("read the code"));

    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "write the tests", state: "done" },
    ] });
    frame = view.frame();
    expect(frame).toMatch(/Tasks\s+1\/1/);
    expect(frame).not.toContain("read the code");
    view.client.close();
  });

  test("fifty tasks stay inside the panel", async () => {
    const view = await screen();
    const tasks = Array.from({ length: 50 }, (_each, at) => ({
      text: at === 7 ? "the active one"
        : at === 1 ? "blocked on review"
        : `task-${String(at).padStart(2, "0")} a fairly long piece of text`,
      state: at === 7 ? "active" : at === 1 ? "blocked"
        : at % 2 === 0 ? "done" : "pending",
    }));
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks });

    const frame = view.frame();
    expect(frame).toMatch(/Tasks\s+25\/50/);
    expect(frame).toContain("the active one");
    expect(frame).toContain("blocked on review");
    expect(frame).toContain("+44 more");
    rowsWithin(frame, 100);
    view.client.close();
  });

  test("persian and emoji task text render as written", async () => {
    const view = await screen();
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "بازبینی کد 🎉", state: "active" },
      { text: "مسیر path", state: "pending" },
    ] });

    const frame = view.frame();
    expect(frame).toContain("بازبینی");
    expect(frame).toContain("🎉");
    expect(frame).toContain("مسیر");
    rowsWithin(frame, 100);
    view.client.close();
  });
});

describe("the agents panel", () => {
  test("every lifecycle state is visible, in words", async () => {
    const view = await screen();
    await emitRun(view, "delegate.updated",
                  { session_id: "s1",
                    delegate: wireAgent("d1", "running",
                                        { label: "survey retries" }) });

    let frame = view.frame();
    expect(frame).toContain("Agents");
    expect(frame).toContain("survey retries");
    expect(frame).toContain("d1 running");

    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "stopping") });
    expect(view.frame()).toContain("d1 stopping");

    await emitRun(view, "delegate.updated",
                  { session_id: "s1",
                    delegate: wireAgent("d2", "done",
                                        { elapsed: 12.4, steps: 3 }) });
    frame = view.frame();
    expect(frame).toContain("d2 done");
    expect(frame).toContain("12.4s");
    expect(frame).toContain("3 steps");

    await emitRun(view, "delegate.updated",
                  { session_id: "s1",
                    delegate: wireAgent("d3", "failed",
                                        { error: "child exploded" }) });
    frame = view.frame();
    expect(frame).toContain("d3 failed");
    expect(frame).toContain("child exploded");

    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d4", "stopped") });
    expect(view.frame()).toContain("d4 stopped");
    view.client.close();
  });

  test("a delegate lost to a crash stays lost", async () => {
    // The state that must never be dressed up: work that died with the
    // process is not work in flight, and a panel that showed it running
    // would have somebody waiting on an answer that does not exist.
    const view = await screen();
    await emitRun(view, "delegate.updated", {
      session_id: "s1",
      delegate: wireAgent("d7", "lost", {
        label: "old survey",
        error: "the session ended while this was running",
      }),
    });

    const frame = view.frame();
    expect(frame).toContain("d7 lost");
    expect(frame).toContain("the session ended");
    expect(frame).not.toContain("d7 running");
    view.client.close();
  });

  test("a panel of six delegates stays bounded and counts what is live",
       async () => {
    const view = await screen();
    for (const id of ["d1", "d2", "d3"]) {
      await emitRun(view, "delegate.updated",
                    { session_id: "s1", delegate: wireAgent(id, "running") });
    }
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d4", "done") });
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d5", "failed") });
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d6", "stopped") });

    const frame = view.frame();
    expect(frame).toContain("3 live");
    expect(frame).toContain("+2 more");
    rowsWithin(frame, 100);
    view.client.close();
  });

  test("an emoji label survives the panel", async () => {
    const view = await screen();
    await emitRun(view, "delegate.updated", {
      session_id: "s1",
      delegate: wireAgent("d1", "running", { label: "🔍 survey the retries" }),
    });

    expect(view.frame()).toContain("🔍");
    view.client.close();
  });

  test("a running delegate is never hidden behind settled rows", async () => {
    // Terminal records stay in the list for the whole session, so a fixed
    // head slice would show the oldest four for ever — and every delegate
    // launched after them would exist only as a count. The window must give
    // the live rows the space first: work happening now is what the panel is
    // for.
    const view = await screen();
    const settled: Array<[string, string]> = [
      ["d1", "done"], ["d2", "failed"], ["d3", "stopped"], ["d4", "done"],
    ];
    for (const [id, state] of settled) {
      await emitRun(view, "delegate.updated",
                    { session_id: "s1", delegate: wireAgent(id, state) });
    }

    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d5", "running") });

    const frame = view.frame();
    expect(frame).toContain("d5 running");
    expect(frame).toContain("1 live");
    // Five rows, four drawn: the oldest settled record is the one counted.
    expect(frame).toContain("+1 more");
    expect(frame).not.toContain("d1 done");
    view.client.close();
  });

  test("the row under the cursor is always drawn", async () => {
    // The keyboard cursor ranges over every delegate, not only the visible
    // window — so the window must follow it. A cursor that could move onto an
    // invisible row would let Enter stop work whose label and state nobody
    // can see.
    const view = await screen();
    for (const id of ["d1", "d2", "d3", "d4", "d5"]) {
      await emitRun(view, "delegate.updated",
                    { session_id: "s1", delegate: wireAgent(id, "done") });
    }
    // Five settled rows, four drawn: unfocused, the newest are shown and the
    // oldest one is not.
    expect(view.frame()).toContain("d5 done");
    expect(view.frame()).not.toContain("d1 done");

    view.mockInput.pressKey("b", { ctrl: true });
    // The cursor opened on the first row, which the window now draws —
    // waited for rather than flushed to, because a render that has not
    // landed yet is not evidence the row is not drawn.
    await view.waitForFrame((frame) =>
      frame.split("\n").find((row) => row.includes("›"))
        ?.includes("d1 done") ?? false);

    for (let at = 0; at < 4; at++) {
      view.mockInput.pressArrow("down");
      await letReactRun(view);
    }
    // The cursor reached d5, and the window moved with it.
    await view.waitForFrame((frame) =>
      frame.split("\n").find((row) => row.includes("›"))
        ?.includes("d5 done") ?? false);
    view.client.close();
  });
});

describe("stopping a background agent", () => {
  test("the keyboard path asks the core, and only the core moves the row",
       async () => {
    const view = await screen();
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });

    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);
    let frame = view.frame();
    expect(frame).toContain("› ● d1 running");
    expect(frame).toContain("enter Stop d1");

    // Two presses inside one tick are one request: the latch refuses the
    // second before the projection has re-rendered anything.
    view.mockInput.pressEnter();
    view.mockInput.pressEnter();
    await view.waitForFrame(() => view.sentStops().length >= 1, MODE_PASSES);
    await letReactRun(view);
    expect(view.sentStops()).toEqual(["d1"]);

    // The row still says running: the client paints nothing the core has not
    // announced. A panel showing `stopped` here would be a lie with a key
    // press's worth of authority behind it.
    expect(view.frame()).toContain("d1 running");
    expect(view.frame()).not.toContain("d1 stopped");

    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "stopping") });
    expect(view.frame()).toContain("d1 stopping");

    // And once it is stopping, Enter has nothing left to ask for.
    view.mockInput.pressEnter();
    await letReactRun(view);
    expect(view.sentStops()).toEqual(["d1"]);

    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "stopped") });
    expect(view.frame()).toContain("d1 stopped");
    view.client.close();
  });

  test("a stop that found nothing running says so", async () => {
    const view = await screen();
    view.core.stopAnswer = false;
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });
    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);

    view.mockInput.pressEnter();
    // The round trip — request, refusal-of-nothing, the local notice it
    // produces — needs the event loop turned, which is what letReactRun does;
    // waitForFrame alone watches frames, and an idle renderer makes none.
    await letReactRun(view);
    await view.waitForFrame((frame) => frame.includes("was not running"),
                            MODE_PASSES);
    expect(view.sentStops()).toEqual(["d1"]);
    view.client.close();
  });

  test("a click selects a row, and only the stop control stops", async () => {
    const view = await screen();
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d2", "running") });

    // Selecting is a click on the row. It must not stop anything — one
    // accidental click on an arbitrary row is not a decision about work.
    const row = locate(view.frame(), "d2 running");
    view.mockMouse.click(row.x, row.y);
    await letReactRun(view);
    expect(view.sentStops()).toEqual([]);
    expect(view.frame()).toContain("enter Stop d2");

    // Stopping is a click on the control that says Stop.
    const control = locate(view.frame(), "enter Stop d2");
    view.mockMouse.click(control.x, control.y);
    await view.waitForFrame(() => view.sentStops().length === 1, MODE_PASSES);
    expect(view.sentStops()).toEqual(["d2"]);
    view.client.close();
  });

  test("the palette offers the stop only where a row can be stopped",
       async () => {
    const view = await screen();

    view.mockInput.pressKey("k", { ctrl: true });
    await letReactRun(view);
    await view.mockInput.typeText("stop");
    await letReactRun(view);
    expect(view.frame()).not.toContain("Stop the selected background agent");
    await pressEscape(view);

    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });
    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);
    view.mockInput.pressKey("k", { ctrl: true });
    await letReactRun(view);
    await view.mockInput.typeText("stop");
    await letReactRun(view);
    expect(view.frame()).toContain("Stop the selected background agent");
    view.client.close();
  });

  test("escape leaves the workbench, and never stops anything", async () => {
    const view = await screen();
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });
    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);
    expect(view.frame()).toContain("enter Stop d1");

    await pressEscape(view);
    expect(view.sentStops()).toEqual([]);
    expect(view.frame()).not.toContain("enter Stop d1");
    // The panel is still drawn at this width — the work exists — it just no
    // longer holds the cursor.
    expect(view.frame()).toContain("d1 running");
    view.client.close();
  });
});

describe("the workbench and the rest of the screen", () => {
  test("an empty session draws no panel until one is asked for", async () => {
    const view = await screen();
    expect(view.frame()).not.toContain("Agents");

    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);
    expect(view.frame()).toContain("Agents");
    expect(view.frame()).toContain("No background work.");

    await pressEscape(view);
    expect(view.frame()).not.toContain("Agents");
    view.client.close();
  });

  test("tab still cycles the mode with the workbench focused", async () => {
    const view = await screen();
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });
    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);

    view.mockInput.pressTab();
    await letReactRun(view);
    await view.waitForFrame((frame) => frame.includes("[PLAN]"), MODE_PASSES);
    expect(view.sentModes()).toEqual(["plan"]);
    view.client.close();
  });

  test("a permission card outranks the workbench", async () => {
    const view = await screen();
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });
    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);

    await emitRun(view, "permission.requested", { ...PERMISSION });
    expect(view.frame()).toContain("Permission needed");

    // Enter belongs to the card, not to the delegate under the cursor.
    view.mockInput.pressEnter();
    await letReactRun(view);
    await view.waitForFrame((frame) => !frame.includes("Permission needed"),
                            MODE_PASSES);
    expect(view.sentStops()).toEqual([]);
    const replies = view.core.sent
      .filter((message) => message["method"] === "permission.reply");
    expect(replies.length).toBe(1);

    // And workbench state keeps flowing behind a card without disturbing it.
    await emitRun(view, "permission.requested", { ...PERMISSION, id: "p2" });
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "carry on", state: "active" }] });
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "stopping") });
    const frame = view.frame();
    expect(frame).toContain("Permission needed");
    expect(frame).toContain("carry on");
    expect(frame).toContain("d1 stopping");
    view.client.close();
  });

  test("an older core gets the older screen", async () => {
    const view = await screen(100, 30, undefined, undefined,
                              ["streaming", "questions", "permissions",
                               "modes", "tool_events"]);
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "a task", state: "active" }] });
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });

    expect(view.frame()).not.toContain("Tasks");
    expect(view.frame()).not.toContain("Agents");
    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);
    expect(view.frame()).not.toContain("Agents");

    // Everything else still works — chat is not held hostage to a capability.
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "still chatting" });
    expect(view.frame()).toContain("still chatting");
    view.client.close();
  });

  test("at sixty columns the conversation survives, and the workbench is a key away",
       async () => {
    const view = await screen(60, 24);
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "reading now" });
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "read_file",
                    summary: "read src/app.py" });
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "the plan", state: "active" }] });
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "running") });

    // No side panel at this width — and the count in the footer says the
    // agent exists even while its panel does not.
    let frame = view.frame();
    expect(frame).not.toContain("Agents");
    expect(frame).toContain("● 1 agent");
    expect(frame).toContain("reading now");
    expect(frame).toContain("ask for anything");
    rowsWithin(frame, 60);

    view.mockInput.pressKey("b", { ctrl: true });
    await letReactRun(view);
    frame = view.frame();
    expect(frame).toContain("Agents");
    expect(frame).toContain("Tasks");
    expect(frame).toContain("the plan");
    rowsWithin(frame, 60);

    await pressEscape(view);
    frame = view.frame();
    expect(frame).not.toContain("Agents");
    expect(frame).toContain("reading now");
    rowsWithin(frame, 60);
    view.client.close();
  });

  test("the side panel holds at every wide width", async () => {
    for (const width of [160, 120, 100]) {
      const view = await screen(width, 30);
      await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
        { text: "the plan", state: "active" }] });
      await emitRun(view, "delegate.updated",
                    { session_id: "s1", delegate: wireAgent("d1", "running") });

      const frame = view.frame();
      expect(frame).toContain("Agents");
      expect(frame).toMatch(/Tasks\s+0\/1/);
      expect(frame).toContain("ask for anything");
      rowsWithin(frame, width);
      view.client.close();
    }
  });

  test("tasks, agents, tools and a message coexist in one stream",
       async () => {
    const view = await screen();
    await emitRun(view, "message.started",
                  { turn_id: "t1", message_id: "m1" });
    await emitRun(view, "tool.started",
                  { turn_id: "t1", call_id: "a", name: "run_shell",
                    summary: "run: pytest" });
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "run the suite", state: "active" }] });
    await emitRun(view, "delegate.updated",
                  { session_id: "s1",
                    delegate: wireAgent("d1", "running",
                                        { label: "survey retries" }) });
    await emitRun(view, "message.delta",
                  { turn_id: "t1", message_id: "m1", text: "on it" });
    await emitRun(view, "tool.output",
                  { turn_id: "t1", call_id: "a", text: "collected 12\n" });

    // The last event is the one whose paint can still be a tick away on a
    // slow runner — one macrotask is not a guarantee that the projection has
    // reached the screen. Waiting on the frame is what every other assertion
    // on arriving output does; this one captured after a single yield and
    // failed on a Windows runner with the tool still "running…".
    await view.waitForFrame((frame) => frame.includes("collected 12"));
    const frame = view.frame();
    expect(frame).toContain("on it");
    expect(frame).toContain("run: pytest");
    expect(frame).toContain("collected 12");
    expect(frame).toContain("run the suite");
    expect(frame).toContain("survey retries");
    rowsWithin(frame, 100);
    view.client.close();
  });
});

describe("the workbench after a reconnect", () => {
  test("a client rebuilt from the snapshot sees the same work", async () => {
    const snapshot = {
      session: { id: "s1", mode: "act", workspace: "/work/project",
                 busy: true },
      revision: 9,
      messages: [
        { message_id: "user-t1", turn_id: "t1", role: "user",
          text: "do the thing", status: "completed", started_seq: 1 },
        { message_id: "m1", turn_id: "t1", role: "assistant",
          text: "on it", status: "completed", started_seq: 6 },
      ],
      tools: [
        { call_id: "a", turn_id: "t1", name: "read_file",
          summary: "read src/app.py", state: "completed", started_seq: 2,
          elapsed_ms: 340 },
        { call_id: "b", turn_id: "t1", name: "run_shell",
          summary: "run: pytest", state: "running", started_seq: 4,
          output: "collecting tests\n", output_truncated: true },
      ],
      tasks: [
        { text: "write the tests", state: "active" },
        { text: "read the code", state: "done" },
      ],
      delegates: [
        { id: "d1", label: "survey retries", state: "running", steps: 0,
          tool_calls: 0, tokens: 0, elapsed: 0.2,
          started_at: Math.floor(Date.now() / 1000) },
        { id: "d7", label: "old survey", state: "lost", steps: 3,
          tool_calls: 2, tokens: 50, elapsed: 40, started_at: 1,
          error: "the session ended while this was running" },
      ],
    };
    const view = await screen(100, 30, "s1", snapshot);

    expect(view.core.methods()).toContain("session.snapshot");
    expect(view.core.methods()).not.toContain("session.create");

    const frame = view.frame();
    expect(frame).toContain("read src/app.py");
    expect(frame).toContain("0.3s");
    expect(frame).toContain("run: pytest");
    expect(frame).toContain("collecting tests");
    expect(frame).toContain("earlier output is not kept");
    expect(frame).toMatch(/Tasks\s+1\/2/);
    expect(frame).toContain("write the tests");
    expect(frame).toContain("survey retries");
    expect(frame).toContain("d7 lost");
    expect(frame).toContain("the session ended");

    // And live events keep landing on the rebuilt state.
    await emitRun(view, "delegate.updated",
                  { session_id: "s1", delegate: wireAgent("d1", "stopping") });
    expect(view.frame()).toContain("d1 stopping");
    view.client.close();
  });

  test("a hole in the stream repairs the workbench too", async () => {
    const view = await screen();
    await emitRun(view, "tasks.updated", { session_id: "s1", tasks: [
      { text: "first plan", state: "active" }] });
    expect(view.frame()).toContain("first plan");

    view.core.snapshot = {
      session: { id: "s1", mode: "act", workspace: "/work/project",
                 busy: false },
      revision: 50, messages: [], tools: [],
      tasks: [{ text: "the true plan", state: "done" }],
      delegates: [{ id: "d9", label: "crashed work", state: "lost",
                    steps: 0, tool_calls: 0, tokens: 0, elapsed: 9,
                    started_at: 1,
                    error: "the session ended while this was running" }],
    };
    // An event numbered far above the last one applied: the projection
    // cannot know what it missed, so it says so and asks.
    view.core.push(event("tasks.updated",
                         { session_id: "s1",
                           tasks: [{ text: "stale hole",
                                     state: "pending" }] }, 50));
    await letReactRun(view);

    await view.waitForFrame((frame) => frame.includes("the true plan"),
                            MODE_PASSES);
    const frame = view.frame();
    expect(view.core.methods()).toContain("session.snapshot");
    expect(frame).toMatch(/Tasks\s+1\/1/);
    expect(frame).not.toContain("stale hole");
    expect(frame).not.toContain("first plan");
    expect(frame).toContain("d9 lost");
    view.client.close();
  });
});

describe("earlier conversations", () => {
  function stock(core: { stored: Array<{ id: string; title: string;
      messages: number; updatedAt: number;
      transcript: Array<{ role: string; text: string }> }> }): void {
    core.stored = [
      { id: "old-1", title: "fix the parser", messages: 12,
        updatedAt: Date.now() / 1000 - 3600,
        transcript: [
          { role: "user", text: "the parser drops braces" },
          { role: "assistant", text: "found it — the scanner skips them" },
        ] },
      { id: "old-2", title: "add the tests", messages: 40,
        updatedAt: Date.now() / 1000 - 7200,
        transcript: [{ role: "user", text: "cover the cache" }] },
    ];
  }

  test("the picker lists the store, and opening restores its transcript",
       async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    stock(view.core as never as Parameters<typeof stock>[0]);
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("earlier");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    await letReactRun(view);
    await waitForText(view, "type a title");

    let frame = view.frame();
    expect(frame).toContain("fix the parser");
    expect(frame).toContain("12 msg");
    expect(frame).toContain("add the tests");

    view.mockInput.pressEnter();
    await letReactRun(view);
    await view.waitForFrame((frame) =>
      frame.includes("the scanner skips them"), MODE_PASSES);

    // The transcript came back from the store, through the core — not from
    // any client-side memory of it.
    frame = view.frame();
    expect(frame).toContain("the parser drops braces");
    expect(view.core.methods()).toContain("session.open");
    view.client.close();
  });

  test("an empty store says so instead of opening nothing", async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("earlier");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    // The empty answer is a round trip too: the notice lands a hop after
    // the key, so wait on the text rather than on one settled frame.
    await waitForText(view, "no earlier conversations");

    const frame = view.frame();
    expect(frame).toContain("no earlier conversations");
    expect(frame).not.toContain("type a title");
    view.client.close();
  });

  test("Escape closes the picker without opening anything", async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    stock(view.core as never as Parameters<typeof stock>[0]);
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("earlier");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    await letReactRun(view);
    await waitForText(view, "type a title");

    await pressEscape(view);
    await view.waitForVisualIdle();
    expect(view.frame()).not.toContain("type a title");
    expect(view.core.methods()).not.toContain("session.open");
    view.client.close();
  });

  test("a draft in the composer does not travel to the opened session",
       async () => {
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    await view.mockInput.typeText("about the old conversation");
    await view.flush();
    stock(view.core as never as Parameters<typeof stock>[0]);
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("earlier");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    await letReactRun(view);
    await waitForText(view, "type a title");
    view.mockInput.pressEnter();
    await letReactRun(view);
    await waitForText(view, "the parser drops braces");

    // The draft belonged to the conversation it was typed for. Carrying it
    // into another session would send it to the wrong agent.
    const frame = view.frame();
    expect(frame).not.toContain("about the old conversation");
    view.client.close();
  });

  test("a shorter stored session opens past a longer live one's revision",
       async () => {
    // Revision is per-session: the guard that drops a stale snapshot of the
    // *same* session must not drop the first snapshot of a *different* one,
    // or a short stored conversation can never open over a long live one.
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    // Push the live session's sequence well past the stored one's length.
    for (let at = 1; at <= 6; at++) {
      await emitRun(view, "message.started",
                    { turn_id: "t1", message_id: `m${at}` });
      await emitRun(view, "message.delta",
                    { turn_id: "t1", message_id: `m${at}`,
                      text: `live message ${at}\n` });
      await emitRun(view, "message.completed",
                    { turn_id: "t1", message_id: `m${at}`,
                      text: `live message ${at}`, status: "completed" });
    }
    stock(view.core as never as Parameters<typeof stock>[0]);
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("earlier");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    await letReactRun(view);
    await waitForText(view, "type a title");
    view.mockInput.pressEnter();
    await letReactRun(view);

    // The stored session's snapshot carries revision 2 over a projection
    // that had reached the teens; it must win, whole.
    await waitForText(view, "the scanner skips them");
    expect(view.frame()).not.toContain("live message 1");
    view.client.close();
  });

  test("an event from the session left behind does not land on screen",
       async () => {
    // `session.open` leaves the first session alive — its worker may still
    // be finishing when the person is reading the reopened one, and its
    // events must never mix into the conversation on screen.
    const view = await screen();
    await view.waitForFrame((frame) => frame.includes("fake-1"));
    stock(view.core as never as Parameters<typeof stock>[0]);
    view.mockInput.pressKey("k", { ctrl: true });
    await view.waitForFrame((frame) => frame.includes("type a command"));
    await view.mockInput.typeText("earlier");
    await view.flush();
    await view.waitForVisualIdle();
    view.mockInput.pressEnter();
    await letReactRun(view);
    await waitForText(view, "type a title");
    view.mockInput.pressEnter();
    await letReactRun(view);
    await waitForText(view, "the parser drops braces");

    // The abandoned session's turn finishing now must not appear.
    view.core.emit("message.started",
                   { session_id: "s1", turn_id: "t9", message_id: "stale" });
    view.core.emit("message.delta",
                   { session_id: "s1", turn_id: "t9", message_id: "stale",
                     text: "words from the session you left" });
    await letReactRun(view);

    const frame = view.frame();
    expect(frame).not.toContain("words from the session you left");
    expect(frame).toContain("the scanner skips them");
    view.client.close();
  });
});

describe("what the conversation has cost", () => {
  test("the footer shows the fill and the cost the core reported",
       async () => {
    const view = await screen();
    await emitRun(view, "usage.updated", {
      session_id: "s1", context_used: 42_000, context_limit: 100_000,
      fill: 0.42, input_tokens: 50_000, output_tokens: 3_000,
      cost_usd: 0.137,
    });

    const frame = view.frame();
    expect(frame).toContain("42% ctx");
    expect(frame).toContain("$0.14");
    view.client.close();
  });

  test("a provider with no cost shows no cost, and never a guessed zero",
       async () => {
    const view = await screen();
    await emitRun(view, "usage.updated", {
      session_id: "s1", context_used: 8_000, context_limit: 32_000,
      fill: 0.25,
    });

    const frame = view.frame();
    expect(frame).toContain("25% ctx");
    expect(frame).not.toContain("$0.00");
    view.client.close();
  });

  test("a core too old to send usage leaves the corner empty", async () => {
    const view = await screen(100, 30, undefined, undefined,
                              ["streaming", "questions", "permissions",
                               "modes", "tool_events"]);
    await emitRun(view, "usage.updated", {
      session_id: "s1", fill: 0.9, cost_usd: 1.5,
    });
    const frame = view.frame();
    expect(frame).not.toContain("90% ctx");
    expect(frame).not.toContain("$1.50");
    view.client.close();
  });

  test("a rebuilt client sees the usage the snapshot carries", async () => {
    const snapshot = {
      session: { id: "s1", mode: "act", workspace: "/work/project",
                 busy: false },
      revision: 4, messages: [], tools: [],
      usage: { context_used: 12_000, context_limit: 100_000, fill: 0.12,
               cost_usd: 0.05 },
    };
    const view = await screen(100, 30, "s1", snapshot);
    const frame = view.frame();
    expect(frame).toContain("12% ctx");
    expect(frame).toContain("$0.05");
    view.client.close();
  });
});
