/**
 * The projection, against the sequences a real core produces — including the
 * ones a buggy core produces, since defining what happens then is the
 * difference between a wrong screen and a screen that says it is wrong.
 */

import { deepStrictEqual as same, ok, strictEqual as is } from "node:assert/strict";
import { test } from "node:test";

import {
  canSubmit,
  initial,
  OUTPUT_CAP,
  presented,
  presentedPermission,
  presentedQuestion,
  reduce,
  runningDelegates,
  stoppable,
  streaming,
  tasksDone,
  timeline,
  toolsOfTurn,
  unsent,
  waitingCount,
  type Action,
  type Snapshot,
  type State,
} from "../src/index.ts";
import type { Session } from "@comodor/protocol";

const SESSION: Session = {
  id: "s1", mode: "act", workspace: "/w", busy: false,
};

let clock = 0;

/**
 * An event, with the next sequence number, so tests read as sequences.
 *
 * The counter is monotonic across a test on purpose. `run([ev(...), ev(...)],
 * fresh())` evaluates its argument list left to right, so the events are
 * numbered *before* `fresh()` runs; a `fresh()` that reset the counter would
 * leave the next `ev()` in the same test numbering from one again, and the
 * projection would drop it as a duplicate of a sequence it had already
 * applied. That reads as a passing test which never exercised the event.
 */
function ev(name: string, params: Record<string, unknown>, seq?: number): Action {
  clock = seq ?? clock + 1;
  return { type: "event", name: name as never, params, seq: clock };
}

function run(actions: Action[], from: State = initial): State {
  return actions.reduce(reduce, from);
}

function fresh(): State {
  // The sequence counter is deliberately left where it is; see `ev`.
  return reduce(initial, { type: "connected", session: SESSION });
}

// --------------------------------------------------------------------------- //
// message correlation
// --------------------------------------------------------------------------- //

test("a delta joins the message its id names, not the newest one", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.started", { turn_id: "t1", message_id: "m2" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "first" }),
    ev("message.delta", { turn_id: "t1", message_id: "m2", text: "second" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "!" }),
  ], fresh());

  same(state.lines.map((line) => [line.id, line.text]),
       [["m1", "first!"], ["m2", "second"]]);
});

test("two messages in one turn are two lines", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Looking." }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Looking.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "c1", name: "read_file" }),
    ev("tool.completed", { turn_id: "t1", call_id: "c1" }),
    ev("message.started", { turn_id: "t1", message_id: "m2" }),
    ev("message.delta", { turn_id: "t1", message_id: "m2", text: "Done." }),
    ev("message.completed", { turn_id: "t1", message_id: "m2",
                              text: "Done.", status: "completed" }),
  ], fresh());

  is(state.lines.length, 2);
  same(state.lines.map((line) => line.text), ["Looking.", "Done."]);
  ok(state.lines.every((line) => line.turnId === "t1"));
  is(streaming(state), false);
});

test("a delta for an unknown message is dropped, not appended to a neighbour", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "mine" }),
    ev("message.delta", { turn_id: "t1", message_id: "ghost", text: "NOT MINE" }),
  ], fresh());

  is(state.lines.length, 1);
  is(state.lines[0]?.text, "mine");
});

test("a completed event before any start changes nothing", () => {
  const state = run([
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "hi", status: "completed" }),
  ], fresh());
  is(state.lines.length, 0);
});

test("a second start for the same id restarts it rather than duplicating", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "stale" }),
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "fresh" }),
  ], fresh());

  is(state.lines.length, 1, "two lines with one id is unusable as a key");
  is(state.lines[0]?.text, "fresh");
});

test("the completed text replaces the deltas, so a lost one is corrected", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Hel" }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Hello there", status: "completed" }),
  ], fresh());
  is(state.lines[0]?.text, "Hello there");
});

// --------------------------------------------------------------------------- //
// how a message ends
// --------------------------------------------------------------------------- //

test("a cancelled message keeps what arrived and says it was cancelled", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "half an" }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "half an", status: "cancelled" }),
  ], fresh());

  is(state.lines[0]?.state, "cancelled");
  is(state.lines[0]?.text, "half an");
  is(streaming(state), false);
});

test("a failed message carries its reason and stops streaming", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.completed", { turn_id: "t1", message_id: "m1", status: "failed",
                              error: "the provider fell over" }),
  ], fresh());

  is(state.lines[0]?.state, "failed");
  is(state.lines[0]?.error, "the provider fell over");
  is(streaming(state), false);
});

// --------------------------------------------------------------------------- //
// tools
// --------------------------------------------------------------------------- //

