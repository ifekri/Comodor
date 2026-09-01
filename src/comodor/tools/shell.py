"""Running commands, and running Python.

Shell access is the most dangerous thing the agent can do, so it is also the
most constrained: a deny-list refusal that no prompt can talk its way past, an
approval prompt for everything else, a hard timeout, and cancellation that
actually kills the process tree instead of orphaning it.

Output is streamed to the UI as it arrives — a three-minute test run should show
progress, not a frozen panel. How much of it reaches the model is not decided
here: an oversized result is bounded once, centrally, by writing the whole of
it to a file and returning the ends with a pointer. See `overflow.py`. What
this tool must not do is cut it first, which would leave that file holding an
already-cut copy and the middle of a failing run unrecoverable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

DEFAULT_TIMEOUT = 120.0
MAX_TIMEOUT = 900.0
#: A ceiling on what is held in memory from one command, not on what the model
#: is shown. A process printing without end must not exhaust the machine; a
#: process printing a great deal must still be saved in full.
MAX_HELD_CHARS = 4_000_000


def _backend(ctx: ToolContext) -> Any:
    """The non-host shell backend this session configured, or None.

    Built per call rather than cached: `settings changed while the bot runs`
    must reach the shell the way it reaches every other setting, and a
    backend holds no state worth keeping.
    """
    settings = getattr(ctx.config, "shell", None)
    if settings is None:
        return None
    name = (getattr(settings, "backend", "host") or "host").lower()
    if name in ("", "host"):
        return None
    from ..safety.backends import build

    return build(settings, ctx.config.paths.project)


def _cap(text: str, limit: int = MAX_HELD_CHARS) -> str:
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return text[:limit] + f"\n\n… [stopped after {limit:,} characters; " \
                          f"{dropped:,} more were produced] …"


def _kill_tree(process: subprocess.Popen) -> None:
    """Terminate the process and its children.

    A bare ``kill()`` leaves grandchildren running — a test runner's workers, a
    dev server — which then hold ports and confuse the next command.
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(process.pid), 9)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


