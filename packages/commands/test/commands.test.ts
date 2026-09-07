import assert from "node:assert/strict";
import test from "node:test";

import { CommandRegistry, type Command } from "../src/index.ts";

interface Context { ran: string[]; busy?: boolean }

function registry(): CommandRegistry<Context> {
  const made = new CommandRegistry<Context>();
  const command = (id: string, title: string, extra: Partial<Command<Context>> = {}):
      Command<Context> => ({
    id, title, run: (context) => { context.ran.push(id); }, ...extra,
  });
  made.add(
    command("session.new", "New session"),
    command("session.cancel", "Cancel", {
      enabled: (context) => Boolean(context.busy),
    }),
    command("mode.next", "Next mode", { keywords: ["act", "plan", "ask"] }),
    command("model.change", "Change model"),
  );
  return made;
}

test("a command runs by id", async () => {
  const context: Context = { ran: [] };
  assert.equal(await registry().run("session.new", context), true);
  assert.deepEqual(context.ran, ["session.new"]);
});

test("a command nobody registered does not run", async () => {
  assert.equal(await registry().run("session.teleport", { ran: [] }), false);
});

test("a disabled command does not run", async () => {
  const context: Context = { ran: [], busy: false };
  assert.equal(await registry().run("session.cancel", context), false);
  assert.deepEqual(context.ran, []);
});

test("two commands cannot claim one id", () => {
  const made = registry();
  assert.throws(() => made.add({ id: "mode.next", title: "Again", run: () => {} }),
    /claim the id/);
});

test("a key bound to nothing is refused when the client is built", () => {
  // The failure this prevents is a footer that advertises a key which does
  // nothing — caught here rather than by somebody pressing it.
  assert.throws(() => registry().bind({ key: "ctrl+s", command: "session.save" }),
    /not a command/);
});

test("every advertised shortcut resolves to a command", () => {
  const made = registry().bind(
    { key: "tab", command: "mode.next", hint: "Mode" },
    { key: "ctrl+n", command: "session.new", hint: "New" },
    { key: "esc", command: "session.cancel" },
  );

  for (const binding of made.hints()) {
    assert.ok(made.get(binding.command),
      `${binding.key} is advertised as ${binding.hint} and resolves to nothing`);
  }
  // The unadvertised binding is real but not printed, which is allowed.
  assert.deepEqual(made.hints().map((b) => b.key), ["tab", "ctrl+n"]);
});

test("a key press finds its command", () => {
  const made = registry().bind({ key: "tab", command: "mode.next" });
  assert.equal(made.forKey("tab")?.id, "mode.next");
  assert.equal(made.forKey("f9"), undefined);
});

test("search puts a title match above a keyword match", () => {
  const found = registry().search("mode");
  assert.equal(found[0]?.id, "mode.next");
});

test("search matches a word people would actually type", () => {
  const found = registry().search("plan");
  assert.equal(found[0]?.id, "mode.next");
});

test("an empty query lists everything that can run", () => {
  const all = registry().search("", { ran: [], busy: false });
  assert.ok(!all.some((command) => command.id === "session.cancel"));
  assert.equal(all.length, 3);
});

test("search finds nothing rather than everything when nothing matches", () => {
  assert.deepEqual(registry().search("zzzz"), []);
});
