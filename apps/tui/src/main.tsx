#!/usr/bin/env bun
/**
 * Start a core, attach to it, draw.
 *
 * The order matters and is the whole of this file. The core is spawned and
 * the handshake completed *before* the renderer takes the terminal, so a core
 * that cannot start prints a plain error to a normal terminal instead of a
 * traceback into a half-initialised alternate screen.
 *
 * **Why Bun.** OpenTUI's renderer reaches native code through `bun:ffi`.
 * Node has no equivalent — `node:ffi` is not a module in any released
 * version, and OpenTUI's own loader falls back to a backend that throws —
 * so this one application needs Bun. Every other package in this workspace is
 * plain TypeScript and runs anywhere, which is deliberate: the runtime
 * requirement belongs to the renderer, not to the protocol.
 */

import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";

import { CoreClient } from "@comodor/client";
import { spawnCore } from "@comodor/client/spawn";

import { App } from "./App.tsx";

const diagnostics: string[] = [];

async function main(): Promise<number> {
  // `comodor tui-v2` starts this with COMODOR_BIN pointing at the very
  // interpreter it is running under, so the core is the one that launched
  // the client rather than whatever `comodor` happens to be on the path.
  const extra = (process.env["COMODOR_ARGS"] ?? "").trim();
  const transport = spawnCore({
    command: process.env["COMODOR_BIN"] ?? "comodor",
    args: extra ? extra.split(/\s+/) : [],
    cwd: process.cwd(),
    onDiagnostic: (text) => diagnostics.push(text),
  });

  const client = new CoreClient(transport, {
    client: { name: "comodor-tui", version: "0.0.0" },
    capabilities: ["questions", "permissions"],
    onDiagnostic: (text) => diagnostics.push(text),
  });

  try {
    await client.start();
  } catch (problem) {
    // Before the renderer, so this lands on an ordinary terminal.
    process.stderr.write(
      `comodor: the core did not start — ${(problem as Error).message}\n`);
    for (const line of diagnostics.slice(-5)) {
      process.stderr.write(`  ${line}\n`);
    }
    await transport.close();
    return 1;
  }

  const renderer = await createCliRenderer();
  const root = createRoot(renderer);

  let leaving = false;
  const leave = async (): Promise<void> => {
    if (leaving) return;
    leaving = true;
    root.unmount();
    renderer.destroy();
    // The core goes with us. A terminal that closes and leaves a Python
    // process holding the workspace is the failure noticed a day later.
    await client.close();
  };

  root.render(<App client={client} onQuit={() => { void leave(); }} />);

  await new Promise<void>((resolve) => {
    const finish = (): void => { void leave().then(resolve); };
    process.once("SIGINT", finish);
    process.once("SIGTERM", finish);
    client.on(() => {});
  });
  return 0;
}

main().then(
  (code) => process.exit(code),
  (problem: unknown) => {
    process.stderr.write(`comodor: ${(problem as Error).message}\n`);
    process.exit(1);
  },
);
