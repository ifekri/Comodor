"""Running commands, and running Python.

Shell access is the most dangerous thing the agent can do, so it is also the
most constrained: a deny-list refusal that no prompt can talk its way past, an
approval prompt for everything else, a hard timeout, and cancellation that
actually kills the process tree instead of orphaning it.

Output is streamed to the UI as it arrives — a three-minute test run should show
progress, not a frozen panel — while what goes back to the model is truncated
from the middle, keeping the command's start and its all-important tail.
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
MAX_OUTPUT_CHARS = 30_000


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Keep the head and the tail — errors almost always live at the end."""
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2:]
    dropped = len(text) - len(head) - len(tail)
    return f"{head}\n\n… [{dropped:,} characters omitted] …\n\n{tail}"


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
            "cwd": {"type": "string", "description": "Working directory, relative to the workspace."},
            "timeout": {"type": "number", "description": f"Seconds before it is killed (max {int(MAX_TIMEOUT)})."},
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

        limit = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
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
        output = _truncate("".join(chunks).strip())
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
        "Good for calculations, data inspection and quick checks."
    )
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source to execute."},
            "timeout": {"type": "number"},
        },
        "required": ["code"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        first = str(args.get("code", "")).strip().splitlines()
        return f"run python: {first[0][:100] if first else '(empty)'}"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        return str(args.get("code", ""))

    def run(self, ctx: ToolContext, code: str, timeout: float = 60.0,
            **_: Any) -> ToolResult:
        # A temp file rather than `-c` so tracebacks carry real line numbers.
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(code)
            script = handle.name

        try:
            completed = subprocess.run(
                [sys.executable, script],
                cwd=str(ctx.cwd), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=max(1.0, min(float(timeout), MAX_TIMEOUT)),
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(f"the snippet did not finish within {timeout:.0f}s")
        except OSError as exc:
            return ToolResult.failure(str(exc))
        finally:
            try:
                Path(script).unlink()
            except OSError:
                pass

        output = _truncate((completed.stdout or "") + (completed.stderr or "")).strip()
        if completed.returncode == 0:
            return ToolResult.success(content=output or "(no output)", display=output)
        return ToolResult(ok=False,
                          content=f"Python exited {completed.returncode}\n{output}",
                          display=output, meta={"exit_code": completed.returncode})
