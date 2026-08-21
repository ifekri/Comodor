"""Work that costs its own context and returns only its conclusion.

Some questions take a great deal of reading to answer and very little to state.
*Which module owns retries?* might mean opening nine files, and the answer is a
sentence. Done in the main conversation, those nine files are now permanent:
they are resent with every request for the rest of the task, and the agent that
has to keep re-reading past them is working in a window mostly full of things
it already finished with.

A delegate is the same agent with its own conversation. It gets the question,
does the reading, and hands back its answer. The reading stays with it. What
reaches the parent is what a colleague would have said — which is the whole
point, and also, by a wide margin, the cheapest thing that could have been
said.

Two shapes, and the difference matters:

**Answering** is the default and it cannot write. A question is not a reason to
hand a second agent the ability to change files, and read-only means the worst
case of a delegate that misunderstands is a wasted minute.

**Doing** is opt-in, and when the project is a git repository it happens in a
worktree of its own. The delegate gets a real checkout at the same commit,
edits it, and what comes back is a patch — inspected, then applied, or kept
aside with its path if it will not apply cleanly. The parent's working tree is
never what the delegate is experimenting in.

Delegates do not delegate. One level is a tool; a tree of them is a way to
spend an afternoon's budget in ninety seconds, and nothing in the design would
stop it.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

#: A delegate's budget, as a share of what the parent has left. It is doing one
#: piece of a task, not the task.
STEP_SHARE = 0.5
MIN_STEPS = 3
MAX_STEPS = 20
#: How long one delegate may take before it is stopped and asked what it has.
MAX_SECONDS = 420.0
#: Worktrees are named so an abandoned one is obviously ours and obviously old.
BRANCH_PREFIX = "comodor/delegate"


class Delegate(Tool):
    """Run a second agent on one question, in its own context."""

    name = "delegate"
    description = (
        "Hand one self-contained piece of work to a second agent with its own "
        "context, and get back only its answer. Use it when finding the answer "
        "means reading a lot and the answer itself is short — surveying a "
        "subsystem, locating where something is implemented, checking whether a "
        "pattern is used consistently. The reading stays with the delegate "
        "rather than filling this conversation. Give it a self-contained brief: "
        "it cannot see this conversation, only what you write here. Set "
        "write=true to let it change files, which it will do in an isolated "
        "checkout."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The complete brief. State the goal, where to "
                               "look, and exactly what to report back.",
            },
            "write": {
                "type": "boolean",
                "description": "Allow it to change files (default false). Its "
                               "changes are made in a separate checkout and "
                               "returned as a patch.",
            },
        },
        "required": ["task"],
    }

    def __init__(self, spawn: Callable[..., Any]) -> None:
        #: Builds a fresh loop. Injected because the tool layer must not know
        #: how a gateway, a brain or a skill registry is assembled.
        self._spawn = spawn

    def summary(self, args: dict[str, Any]) -> str:
        task = str(args.get("task", "")).strip().splitlines()
        head = task[0] if task else "?"
        return f"delegate: {head[:70]}"

    # -- running ---------------------------------------------------------- #

    def run(self, ctx: ToolContext, task: str = "", write: bool = False,
            **_: Any) -> ToolResult:
        brief = (task or "").strip()
        if not brief:
            return ToolResult.failure("a delegate needs a brief")

        started = time.monotonic()
        worktree: _Worktree | None = None
        in_place = ""
        try:
            if write:
                worktree, in_place = _isolate(ctx.cwd)
            root = worktree.path if worktree else ctx.cwd
            outcome = self._run_once(ctx, brief, root, write)
            if worktree is None:
                return _noting(outcome, in_place)
            return _with_changes(outcome, worktree, ctx, time.monotonic() - started)
        finally:
            if worktree is not None and worktree.keep is False:
                worktree.remove()

    def _run_once(self, ctx: ToolContext, brief: str, root: Path,
                  write: bool) -> ToolResult:
        budget = _steps(ctx)
        try:
            loop = self._spawn(cwd=root, mode="act" if write else "plan",
                               max_steps=budget, max_seconds=MAX_SECONDS,
                               cancel=ctx.cancel)
        except Exception as error:                # a misconfigured parent
            return ToolResult.failure(f"could not start a delegate: {error}")

        result = loop.run(brief)
        answer = (result.text or "").strip()

        if result.stopped == "error":
            return ToolResult.failure(f"the delegate failed: {result.error}")
        if result.stopped == "cancelled":
            return ToolResult.failure("the delegate was cancelled")
        if not answer:
            return ToolResult.failure(
                f"the delegate stopped after {result.steps} steps without an "
                f"answer ({result.stopped}). Narrow the brief and try again.")

        note = ""
        if result.stopped == "max_steps":
            note = (f"\n\n[it reached its {budget}-step limit, so this may be "
                    f"partial]")
        return ToolResult.success(
            content=answer + note,
            steps=result.steps, tool_calls=result.tool_calls,
            # What it read is what was *not* added to this conversation.
            delegate_tokens=result.usage.prompt_tokens,
        )


def _steps(ctx: ToolContext) -> int:
    share = int(ctx.config.agent.max_steps * STEP_SHARE)
    return max(MIN_STEPS, min(MAX_STEPS, share))


# --------------------------------------------------------------------------- #
# an isolated checkout
# --------------------------------------------------------------------------- #


class _Worktree:
    """A second checkout of the project at the same commit.

    Only for git projects: without one there is nothing to isolate against and
    nothing to turn the result into, so the delegate works in place and the
    parent's checkpoints are what protects the files.
    """

    def __init__(self, path: Path, branch: str, origin: Path) -> None:
        self.path = path
        self.branch = branch
        self.origin = origin
        self.keep = False

    @classmethod
    def create(cls, cwd: Path) -> "_Worktree | None":
        root = _git_root(cwd)
        if root is None:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        branch = f"{BRANCH_PREFIX}/{stamp}"
        path = root.parent / f".{root.name}-delegate-{stamp}"
        # `-b` and `--detach` cannot be used together. The branch is what gives
        # an abandoned worktree a name saying where it came from.
        done = _git(root, "worktree", "add", "-b", branch, str(path))
        if done is None:
            return None
        return cls(path, branch, root)

    def diff(self) -> str:
        _git(self.path, "add", "-A")
        return _git(self.path, "diff", "--cached") or ""

    def remove(self) -> None:
        _git(self.origin, "worktree", "remove", "--force", str(self.path))
        _git(self.origin, "branch", "-D", self.branch)
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)


def _isolate(cwd: Path) -> tuple["_Worktree | None", str]:
    """A checkout of its own, or a plain statement of why there is not one."""
    if _git_root(cwd) is None:
        return None, ("[It worked directly in this project: not a git "
                      "repository, so there was no separate checkout to make. "
                      "The usual checkpoints are what protect the files.]")
    worktree = _Worktree.create(cwd)
    if worktree is None:
        return None, ("[It worked directly in this project: a separate "
                      "checkout could not be created. The usual checkpoints "
                      "are what protect the files.]")
    return worktree, ""


def _noting(outcome: ToolResult, note: str) -> ToolResult:
    if not note or not outcome.ok:
        return outcome
    return ToolResult.success(content=f"{outcome.content}\n\n{note}",
                              isolated=False, **outcome.meta)


def _with_changes(outcome: ToolResult, worktree: _Worktree, ctx: ToolContext,
                  elapsed: float) -> ToolResult:
    """Bring a delegate's edits back, or say plainly why they stayed put."""
    if not outcome.ok:
        return outcome

    patch = worktree.diff().strip()
    if not patch:
        return ToolResult.success(
            content=outcome.content + "\n\n[it changed no files]",
            **outcome.meta)

    applied = _git(ctx.cwd, "apply", "--3way", "-", stdin=patch + "\n")
    if applied is None:
        worktree.keep = True
        return ToolResult.success(
            content=(f"{outcome.content}\n\n[Its changes do not apply cleanly "
                     f"here — something moved underneath it. The checkout is "
                     f"kept at {worktree.path} on branch {worktree.branch}; "
                     f"read the files there, or discard it.]"),
            worktree=str(worktree.path), applied=False, **outcome.meta)

    files = sorted({line.split("/", 1)[-1] for line in patch.splitlines()
                    if line.startswith("+++ b/")})
    listed = ", ".join(files[:12]) or "none"
    return ToolResult.success(
        content=(f"{outcome.content}\n\n[Its changes are applied here: "
                 f"{listed}. Review them with git diff.]"),
        applied=True, files=files, **outcome.meta)


def _git_root(cwd: Path) -> Path | None:
    found = _git(cwd, "rev-parse", "--show-toplevel")
    if not found:
        return None
    root = Path(found.strip())
    return root if root.is_dir() else None


def _git(cwd: Path, *args: str, stdin: str | None = None) -> str | None:
    """Run one git command. ``None`` means it failed, and failure is expected."""
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(cwd), input=stdin, text=True,
            capture_output=True, timeout=120.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None
