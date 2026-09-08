import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { ALL, CYCLE, MODES, describe, isMode, next } from "../src/index.ts";

test("tab walks act, plan, ask and comes back", () => {
  assert.deepEqual(
    [next("act"), next("plan"), next("ask")],
    ["plan", "ask", "act"]);
});

test("shift-tab walks the other way", () => {
  assert.deepEqual(
    [next("act", true), next("plan", true), next("ask", true)],
    ["ask", "act", "plan"]);
});

test("chat is reachable by name and not by pressing the key", () => {
  assert.ok(ALL.includes("chat"));
  assert.ok(!CYCLE.includes("chat" as never));
  assert.equal(next("chat"), "act");
});

test("an unknown mode lands on the first rather than throwing", () => {
  // A client with a stale mode string should recover by pressing the key,
  // not by crashing on a name the core stopped using.
  assert.equal(next("turbo"), "act");
  assert.equal(describe("turbo").id, "act");
});

test("every mode has a label and a token, and the token is not a colour", () => {
  for (const mode of ALL) {
    const info = MODES[mode];
    assert.equal(info.label, mode.toUpperCase());
    assert.equal(info.token, `mode.${mode}`);
    assert.ok(info.summary.length > 10);
    assert.ok(!/#[0-9a-f]{3,6}/i.test(info.token));
  }
});

test("isMode accepts only the four", () => {
  assert.ok(isMode("plan"));
  assert.ok(!isMode("PLAN"));
  assert.ok(!isMode(""));
  assert.ok(!isMode(2));
});

test("these are the modes the core enforces", () => {
  // The one that matters: a mode a client can offer and the core will not
  // accept is a button that fails, and one the core has and the client hides
  // is a capability nobody can reach. The schema is generated from the same
  // definition the core reads.
  const here = fileURLToPath(new URL("../../../schemas/protocol/v1.json",
    import.meta.url));
  const schema = JSON.parse(readFileSync(here, "utf8")) as {
    $defs: { Mode: { enum: string[] } };
  };

  assert.deepEqual([...ALL], schema.$defs.Mode.enum);
});
