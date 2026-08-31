"""What a tool is.

A tool declares a JSON schema (so the model can call it), a risk tier (so the
permission engine can gate it), and a one-line summary (so the approval prompt
and the transcript can describe it in human terms). Everything a tool needs at
runtime arrives in a :class:`ToolContext` rather than through globals, which is
what makes the whole set testable without a terminal.

Results carry two payloads: ``content`` goes back to the model and should be
compact and factual, while ``display`` is what the UI renders and may be much
richer — a coloured diff, a table, syntax-highlighted source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..events import Cancellation, EventBus
from ..providers.base import ToolSpec
from ..safety import CheckpointStore, PermissionEngine, Redactor, Risk

# --------------------------------------------------------------------------- #
# runtime context
# --------------------------------------------------------------------------- #


@dataclass
class TodoItem:
    text: str
    state: str = "pending"               # pending | active | done | blocked

    @property
    def icon(self) -> str:
        return {"pending": "○", "active": "◐", "done": "●", "blocked": "✗"}.get(self.state, "○")


@dataclass
class ToolContext:
    """Everything a tool may touch."""

    config: Config
    permissions: PermissionEngine
    checkpoints: CheckpointStore
    bus: EventBus
    redact: Redactor
    cancel: Cancellation
    cwd: Path
    todos: list[TodoItem] = field(default_factory=list)
    emit_output: Callable[[str], None] | None = None   # incremental tool output
    #: What the user said not to do, in their own words, for this turn.
    #:
    #: Shown again on the result of a write, because that is the last thing the
    #: model reads before deciding what to do next — and by then the request is
    #: thousands of tokens up the context behind everything it has read since.
    rules: list[str] = field(default_factory=list)
    #: How many times they have been repeated this turn, and whether the
    #: moment for repeating them has passed.
    rules_shown: int = 0
    #: Set as soon as the turn writes anything. After that the rule has either
    #: been kept or broken, and saying it again is noise.
    has_written: bool = False

    #: Every file this session has actually read, by resolved path.
    #:
    #: Kept so a write can tell the difference between replacing a file whose
    #: contents are known and replacing one sight unseen. The second is how the
    #: rest of a file gets silently thrown away, and the benchmark caught it:
    #: one task was failed for overwriting the sample it was being measured
    #: against, in a run that was otherwise correct.
    seen: set[str] = field(default_factory=set)

    def note_read(self, path: Path) -> None:
        self.seen.add(self._key(path))

    def was_read(self, path: Path) -> bool:
        return self._key(path) in self.seen

    @staticmethod
    def _key(path: Path) -> str:
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(path)

    def resolve(self, path: str | Path) -> Path:
        """Interpret a model-supplied path relative to the workspace."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.cwd / candidate
        return candidate

    def relative(self, path: Path) -> str:
        """Display form: short and relative when the file is in the project."""
        try:
            return str(Path(path).resolve().relative_to(self.cwd.resolve()))
        except (ValueError, OSError):
            return str(path)

    def progress(self, text: str) -> None:
        if self.emit_output is not None:
            self.emit_output(text)


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #


@dataclass
class ToolResult:
    ok: bool = True
    content: str = ""                     # what the model sees
    display: str = ""                     # what the user sees, if different
    meta: dict[str, Any] = field(default_factory=dict)
    elapsed: float = 0.0

    @classmethod
    def success(cls, content: str, display: str = "", **meta: Any) -> "ToolResult":
        return cls(ok=True, content=content, display=display, meta=meta)

    @classmethod
    def failure(cls, message: str, **meta: Any) -> "ToolResult":
        # Errors are returned, not raised: the model can read them and correct
        # course, which is far more useful than aborting the turn.
        return cls(ok=False, content=f"Error: {message}", display="", meta=meta)

    @property
    def rendered(self) -> str:
        return self.display or self.content


# --------------------------------------------------------------------------- #
# the tool
# --------------------------------------------------------------------------- #


class Tool:
    """Base class. Subclasses set the class attributes and implement ``run``."""

    name: str = ""
    description: str = ""
    risk: Risk = Risk.SAFE
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    # Tools the model may call while in Plan mode are exactly the SAFE ones.

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        parameters=self.parameters)

    def summary(self, args: dict[str, Any]) -> str:
        """One line describing this specific call."""
        if not args:
            return self.name
        preview = ", ".join(f"{k}={_short(v)}" for k, v in list(args.items())[:3])
        return f"{self.name}({preview})"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        """Extra context for the approval dialog — a diff, a command, a URL."""
        return ""

    def permission_key(self, args: dict[str, Any]) -> str:
        """What an "always allow" grant should cover. Defaults to the tool."""
        return self.name

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        raise NotImplementedError

    # -- invocation ------------------------------------------------------- #

    def invoke(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        """Gate, run, and time one call."""
        started = time.monotonic()
        decision = ctx.permissions.check(
            tool=self.name,
            risk=self.risk,
            summary=self.summary(args),
            detail=self.detail(ctx, args),
            key=self.permission_key(args),
        )
        if not decision:
            result = ToolResult.failure(decision.reason or "not permitted",
                                        denied=True)
            result.elapsed = time.monotonic() - started
            return result

        try:
            result = self.run(ctx, **args)
        except TypeError as exc:
            # Almost always a bad argument set from the model — tell it exactly
            # what went wrong so the next attempt is right.
            result = ToolResult.failure(f"invalid arguments for {self.name}: {exc}")
        except Exception as exc:
            result = ToolResult.failure(f"{type(exc).__name__}: {exc}")

        result.content = ctx.redact(result.content)
        result.display = ctx.redact(result.display)
        result.elapsed = time.monotonic() - started
        return result


def _short(value: Any, limit: int = 40) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