test("interleaved output from two tools stays under the right tool", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.started", { turn_id: "t1", call_id: "b", name: "bravo" }),
    ev("tool.output", { turn_id: "t1", call_id: "a", text: "A1\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "b", text: "B1\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "a", text: "A2\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "b", text: "B2\n" }),
  ], fresh());

  same(state.tools.map((tool) => [tool.id, tool.output]),
       [["a", "A1\nA2\n"], ["b", "B1\nB2\n"]]);
});

test("output for an unknown call is dropped rather than guessed at", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.output", { turn_id: "t1", call_id: "ghost", text: "not mine" }),
  ], fresh());
  is(state.tools[0]?.output, "");
});

test("a tool reports completed or failed, and carries the reason", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.started", { turn_id: "t1", call_id: "b", name: "bravo" }),
    ev("tool.completed", { turn_id: "t1", call_id: "a", elapsed_ms: 12 }),
    ev("tool.failed", { turn_id: "t1", call_id: "b", error: "it broke" }),
  ], fresh());

  is(state.tools[0]?.state, "completed");
  is(state.tools[0]?.elapsedMs, 12);
  is(state.tools[1]?.state, "failed");
  is(state.tools[1]?.error, "it broke");
});

test("tools are grouped by the turn that started them", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.started", { turn_id: "t2", call_id: "b", name: "bravo" }),
  ], fresh());

  same(toolsOfTurn(state, "t1").map((tool) => tool.id), ["a"]);
  same(toolsOfTurn(state, "t2").map((tool) => tool.id), ["b"]);
});

test("a repeated tool.started does not create a second row", () => {
  const state = run([
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
    ev("tool.output", { turn_id: "t1", call_id: "a", text: "kept" }),
    ev("tool.started", { turn_id: "t1", call_id: "a", name: "alpha" }),
  ], fresh());

  is(state.tools.length, 1);
  is(state.tools[0]?.output, "kept", "and does not wipe what it produced");
});

// --------------------------------------------------------------------------- //
// sending
// --------------------------------------------------------------------------- //

test("a prompt is shown at once and shown as pending", () => {
  const state = reduce(fresh(),
    { type: "sending", localId: "you-1", text: "fix the parser" });

  is(state.lines[0]?.speaker, "you");
  is(state.lines[0]?.text, "fix the parser");
  is(state.lines[0]?.state, "pending");
});

test("a rejected send keeps the text and says why", () => {
  const state = run([
    { type: "sending", localId: "you-1", text: "fix the parser" },
    { type: "rejected", localId: "you-1", reason: "already working" },
  ], fresh());

  is(state.lines[0]?.text, "fix the parser", "the text must not be lost");
  is(state.lines[0]?.state, "failed_to_send");
  is(state.lines[0]?.error, "already working");
  same(unsent(state).map((line) => line.text), ["fix the parser"]);
});

test("a retry clears the failure without duplicating the message", () => {
  const state = run([
    { type: "sending", localId: "you-1", text: "again" },
    { type: "rejected", localId: "you-1", reason: "busy" },
    { type: "retrying", localId: "you-1" },
    { type: "accepted", localId: "you-1", turnId: "t9" },
  ], fresh());

  is(state.lines.length, 1);
  is(state.lines[0]?.state, "completed");
  is(state.lines[0]?.turnId, "t9");
  is(unsent(state).length, 0);
});

// --------------------------------------------------------------------------- //
// sequence, duplicates and gaps
// --------------------------------------------------------------------------- //

test("an event already applied is not applied twice", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 5));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "x" }, 6));
  // The same delta again, as a redelivery would arrive.
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "x" }, 6));

  is(state.lines[0]?.text, "x");
  is(state.revision, 6);
});

test("an event from before the current revision is dropped", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 10));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "late" }, 4));

  is(state.lines[0]?.text, "");
  is(state.revision, 10);
});

test("a hole in the sequence is recorded rather than smoothed over", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 3));
  is(state.gap, false);
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "?" }, 9));

  is(state.gap, true, "five events never arrived; the session is incomplete");
  is(state.revision, 9);
});

// --------------------------------------------------------------------------- //
// snapshots
// --------------------------------------------------------------------------- //

function snapshotOf(revision: number): Snapshot {
  return {
    session: { ...SESSION, busy: true },
    revision,
    messages: [
      { message_id: "user-t1", turn_id: "t1", role: "user",
        text: "look at it", status: "completed" },
      { message_id: "m1", turn_id: "t1", role: "assistant",
        text: "Looking.", status: "completed" },
      { message_id: "m2", turn_id: "t1", role: "assistant",
        text: "Still going", status: "streaming" },
    ],
    tools: [
      { call_id: "c1", turn_id: "t1", name: "run_shell", state: "running",
        output: "line one\n" },
    ],
  };
}

