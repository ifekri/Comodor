/**
 * A real core process, started and stopped the way the client starts one.
 *
 * The renderer suite uses a loopback so it can be exact about the screen.
 * This is the other half: a Python core in its own process, to prove the two
 * things a loopback cannot — that the client can actually talk to one, and
 * that it does not leave one running.
 *
 * An orphaned core is the failure people notice a day later, holding a
 * workspace and a provider connection with nobody attached, so it is worth a
 * test that spawns and kills for real.
 */

import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { CoreClient } from "@comodor/client";
import { spawnCore } from "@comodor/client/spawn";

const ROOT = join(import.meta.dir, "..", "..", "..", "..");

/** A home whose only provider is the scripted one, so nothing reaches out. */
function offlineHome(): string {
  const home = mkdtempSync(join(tmpdir(), "comodor-tui-"));
  mkdirSync(join(home, "home"), { recursive: true });
  writeFileSync(join(home, "home", "config.json"), JSON.stringify({
    provider: "fake",
    model: "fake-1",
    providers: { fake: { name: "fake", kind: "fake", base_url: "offline",
                         api_key: "test", model: "fake-1", label: "Fake" } },
    agent: { mode: "act", loop: false },
    learning: { enabled: false }, mcp: { enabled: false },
    cron: { enabled: false }, skills: { enabled: false },
  }));
  return home;
}

const made: string[] = [];
afterEach(() => {
  for (const home of made.splice(0)) {
    try { rmSync(home, { recursive: true, force: true }); } catch { /* gone */ }
  }
});

const notes: string[] = [];

function start(home: string) {
  made.push(home);
  return spawnCore({
    // The interpreter is named rather than assumed: `python` on Windows can
    // resolve to the Store alias, and CI runs a specific one.
    command: process.env["COMODOR_PYTHON"] ?? "python",
    args: ["-m", "comodor"],
    onDiagnostic: (text) => notes.push(text),
    cwd: home,
    env: {
      ...process.env,
      COMODOR_HOME: join(home, "home"),
      PYTHONPATH: join(ROOT, "src"),
      PYTHONIOENCODING: "utf-8",
    },
  });
}

test("the client can drive a real core over a real pipe", async () => {
  const transport = start(offlineHome());
  const client = new CoreClient(transport, { timeoutMs: 30_000 });

  const shook = await client.start().catch((problem: Error) => {
    // Whatever the core said on its way out, so a failure here names a cause
    // rather than only reporting that the pipe closed.
    throw new Error([problem.message, "stderr:", ...notes].join("\n"));
  });
  expect(shook.core.name).toBe("comodor-core");
  expect(shook.capabilities).toContain("streaming");

  const opened = await client.call("session.create");
  const session = opened["session"] as { id: string; mode: string };
  expect(session.mode).toBe("act");

  const switched = await client.call("session.set_mode",
    { session_id: session.id, mode: "plan" });
  expect((switched["session"] as { mode: string }).mode).toBe("plan");

  await client.close();
  expect(transport.process.exitCode !== null
         || transport.process.signalCode !== null).toBe(true);
}, 60_000);

test("closing the client leaves no core behind", async () => {
  const transport = start(offlineHome());
  const client = new CoreClient(transport, { timeoutMs: 30_000 });
  await client.start();
  const pid = transport.pid;
  expect(pid).toBeGreaterThan(0);

  await client.close();

  // `kill(pid, 0)` asks whether the process exists without signalling it.
  // A core still running here is one that would have outlived its terminal.
  let alive = true;
  for (let attempt = 0; attempt < 50 && alive; attempt += 1) {
    try {
      process.kill(pid as number, 0);
      await Bun.sleep(100);
    } catch {
      alive = false;
    }
  }
  expect(alive).toBe(false);
}, 60_000);

test("a core that cannot be started is a rejection, not a dead process",
     async () => {
  const transport = spawnCore({ command: "comodor-does-not-exist-4f21a9" });
  const client = new CoreClient(transport, { timeoutMs: 5_000 });

  await expect(client.start()).rejects.toThrow();
  await transport.close();
}, 30_000);
