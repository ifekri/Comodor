/**
 * Launching a core that is not there.
 *
 * The commonest first-run failure is `comodor` not being on PATH. Node
 * reports that through the child's `error` event, and an `error` event with
 * no listener does not reject anything — it takes the whole process down. So
 * the TUI's careful startup diagnostic never printed, and a person saw a Node
 * stack trace instead.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { CoreClient } from "../src/index.ts";
import { spawnCore } from "../src/spawn.ts";

test("a command that does not exist rejects instead of killing the process",
     async () => {
  const notes: string[] = [];
  const transport = spawnCore({
    command: "comodor-does-not-exist-9d4f1a",
    onDiagnostic: (text) => notes.push(text),
  });

  const client = new CoreClient(transport, {
    timeoutMs: 5_000,
    onDiagnostic: (text) => notes.push(text),
  });

  await assert.rejects(client.start());
  // And the reason is available, rather than the process simply being gone.
  assert.ok(notes.some((note) => /could not start/.test(note)),
    `no diagnostic explained the failure: ${JSON.stringify(notes)}`);

  await transport.close();
});

test("closing a core that never started does not throw", async () => {
  const transport = spawnCore({ command: "comodor-does-not-exist-9d4f1a" });
  await transport.close();
});