test("a snapshot rebuilds the whole visible session", () => {
  const state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(20) });

  same(state.lines.map((line) => [line.speaker, line.text, line.state]), [
    ["you", "look at it", "completed"],
    ["comodor", "Looking.", "completed"],
    ["comodor", "Still going", "streaming"],
  ]);
  is(state.tools[0]?.output, "line one\n");
  is(state.tools[0]?.state, "running");
  is(state.revision, 20);
  is(state.connection.kind, "ready");
  is(streaming(state), true);
});

test("events after a snapshot continue it; events before it are dropped", () => {
  let state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(20) });
  // An event the snapshot already contains, arriving late.
  state = reduce(state, ev("tool.output", { turn_id: "t1", call_id: "c1",
                                            text: "line one\n" }, 18));
  // And one it does not.
  state = reduce(state, ev("tool.output", { turn_id: "t1", call_id: "c1",
                                            text: "line two\n" }, 21));

  is(state.tools[0]?.output, "line one\nline two\n",
     "the snapshot's own output must not be counted twice");
});

test("a stale snapshot does not undo newer events", () => {
  let state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(20) });
  state = reduce(state, ev("tool.output", { turn_id: "t1", call_id: "c1",
                                            text: "line two\n" }, 21));
  // A snapshot built before that event finally arrives.
  state = reduce(state, { type: "snapshot", snapshot: snapshotOf(19) });

  is(state.tools[0]?.output, "line one\nline two\n");
  is(state.revision, 21);
});

test("a snapshot clears a gap, because it is the repair for one", () => {
  let state = fresh();
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }, 3));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1", text: "?" }, 9));
  is(state.gap, true);

  state = reduce(state, { type: "snapshot", snapshot: snapshotOf(30) });
  is(state.gap, false);
});

test("a rebuilt projection equals one that watched the whole thing", () => {
  // A: connected throughout.
  clock = 0;
  const timeline: Action[] = [
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Looking." }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Looking.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "c1", name: "run_shell" }),
    ev("tool.output", { turn_id: "t1", call_id: "c1", text: "one\n" }),
    ev("tool.output", { turn_id: "t1", call_id: "c1", text: "two\n" }),
    ev("tool.completed", { turn_id: "t1", call_id: "c1" }),
  ];
  const watched = run(timeline, fresh());

  // B: joined at the fifth event, from a snapshot describing the first four.
  const halfway = run(timeline.slice(0, 5), fresh());
  const rebuilt = run(timeline.slice(5), reduce(fresh(), {
    type: "snapshot",
    snapshot: {
      session: SESSION,
      revision: 5,
      messages: [{ message_id: "m1", turn_id: "t1", role: "assistant",
                   text: "Looking.", status: "completed" }],
      tools: [{ call_id: "c1", turn_id: "t1", name: "run_shell",
                state: "running", output: "one\n" }],
    },
  }));

  is(halfway.tools[0]?.output, "one\n");
  same(rebuilt.lines.map((line) => [line.id, line.text, line.state]),
       watched.lines.map((line) => [line.id, line.text, line.state]));
  same(rebuilt.tools.map((tool) => [tool.id, tool.output, tool.state]),
       watched.tools.map((tool) => [tool.id, tool.output, tool.state]));
});

test("a snapshot that shortened output says so", () => {
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: {
      session: SESSION, revision: 4, messages: [],
      tools: [{ call_id: "c1", turn_id: "t1", name: "run_shell",
                state: "completed", output: "…the tail", output_truncated: true }],
    },
  });
  is(state.tools[0]?.outputTruncated, true);
});

// --------------------------------------------------------------------------- //
// the order a rebuilt session draws in
// --------------------------------------------------------------------------- //

/** A turn of answer, tool, answer, tool, answer — as the core numbers it. */
const INTERLEAVED: Snapshot = {
  session: SESSION,
  revision: 11,
  messages: [
    { message_id: "A", turn_id: "t1", role: "assistant", text: "Looking.",
      status: "completed", started_seq: 1 },
    { message_id: "B", turn_id: "t1", role: "assistant", text: "Found it.",
      status: "completed", started_seq: 6 },
    { message_id: "C", turn_id: "t1", role: "assistant", text: "",
      status: "streaming", started_seq: 9 },
  ],
  tools: [
    { call_id: "X", turn_id: "t1", name: "read_file", state: "completed",
      started_seq: 3 },
    { call_id: "Y", turn_id: "t1", name: "edit_file", state: "running",
      started_seq: 8 },
  ],
};

