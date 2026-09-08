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
        capabilities: ["streaming", "questions", "permissions", "modes"],
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
    if (method === "session.set_mode") {
      // The core is the authority. The client must not move its own label;
      // it waits for the event, which is what these tests then assert on.
      this.mode = String(params["mode"]);
      this.push(response(id, { session: this.session() }));
      this.push(event("mode.changed",
        { session_id: "s1", mode: this.mode }));
      this.push(event("session.updated", { session: this.session() }));
      return;
    }
    this.push(response(id, {}));
  }

  close(): void {
    this.done = true;
    for (const waiter of this.waiting.splice(0)) waiter(null);
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

  session() {
    return { id: "s1", mode: this.mode, workspace: "/work/project",
             busy: false };
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
                      snapshot?: Record<string, unknown>) {
  const core = new FakeCore();
  if (snapshot) core.snapshot = snapshot;
  const client = new CoreClient(core, { timeoutMs: 5_000 });
  await client.start();

  let quit = false;
  const rendered = await testRender(
    <App client={client} onQuit={() => { quit = true; }} sessionId={sessionId} />,
    { width, height });

  await rendered.flush();
  // The session arrives asynchronously; wait for the workspace to appear
  // rather than for a number of frames.
  await rendered.waitForFrame((frame) => frame.includes("project"));

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

describe("leaving", () => {
  test("Ctrl+D quits", async () => {
    const view = await screen();
    view.mockInput.pressKey("d", { ctrl: true });
    await view.flush();

    expect(view.quit()).toBe(true);
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

/** The palette row currently marked as selected. */
function markedRow(frame: string): string {
  for (const row of frame.split("\n")) {
    const at = row.indexOf("›");
    if (at >= 0) return row.slice(at + 1).trim();
  }
  return "";
}
