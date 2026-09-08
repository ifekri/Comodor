/**
 * Mode intent, driven the way a keyboard drives it: faster than the core can
 * answer.
 *
 * Each test spells out the round trips explicitly rather than using a fake
 * clock, because the property under test is an ordering — what is asked for
 * after what is confirmed — and not a duration.
 */

import { deepStrictEqual as same, ok, strictEqual as is } from "node:assert/strict";
import { test } from "node:test";

import {
  beginIntent,
  intentConfirmed,
  intentDue,
  intentSending,
  intentSettled,
  refuseIntent,
  stepIntent,
  wantMode,
  type ModeIntent,
} from "../src/index.ts";
import type { Mode } from "@comodor/modes";

/** A core that answers every request, one at a time, in order. */
function settle(intent: ModeIntent, agree: (mode: Mode) => boolean = () => true):
    { intent: ModeIntent; asked: Mode[] } {
  const asked: Mode[] = [];
  let held = intent;
  for (let guard = 0; guard < 20; guard += 1) {
    const next = intentDue(held);
    if (next === undefined) break;
    asked.push(next);
    held = intentSending(held, next);
    held = agree(next)
      ? intentConfirmed(held, next)
      : refuseIntent(held, `${next} is not allowed here`);
  }
  return { intent: held, asked };
}

test("one press asks for one mode", () => {
  const { intent, asked } = settle(stepIntent(beginIntent("act")));
  is(asked.length, 1);
  is(asked[0], "plan");
  is(intent.confirmed, "plan");
  ok(intentSettled(intent));
});

test("three presses inside one round trip still land on the third", () => {
  // The failure this exists for: F1 computed each press from the last
  // *confirmed* mode, so all three asked for `plan` and two were discarded.
  let intent = beginIntent("act");
  intent = stepIntent(intent);           // → plan
  intent = stepIntent(intent);           // → ask
  intent = stepIntent(intent);           // → act

  is(intent.desired, "act");
  is(intent.confirmed, "act", "the core has not been asked yet");
  is(intentDue(intent), undefined, "and nothing needs asking: it is already there");
});

test("two presses inside one round trip ask twice and end on the second", () => {
  let intent = beginIntent("act");
  intent = stepIntent(intent);           // desired plan
  const first = intentDue(intent);
  is(first, "plan");
  intent = intentSending(intent, "plan");

  // Another press, while the first request is still out.
  intent = stepIntent(intent);           // desired ask
  is(intentDue(intent), undefined, "only one mutation in flight per session");

  intent = intentConfirmed(intent, "plan");
  is(intentDue(intent), "ask", "the intent that arrived mid-flight is not lost");

  const { intent: done, asked } = settle(intent);
  is(done.confirmed, "ask");
  is(asked.length, 1, "intermediate states are coalesced, not replayed");
});

test("ten presses ask far fewer than ten times and still end correctly", () => {
  let intent = beginIntent("act");
  for (let press = 0; press < 10; press += 1) intent = stepIntent(intent);
  // act → plan → ask → act → … ten steps through a cycle of three.
  is(intent.desired, "plan");

  const { intent: done, asked } = settle(intent);
  is(done.confirmed, "plan");
  ok(asked.length <= 2, `asked ${asked.length} times`);
});

test("shift+tab walks the other way and keeps the same property", () => {
  let intent = beginIntent("act");
  intent = stepIntent(intent, true);     // → ask
  intent = stepIntent(intent, true);     // → plan
  is(intent.desired, "plan");

  const { intent: done, asked } = settle(intent);
  is(done.confirmed, "plan");
  is(asked.length, 1);
});

test("mixed directions end where the last press pointed", () => {
  let intent = beginIntent("act");
  intent = stepIntent(intent);           // plan
  intent = stepIntent(intent);           // ask
  intent = stepIntent(intent, true);     // plan
  is(intent.desired, "plan");

  is(settle(intent).intent.confirmed, "plan");
});

test("a slow acknowledgement does not drop the presses behind it", () => {
  let intent = beginIntent("act");
  intent = stepIntent(intent);                   // desired plan
  intent = intentSending(intent, "plan");        // asked

  intent = stepIntent(intent);                   // desired ask
  intent = stepIntent(intent);                   // desired act
  intent = stepIntent(intent);                   // desired plan

  // Only now does the first answer come back.
  intent = intentConfirmed(intent, "plan");
  is(intent.confirmed, "plan");
  is(intent.desired, "plan");
  is(intentDue(intent), undefined, "it already arrived where the person wanted");
});

test("naming a mode outright is the same intent as pressing towards it", () => {
  const intent = wantMode(beginIntent("act"), "ask");
  is(intentDue(intent), "ask");
  is(settle(intent).intent.confirmed, "ask");
});

test("a refusal keeps the core's mode and does not loop", () => {
  const intent = stepIntent(beginIntent("act"));
  const { intent: done, asked } = settle(intent, () => false);

  is(done.confirmed, "act", "the core is still the authority");
  is(done.desired, "act", "intent reconciles rather than asking for ever");
  is(asked.length, 1, "asking again would be a loop against a settled no");
  ok(done.refused);
  ok(intentSettled(done));
});

test("a refusal in the middle of a run stops that run and keeps the core's mode", () => {
  let intent = beginIntent("act");
  intent = stepIntent(intent);
  intent = stepIntent(intent);           // desired ask
  const { intent: done } = settle(intent, (mode) => mode !== "ask");

  is(done.confirmed, "act");
  ok(done.refused);
  ok(intentSettled(done));
});

test("the label never moves before the core says so", () => {
  let intent = beginIntent("act");
  intent = stepIntent(intent);
  intent = intentSending(intent, "plan");
  is(intent.confirmed, "act", "a client that moved first would show a lie");
});

test("a mode change the core reports on its own is adopted", () => {
  // Something else changed the mode — a palette entry in another client, or a
  // programmatic `session.set_mode`. Confirmation is confirmation.
  const intent = intentConfirmed(beginIntent("act"), "plan");
  is(intent.confirmed, "plan");
});

test("resuming a session starts from the mode it is actually in", () => {
  // A remount has no intent of its own. Beginning from anything other than the
  // resumed mode leaves a stale aim behind: a session already in Plan would
  // answer the first Tab by asking for Plan again.
  const resumed = beginIntent("plan");
  is(resumed.confirmed, "plan");
  is(resumed.desired, "plan");
  is(intentDue(resumed), undefined, "nothing to ask before anybody presses");

  const { intent, asked } = settle(stepIntent(resumed));
  same(asked, ["ask"], "one Tab from Plan goes to Ask");
  is(intent.confirmed, "ask");
});

test("a resync adopts the core's mode without dropping an outstanding aim", () => {
  // A gap forces a snapshot mid-intent. The core is authoritative about where
  // the mode is, but repairing a hole in the stream is not a reason to forget
  // what the person asked for a moment ago.
  let intent = beginIntent("act");
  intent = stepIntent(intent);                     // desired plan
  intent = intentSending(intent, "plan");          // asked, not yet answered

  intent = intentConfirmed(intent, "act");         // the snapshot says: still act

  is(intent.confirmed, "act");
  is(intent.desired, "plan");
  is(intentDue(intent), "plan", "and it is asked for again");
  is(settle(intent).intent.confirmed, "plan");
});