test("a snapshot keeps a turn interleaved rather than messages then tools", () => {
  const state = reduce(fresh(), { type: "snapshot", snapshot: INTERLEAVED });

  same(timeline(state).map((entry) => entry.kind === "line"
    ? `message:${entry.line.id}` : `tool:${entry.tool.id}`),
       ["message:A", "tool:X", "message:B", "tool:Y", "message:C"]);
});

test("a rebuilt session draws in the same order as one that watched it", () => {
  // The same turn, arrived at by watching the events instead of by snapshot.
  const watched = run([
    ev("message.started", { turn_id: "t1", message_id: "A" }),
    ev("message.completed", { turn_id: "t1", message_id: "A",
                              text: "Looking.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "X", name: "read_file" }),
    ev("tool.completed", { turn_id: "t1", call_id: "X" }),
    ev("message.started", { turn_id: "t1", message_id: "B" }),
    ev("message.completed", { turn_id: "t1", message_id: "B",
                              text: "Found it.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "Y", name: "edit_file" }),
    ev("message.started", { turn_id: "t1", message_id: "C" }),
  ], fresh());
  const rebuilt = reduce(fresh(), { type: "snapshot", snapshot: INTERLEAVED });

  const order = (state: State) => timeline(state).map((entry) =>
    entry.kind === "line" ? `message:${entry.line.id}` : `tool:${entry.tool.id}`);
  same(order(rebuilt), order(watched));
});

test("an open message in a snapshot is still streaming", () => {
  const state = reduce(fresh(), { type: "snapshot", snapshot: INTERLEAVED });
  const open = state.lines.find((line) => line.id === "C");

  is(open?.state, "streaming");
  is(streaming(state), true, "so a client keeps listening for its deltas");
});

test("deltas after a snapshot continue the message it called streaming", () => {
  let state = reduce(fresh(), { type: "snapshot", snapshot: INTERLEAVED });
  state = reduce(state, ev("message.delta",
    { turn_id: "t1", message_id: "C", text: "Done." }, 12));
  state = reduce(state, ev("message.completed",
    { turn_id: "t1", message_id: "C", text: "Done.", status: "completed" }, 13));

  is(state.lines.length, 3, "continued, not duplicated");
  const finished = state.lines.find((line) => line.id === "C");
  is(finished?.text, "Done.");
  is(finished?.state, "completed");
  is(streaming(state), false);
});

test("several turns keep their history in order after a rebuild", () => {
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: {
      session: SESSION,
      revision: 8,
      // Deliberately listed turn by turn rather than in sequence, to prove the
      // ordering comes from the numbers and not from the array's own order.
      messages: [
        { message_id: "b1", turn_id: "t2", role: "assistant", text: "second",
          status: "completed", started_seq: 6 },
        { message_id: "a1", turn_id: "t1", role: "assistant", text: "first",
          status: "completed", started_seq: 2 },
      ],
      tools: [
        { call_id: "y", turn_id: "t2", name: "edit_file", state: "completed",
          started_seq: 7 },
        { call_id: "x", turn_id: "t1", name: "read_file", state: "completed",
          started_seq: 4 },
      ],
    },
  });

  same(timeline(state).map((entry) => entry.kind === "line"
    ? entry.line.id : entry.tool.id), ["a1", "x", "b1", "y"]);
});

test("the prompt stays ahead of the answer when they share a number", () => {
  // The core records the person's own message against the number the session
  // is about to use. Should the two ever tie, the stable merge must not put
  // the answer above the question it answers.
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: {
      session: SESSION, revision: 2,
      messages: [
        { message_id: "user-t1", turn_id: "t1", role: "user",
          text: "have a look", status: "completed", started_seq: 1 },
        { message_id: "A", turn_id: "t1", role: "assistant", text: "",
          status: "streaming", started_seq: 1 },
      ],
      tools: [],
    },
  });

  same(state.lines.map((line) => line.id), ["user-t1", "A"]);
});

// --------------------------------------------------------------------------- //
// what a snapshot restores besides the transcript
// --------------------------------------------------------------------------- //

test("a pending question survives a rebuild", () => {
  const form = { id: "ask-1", session_id: "s1", title: "before I start",
                 questions: [] };
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: { ...INTERLEAVED, question: form },
  });

  same(presentedQuestion(state), form,
       "so the client can answer what is still waiting");
});

test("a snapshot with nothing waiting leaves no stale question", () => {
  let state = reduce(fresh(), {
    type: "snapshot",
    snapshot: { ...INTERLEAVED, question: { id: "ask-1", questions: [] } },
  });
  ok(presentedQuestion(state));

  // The question was answered elsewhere, and the rebuild says so.
  state = reduce(state, { type: "snapshot", snapshot: { ...INTERLEAVED,
                                                        revision: 12 } });
  is(presentedQuestion(state), undefined);
  is(state.interactions.length, 0);
});