class RunShell(Tool):
    name = "run_shell"
    description = (
        "Run a shell command in the workspace and return its output. "
        "Use for builds, tests, git, and package managers. "
        "Prefer the dedicated file tools for reading and editing files."
    )
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command line to run."},
            "cwd": {"type": "string",
                    "description": "Working directory, relative to the workspace."},
            "timeout": {"type": "number",
                        "description": f"Seconds before it is killed (max {int(MAX_TIMEOUT)})."},
            "description": {"type": "string", "description": "One line on what this command does."},
        },
        "required": ["command"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        command = str(args.get("command", "")).strip().replace("\n", " ")
        return f"run: {command[:120]}"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        where = args.get("cwd") or "."
        return f"$ {args.get('command', '')}\n\nin {ctx.relative(ctx.resolve(where))}"

    def permission_key(self, args: dict[str, Any]) -> str:
        # An "always allow" for shell is scoped to the first token, so approving
        # `git status` does not silently approve `rm`.
        command = str(args.get("command", "")).strip()
        first = command.split()[0] if command.split() else "shell"
        return f"{self.name}:{first}"

    def run(self, ctx: ToolContext, command: str, cwd: str = ".",
            timeout: float = DEFAULT_TIMEOUT, description: str = "",
            **_: Any) -> ToolResult:
        blocked = ctx.permissions.denied_command(command)
        if blocked:
            return ToolResult.failure(
                f"refused: the command matches the blocked pattern {blocked!r}")

        workdir = ctx.resolve(cwd)
        if not workdir.is_dir():
            return ToolResult.failure(f"{ctx.relative(workdir)} is not a directory")

        # A non-host backend carries the command elsewhere. The deny list ran
        # above — depth of defence is not negotiable — and the timeout is
        # capped by the same ceiling, because a remote or containerised
        # command has no better claim to run forever than a local one.
        backend = _backend(ctx)
        if backend is not None:
            return self._run_on_backend(ctx, backend, command, workdir, timeout)

        limit = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))

        limit = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
        # The host loop, extracted once so the backends module could carry
        # the same shape: poll the process, stream the output, kill the tree.
        popen_kwargs: dict[str, Any] = {
            "cwd": str(workdir),
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True   # so we can kill the group

        started = time.monotonic()
        try:
            process = subprocess.Popen(command, **popen_kwargs)
        except OSError as exc:
            return ToolResult.failure(f"could not start the command: {exc}")

        chunks: list[str] = []
        collector_done = threading.Event()

        def collect() -> None:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    chunks.append(line)
                    ctx.progress(line.rstrip("\n"))
            except Exception:
                pass
            finally:
                collector_done.set()

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()

        timed_out = False
        cancelled = False
        while True:
            if process.poll() is not None:
                break
            if ctx.cancel.cancelled:
                cancelled = True
                _kill_tree(process)
                break
            if time.monotonic() - started > limit:
                timed_out = True
                _kill_tree(process)
                break
            time.sleep(0.05)

        collector_done.wait(timeout=2.0)
        reader.join(timeout=1.0)
        code = process.poll()
        output = _cap("".join(chunks).strip())
        elapsed = time.monotonic() - started

        if cancelled:
            return ToolResult.failure(
                f"cancelled after {elapsed:.1f}s\n{output}", exit_code=code)
        if timed_out:
            return ToolResult.failure(
                f"timed out after {limit:.0f}s and was killed.\n{output}", exit_code=code)

        header = f"exit {code} in {elapsed:.1f}s"
        body = output or "(no output)"
        if code == 0:
            return ToolResult.success(content=f"{header}\n{body}", display=body,
                                      exit_code=code, elapsed=elapsed)
        return ToolResult(ok=False, content=f"Command failed — {header}\n{body}",
                          display=body, meta={"exit_code": code})


class RunPython(Tool):
    name = "run_python"
    description = (
        "Run a short Python snippet in a subprocess and return its output. "
        "Good for calculations, data inspection and quick checks. With "
        "tools=true the snippet can also call this session's read-only tools "
        "as comodor.tools.<name>(**args) — for reading many files and "
        "returning only the conclusion, without every result landing in the "
        "conversation. Note: with tools=true the protocol owns stdout, so "
        "print to stderr."
    )
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source to execute."},
            "timeout": {"type": "number"},
            "tools": {"type": "boolean",
                      "description": "Expose the session's read-only tools to "
                                     "the script as comodor.tools (default "
                                     "false)."},
        },
        "required": ["code"],
    }

    def __init__(self, registry: Any = None) -> None:
        #: The registry this session dispatches through, when the tool has
        #: been wired to one. The bridge reaches the same permission engine
        #: and the same overflow rule as a normal tool call, because it goes
        #: through the same objects. Without it, tools=true is refused.
        self._registry = registry

    def use_registry(self, registry: Any) -> None:
        """Wire the bridge to a registry. Called by the registry itself."""
        self._registry = registry

    def summary(self, args: dict[str, Any]) -> str:
        first = str(args.get("code", "")).strip().splitlines()
        head = first[0][:100] if first else "(empty)"
        return f"run python: {head}" + (" (tools)" if args.get("tools") else "")

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        return str(args.get("code", ""))

    def run(self, ctx: ToolContext, code: str, timeout: float = 60.0,
            tools: bool = False, **_: Any) -> ToolResult:
        bridge: Any = None
        setup = ""
        if tools:
            if self._registry is None:
                return ToolResult.failure(
                    "tools=true needs a tool registry, and this run_python was "
                    "built without one (inside a delegate or a scheduled run, "
                    "for instance). Run the script without tools.")
            from ..agent.tool_bridge import CHILD_SETUP, Bridge

            bridge = Bridge(self._registry, ctx)
            setup = CHILD_SETUP

        # A temp file rather than `-c` so tracebacks carry real line numbers.
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(setup + code)
            script = handle.name

        # Without the bridge, stdin is closed and the plain `run` is one
        # blocking call, as it always was. With it, requests and replies move
        # over the child's stdin and stdout in a pump thread: the subprocess
        # runs in the tool's thread either way, and a script that never talks
        # to the bridge is unaffected by any of this.
        try:
            if bridge is None:
                completed = subprocess.run(
                    [sys.executable, script],
                    cwd=str(ctx.cwd), capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=max(1.0, min(float(timeout), MAX_TIMEOUT)),
                )
                return self._finish(completed)
            with subprocess.Popen(
                [sys.executable, script],
                cwd=str(ctx.cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace",
            ) as process:
                return self._pump(process, bridge, timeout)
        except subprocess.TimeoutExpired:
            return ToolResult.failure(f"the snippet did not finish within {timeout:.0f}s")
        except OSError as exc:
            return ToolResult.failure(str(exc))
        finally:
            try:
                Path(script).unlink()
            except OSError:
                pass

    def _run_on_backend(self, ctx: ToolContext, backend: Any, command: str,
                        workdir: Path, timeout: float) -> ToolResult:
        """Hand the command to a container or a remote box."""
        limit = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
        result = backend.run(
            command, workdir, limit, ctx.cancel,
            on_output=ctx.progress)
        if result.cancelled:
            return ToolResult.failure(
                f"cancelled after {result.elapsed:.1f}s\n{result.output}")
        if result.timed_out:
            return ToolResult.failure(
                f"timed out after {limit:.0f}s and was killed.\n{result.output}",
                exit_code=result.exit_code)
        header = (f"exit {result.exit_code} in {result.elapsed:.1f}s "
                  f"on {backend.description()}")
        body = (result.output or "").strip() or "(no output)"
        if result.exit_code == 0:
            return ToolResult.success(content=f"{header}\n{body}", display=body,
                                      exit_code=0, elapsed=result.elapsed)
        return ToolResult(
            ok=False, content=f"Command failed — {header}\n{body}",
            display=body, meta={"exit_code": result.exit_code})

    @staticmethod
    def _finish(completed: subprocess.CompletedProcess) -> ToolResult:
        output = _cap((completed.stdout or "") + (completed.stderr or "")).strip()
        if completed.returncode == 0:
            return ToolResult.success(content=output or "(no output)", display=output)
        return ToolResult(ok=False,
                          content=f"Python exited {completed.returncode}\n{output}",
                          display=output, meta={"exit_code": completed.returncode})

    def _pump(self, process: subprocess.Popen, bridge: Any,
              timeout: float) -> ToolResult:
        """Run the script and answer its bridge requests until it exits.

        stdout is the protocol; stderr is the script's own voice and is
        buffered here in a reader thread, the same job the plain run's
        capture does.
        """
        stderr_chunks: list[str] = []
        reader = threading.Thread(
            target=lambda: stderr_chunks.append(process.stderr.read() or ""),
            daemon=True)
        reader.start()
        #: The script's own wall clock. Checked between bridge round trips;
        #: a script wedged inside one call is killed by the bridge's own
        #: registry timeout or, failing that, the finally-kill below.
        deadline = time.monotonic() + max(1.0, min(float(timeout), MAX_TIMEOUT))
        try:
            assert process.stdin is not None and process.stdout is not None
            while True:
                line = process.stdout.readline()
                if not line:                       # the child closed stdout
                    break
                if time.monotonic() > deadline:
                    process.kill()
                    return ToolResult.failure(
                        f"the snippet did not finish within {timeout:.0f}s")
                reply = bridge.handle_line(line)
                try:
                    process.stdin.write(reply + "\n")
                    process.stdin.flush()
                except (OSError, ValueError):      # the child died mid-call
                    break
            try:
                process.stdin.close()
            except OSError:
                pass
            code = process.wait(timeout=max(1.0, min(float(timeout), MAX_TIMEOUT)))
            reader.join(timeout=2.0)
            output = _cap((stderr_chunks[0] or "")).strip()
            if code == 0:
                return ToolResult.success(content=output or "(no output)",
                                          display=output,
                                          bridge_calls=bridge.calls)
            return ToolResult(ok=False,
                              content=f"Python exited {code}\n{output}",
                              display=output, meta={"exit_code": code})
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
