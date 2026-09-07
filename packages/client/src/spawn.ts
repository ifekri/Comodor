/**
 * A core in a child process, over its own stdin and stdout.
 *
 * The only file in this package that knows what an operating system is, and
 * deliberately the smallest. Everything interesting — correlation, the
 * handshake, events — is in `CoreClient` and is tested without any of this.
 *
 * Lifecycle, in the order it matters:
 *
 * **stdout is protocol, stderr is not.** They are read by different code and
 * never mixed. A core that warns about a missing MCP server must not look
 * like a core that broke.
 *
 * **The child does not outlive the parent.** A terminal client that exits and
 * leaves a Python process holding the workspace is the failure people notice
 * a day later, so the exit handlers are registered at spawn and `stop` is
 * safe to call more than once.
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

import type { Transport } from "./index.ts";

export interface SpawnOptions {
  /** The executable. `comodor` on the path by default. */
  command?: string;
  /** Arguments before the transport flag. */
  args?: string[];
  /** Where the core should treat as the workspace. */
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  /** Lines the core wrote to stderr. */
  onDiagnostic?: (text: string) => void;
  /** The child ended. `code` is null when a signal killed it. */
  onExit?: (code: number | null, signal: NodeJS.Signals | null) => void;
}

export interface SpawnedCore extends Transport {
  readonly process: ChildProcessWithoutNullStreams;
  readonly pid: number | undefined;
}

export function spawnCore(options: SpawnOptions = {}): SpawnedCore {
  const command = options.command ?? "comodor";
  const args = [...(options.args ?? []), "core", "--stdio"];
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: options.env ?? process.env,
    stdio: ["pipe", "pipe", "pipe"],
    // No shell: the command and its arguments are ours, and a shell would
    // add quoting rules to a path that already works.
    shell: false,
    windowsHide: true,
  }) as ChildProcessWithoutNullStreams;

  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");

  // Diagnostics, line by line, never parsed.
  const diagnostics = createInterface({ input: child.stderr });
  diagnostics.on("line", (text) => options.onDiagnostic?.(text));

  let stopped = false;
  const stop = (): void => {
    if (stopped) return;
    stopped = true;
    try {
      child.stdin.end();
    } catch { /* already gone */ }
    // Closing stdin is how a core is asked to stop; the kill is the promise
    // that it does. Unreferenced so it cannot hold the process open itself.
    const grace = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill();
    }, 2_000);
    grace.unref?.();
  };

  child.on("exit", (code, signal) => {
    stopped = true;
    diagnostics.close();
    options.onExit?.(code, signal);
    process.off("exit", stop);
  });
  // Registered at spawn rather than at close: the case this exists for is the
  // parent ending without getting the chance to tidy up.
  process.once("exit", stop);

  return {
    process: child,
    get pid() { return child.pid; },
    lines(): AsyncIterable<string> {
      return createInterface({ input: child.stdout, crlfDelay: Infinity });
    },
    write(line: string): void {
      child.stdin.write(line + "\n");
    },
    async close(): Promise<void> {
      stop();
      if (child.exitCode !== null || child.signalCode !== null) return;
      await new Promise<void>((resolve) => {
        const done = (): void => resolve();
        child.once("exit", done);
        const giveUp = setTimeout(() => {
          child.kill();
          resolve();
        }, 5_000);
        giveUp.unref?.();
      });
    },
  };
}