test("a pending permission survives a rebuild", () => {
  const asked = { id: "perm-1", session_id: "s1", title: "run this?",
                  options: ["allow", "deny"] };
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: { ...INTERLEAVED, permission: asked },
  });

  same(presentedPermission(state), asked, "carried, not silently dropped");
});

test("a snapshot carrying the whole list restores all of it", () => {
  const permission = { id: "perm-1", title: "run this?",
                       options: ["allow", "deny"] };
  const question = { id: "ask-1", title: "which?", questions: [] };
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: {
      ...INTERLEAVED,
      permission, question,
      interactions: [
        { kind: "permission", permission },
        { kind: "question", question },
      ],
    },
  });

  same(state.interactions.map((each) => [each.kind, each.id]),
       [["permission", "perm-1"], ["question", "ask-1"]]);
  same(presentedPermission(state), permission);
  is(waitingCount(state), 2);
});

test("a rebuild reports the session as busy when the core says it is", () => {
  const state = reduce(fresh(), {
    type: "snapshot",
    snapshot: { ...INTERLEAVED, session: { ...SESSION, mode: "plan",
                                           busy: true } },
  });

  is(state.session?.busy, true);
  is(state.session?.mode, "plan");
});

// --------------------------------------------------------------------------- //
// connection and mode
// --------------------------------------------------------------------------- //

test("resynchronising is not the same state as starting", () => {
  const state = reduce(fresh(), { type: "resynchronising" });
  is(state.connection.kind, "resynchronising");
});

test("the mode follows the core and nothing else", () => {
  const state = run([
    ev("mode.changed", { session_id: "s1", mode: "plan" }),
  ], fresh());
  is(state.session?.mode, "plan");
});

test("an unknown event leaves the state alone", () => {
  const before = fresh();
  const after = reduce(before, ev("something.new" as never, { any: 1 }));
  same(after.lines, before.lines);
  same(after.tools, before.tools);
});

// --------------------------------------------------------------------------- //
// drawing order
// --------------------------------------------------------------------------- //

test("the timeline interleaves messages and the tools between them", () => {
  const state = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "Looking." }),
    ev("message.completed", { turn_id: "t1", message_id: "m1",
                              text: "Looking.", status: "completed" }),
    ev("tool.started", { turn_id: "t1", call_id: "c1", name: "read_file" }),
    ev("tool.started", { turn_id: "t1", call_id: "c2", name: "run_shell" }),
    ev("tool.completed", { turn_id: "t1", call_id: "c1" }),
    ev("message.started", { turn_id: "t1", message_id: "m2" }),
    ev("message.delta", { turn_id: "t1", message_id: "m2", text: "Done." }),
  ], fresh());

  same(timeline(state).map((entry) => entry.kind === "line"
    ? `msg:${entry.line.text}` : `tool:${entry.tool.name}`),
    ["msg:Looking.", "tool:read_file", "tool:run_shell", "msg:Done."]);
});

test("the person's prompt comes before the answer to it", () => {
  let state = fresh();
  state = reduce(state, { type: "sending", localId: "you-1", text: "hello" });
  state = reduce(state, { type: "accepted", localId: "you-1", turnId: "t1" });
  state = reduce(state, ev("message.started", { turn_id: "t1", message_id: "m1" }));
  state = reduce(state, ev("message.delta", { turn_id: "t1", message_id: "m1",
                                              text: "hi back" }));

  same(timeline(state).map((entry) => entry.kind === "line"
    ? entry.line.text : "?"), ["hello", "hi back"]);
});

test("a snapshot's timeline keeps a turn's messages and tools together", () => {
  const state = reduce(fresh(), { type: "snapshot", snapshot: snapshotOf(9) });
  const order = timeline(state).map((entry) => entry.kind);
  is(order.filter((kind) => kind === "line").length, 3);
  is(order.filter((kind) => kind === "tool").length, 1);
  // Ordering is total and stable, which is what a keyed render needs.
  const at = timeline(state).map((entry) => entry.at);
  same(at, [...at].sort((left, right) => left - right));
  is(new Set(at).size, at.length, "two entries must never share a position");
});

// --------------------------------------------------------------------------- //
// what is waiting on the person
// --------------------------------------------------------------------------- //

const PERMISSION = { id: "perm-1", session_id: "s1", title: "run: npm test",
                     options: ["allow", "allow_always", "deny"],
                     tool: "run_shell", risk: "dangerous" };
const QUESTION = { id: "ask-1", session_id: "s1", title: "which approach?",
                   questions: [{ header: "approach", prompt: "Which?",
                                 multiple: false, options: [] }] };

function withPermission(state: State = fresh()): State {
  return reduce(state, ev("permission.requested", PERMISSION));
}

test("two questions live at once are both kept", () => {
  // A batch of read-only tools runs in parallel, and each may ask. One slot
  // would strand the second, and a stranded prompt is a tool that looks hung.
  const state = run([
    ev("question.requested", QUESTION),
    ev("question.requested", { ...QUESTION, id: "ask-2" }),
  ], fresh());

  same(state.interactions.map((each) => each.id), ["ask-1", "ask-2"]);
  is(waitingCount(state), 2);
  is(presented(state)?.id, "ask-1", "what has waited longest is shown");
});

test("a question and a permission can both be waiting", () => {
  const state = run([
    ev("permission.requested", PERMISSION),
    ev("question.requested", QUESTION),
  ], fresh());

  same(state.interactions.map((each) => each.kind), ["permission", "question"]);
  same(presentedPermission(state)?.["id"], "perm-1");
  is(presentedQuestion(state), undefined,
     "the permission is what is being presented, so it is the only question asked of the person");
});

test("resolving one leaves the other waiting", () => {
  let state = run([
    ev("permission.requested", PERMISSION),
    ev("question.requested", QUESTION),
  ], fresh());

  state = reduce(state, ev("permission.resolved",
                           { id: "perm-1", choice: "deny" }));

  same(state.interactions.map((each) => each.id), ["ask-1"]);
  same(presentedQuestion(state)?.["id"], "ask-1");
});

test("a redelivered request replaces itself rather than doubling", () => {
  const state = run([
    ev("permission.requested", PERMISSION),
    ev("permission.requested", PERMISSION),
  ], fresh());

  is(state.interactions.length, 1, "two cards for one request is unusable");
  is(canSubmit(state, "perm-1"), true);
});

test("a resolution for an unknown request changes nothing", () => {
  const state = withPermission();
  const after = reduce(state, ev("permission.resolved",
                                 { id: "perm-ghost", choice: "deny" }));

  same(after.interactions, state.interactions);
});

// --------------------------------------------------------------------------- //
// one decision per request
// --------------------------------------------------------------------------- //

test("a decision in flight cannot be sent twice", () => {
  // Two presses inside one round trip are otherwise two replies, and the
  // second is refused by a core that has already closed the request — which
  // reads as a broken interface rather than as the no-op it was.
  let state = reduce(withPermission(), { type: "submitting", id: "perm-1" });

  is(state.interactions[0]?.state, "submitting");
  is(canSubmit(state, "perm-1"), false);

  const again = reduce(state, { type: "submitting", id: "perm-1" });
  is(again.interactions[0]?.state, "submitting");
  same(again.interactions, state.interactions, "and nothing was rebuilt");
});

test("a refused decision leaves the request answerable", () => {
  // The core did not take it, so it is still waiting. A card that vanished on
  // an error would strand the prompt it was showing.
  let state = reduce(withPermission(), { type: "submitting", id: "perm-1" });
  state = reduce(state, { type: "submitFailed", id: "perm-1",
                          reason: "nothing is waiting under that id" });

  is(state.interactions[0]?.state, "failed");
  is(state.interactions[0]?.error, "nothing is waiting under that id");
  is(canSubmit(state, "perm-1"), true, "so it can be tried again, or denied");
});

test("a failure reported for something not in flight is ignored", () => {
  const state = withPermission();
  const after = reduce(state, { type: "submitFailed", id: "perm-1",
                                reason: "stale" });

  is(after.interactions[0]?.state, "waiting");
  is(after.interactions[0]?.error, undefined);
});

test("the core resolving it wins over a reply still in flight", () => {
  // Answered elsewhere, or timed out. Either way the card goes, and a late
  // failure for it must not put it back.
  let state = reduce(withPermission(), { type: "submitting", id: "perm-1" });
  state = reduce(state, ev("permission.resolved",
                           { id: "perm-1", choice: "deny" }));
  is(state.interactions.length, 0);

  state = reduce(state, { type: "submitFailed", id: "perm-1", reason: "late" });
  is(state.interactions.length, 0, "no resurrected card");
});

test("a rebuild clears a decision that was in flight", () => {
  // The snapshot is the core's account. Whatever was in flight when the
  // connection was repaired is not in flight any more.
  let state = reduce(withPermission(), { type: "submitting", id: "perm-1" });
  state = reduce(state, {
    type: "snapshot",
    // Above whatever has been applied, or the snapshot is the stale one and
    // the projection correctly refuses it.
    snapshot: { ...INTERLEAVED, revision: state.revision + 1,
                permission: PERMISSION,
                interactions: [{ kind: "permission", permission: PERMISSION }] },
  });

  is(state.interactions[0]?.state, "waiting");
  is(state.interactions[0]?.error, undefined);
  is(canSubmit(state, "perm-1"), true);
});

// --------------------------------------------------------------------------- //
// a draft is not disturbed by the stream behind it
// --------------------------------------------------------------------------- //

test("unrelated events leave a waiting request alone", () => {
  // Somebody halfway through a form must not lose their place because the
  // turn behind it streamed a token. The identity of the request is what the
  // presentation keys its draft on, so it has to survive untouched.
  const state = run([
    ev("permission.requested", PERMISSION),
    ev("question.requested", QUESTION),
  ], fresh());
  const before = presented(state);

  const after = run([
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "still going" }),
    ev("tool.output", { turn_id: "t1", call_id: "c1", text: "noise\n" }),
    ev("notification.created", { level: "info", text: "a note" }),
    ev("mode.changed", { session_id: "s1", mode: "plan" }),
    ev("session.updated", { session: { ...SESSION, busy: true } }),
  ], state);

  is(presented(after), before, "the same object, so a draft keyed on it survives");
  is(after.interactions.length, 2);
});

// --------------------------------------------------------------------------- //
// the workbench: tasks and delegates
// --------------------------------------------------------------------------- //

function wireDelegate(id: string, state: string,
                      extra: Record<string, unknown> = {}) {
  return { id, label: `work ${id}`, state, steps: 0, tool_calls: 0,
           tokens: 0, elapsed: 0, started_at: 100, ...extra };
}

test("a task list is replaced whole, never merged", () => {
  const state = run([
    ev("tasks.updated", { session_id: "s1", tasks: [
      { text: "read the code", state: "done" },
      { text: "write the tests", state: "active" },
      { text: "a task that will be dropped", state: "pending" },
    ] }),
    ev("tasks.updated", { session_id: "s1", tasks: [
      { text: "write the tests", state: "active" },
      { text: "read the code", state: "done" },
    ] }),
  ], fresh());

  same(state.tasks.map((task) => [task.text, task.state]),
       [["write the tests", "active"], ["read the code", "done"]],
  );
  is(tasksDone(state.tasks), 1);
});

test("an unknown task state is held as pending, not passed through", () => {
  const state = run([
    ev("tasks.updated", { session_id: "s1", tasks: [
      { text: "kept", state: "blocked" },
      { text: "coerced", state: "exploded" },
      { text: "", state: "pending" },
      "junk",
    ] }),
  ], fresh());

  same(state.tasks.map((task) => [task.text, task.state]),
       [["kept", "blocked"], ["coerced", "pending"]]);
});

test("two active tasks are shown as two active tasks", () => {
  // The tool recommends one active item and tolerates more. The projection
  // reports what the core said; "fixing" it here would be the client
  // disagreeing with the only authority either of them has.
  const state = run([
    ev("tasks.updated", { session_id: "s1", tasks: [
      { text: "one", state: "active" },
      { text: "two", state: "active" },
    ] }),
  ], fresh());

  is(state.tasks.filter((task) => task.state === "active").length, 2);
});

test("a delegate record is replaced whole, by id", () => {
  const state = run([
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "running",
                                                    { error: "stale" }) }),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "done",
                                                    { steps: 4, tokens: 99 }) }),
  ], fresh());

  is(state.delegates.length, 1);
  is(state.delegates[0]?.state, "done");
  is(state.delegates[0]?.steps, 4);
  is(state.delegates[0]?.tokens, 99);
  is(state.delegates[0]?.error, undefined,
     "a half-merge would keep the old error beside the new state");
});

test("a late announcement cannot move a delegate backwards", () => {
  const state = run([
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "running") }),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "stopping") }),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "running") }),
  ], fresh());

  is(state.delegates[0]?.state, "stopping");
});

test("a terminal delegate state is final", () => {
  const from = run([
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "stopped") }),
  ], fresh());

  for (const late of ["running", "stopping", "done", "lost"]) {
    const after = run([
      ev("delegate.updated", { session_id: "s1",
                               delegate: wireDelegate("d1", late) }),
    ], from);
    is(after.delegates[0]?.state, "stopped", `${late} displaced a terminal`);
  }
});

test("a lost delegate stays lost", () => {
  // The state that matters most after a crash: work that died with the
  // process must never be redrawn as work in flight.
  const state = run([
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d7", "lost", {
                               error: "the session ended while this was running",
                             }) }),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d7", "running") }),
  ], fresh());

  is(state.delegates[0]?.state, "lost");
  is(state.delegates[0]?.error, "the session ended while this was running");
  is(stoppable(state.delegates[0]!), false);
});

test("stoppable is the lifecycle's answer, not the renderer's", () => {
  const running = run([ev("delegate.updated", { session_id: "s1",
    delegate: wireDelegate("d1", "running") })], fresh());
  is(stoppable(running.delegates[0]!), true);
  is(runningDelegates(running).length, 1);

  const stopping = run([ev("delegate.updated", { session_id: "s1",
    delegate: wireDelegate("d1", "stopping") })], running);
  is(stoppable(stopping.delegates[0]!), false,
     "the stop is already asked for");
  is(runningDelegates(stopping).length, 1, "still in flight until it settles");

  const done = run([ev("delegate.updated", { session_id: "s1",
    delegate: wireDelegate("d1", "done") })], stopping);
  is(runningDelegates(done).length, 0);
});

test("workbench events join the one sequence domain", () => {
  // A tasks update between two message deltas is not a gap, and a jump over
  // one is: the workbench states ride the session's counter like everything
  // else, so one revision repairs all of them.
  const continuous = run([
    ev("message.started", { turn_id: "t1", message_id: "m1" }, 10),
    ev("tasks.updated", { session_id: "s1", tasks: [] }, 11),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "running") }, 12),
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "x" }, 13),
  ], fresh());
  is(continuous.gap, false);
  is(continuous.revision, 13);

  const holed = run([
    ev("message.delta", { turn_id: "t1", message_id: "m1", text: "y" }, 20),
  ], continuous);
  is(holed.gap, true, "a hole around a workbench event must be detected");
});

test("a snapshot restores the tasks and the delegates", () => {
  const snapshot: Snapshot = {
    session: SESSION,
    revision: 40,
    messages: [],
    tools: [],
    tasks: [
      { text: "read the code", state: "done" },
      { text: "write the tests", state: "active" },
    ],
    delegates: [
      wireDelegate("d1", "done", { steps: 3, tokens: 40, elapsed: 12.4,
                                   started_at: 900 }) as never,
      wireDelegate("d7", "lost") as never,
    ],
  };

  const state = reduce(fresh(), { type: "snapshot", snapshot });

  same(state.tasks.map((task) => [task.text, task.state]),
       [["read the code", "done"], ["write the tests", "active"]]);
  same(state.delegates.map((each) => [each.id, each.state]),
       [["d1", "done"], ["d7", "lost"]]);
  is(state.delegates[0]?.steps, 3);
  is(state.delegates[0]?.startedAt, 900);
  is(state.revision, 40);
});

test("a rebuilt projection equals one that watched the work happen", () => {
  const watched = run([
    ev("tasks.updated", { session_id: "s1", tasks: [
      { text: "one", state: "active" }, { text: "two", state: "pending" }] }),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "running") }),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "stopping") }),
  ], fresh());

  const rebuilt = reduce(fresh(), { type: "snapshot", snapshot: {
    session: SESSION,
    revision: watched.revision,
    messages: [],
    tools: [],
    tasks: [{ text: "one", state: "active" }, { text: "two", state: "pending" }],
    delegates: [wireDelegate("d1", "stopping") as never],
  } });

  same(rebuilt.tasks, watched.tasks);
  same(rebuilt.delegates, watched.delegates);
});

test("a stale snapshot cannot undo a newer workbench state", () => {
  const watched = run([
    ev("tasks.updated", { session_id: "s1", tasks: [
      { text: "newest", state: "done" }] }),
    ev("delegate.updated", { session_id: "s1",
                             delegate: wireDelegate("d1", "done") }),
  ], fresh());

  const after = reduce(watched, { type: "snapshot", snapshot: {
    session: SESSION,
    revision: watched.revision - 1,
    messages: [],
    tools: [],
    tasks: [{ text: "older", state: "pending" }],
    delegates: [wireDelegate("d1", "running") as never],
  } });

  is(after, watched, "the whole snapshot is dropped below the revision");
});

test("tool output is bounded to the tail the core would also keep", () => {
  let state = run([
    ev("tool.started", { turn_id: "t1", call_id: "c1", name: "run_shell" }),
  ], fresh());

  const chunk = "x".repeat(10_000) + "\n";
  for (let index = 0; index < 10; index += 1) {
    state = run([ev("tool.output", { turn_id: "t1", call_id: "c1",
                                     text: chunk })], state);
  }

  const tool = state.tools[0]!;
  ok(tool.output.length <= OUTPUT_CAP,
     `held ${tool.output.length} characters, cap is ${OUTPUT_CAP}`);
  is(tool.outputTruncated, true, "the shortening is said, not silent");
  ok(tool.output.endsWith("x\n"));
});
