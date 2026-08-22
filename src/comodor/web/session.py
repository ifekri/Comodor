"""One agent, driven from a browser instead of a terminal.

The interesting part is how little there is here, and that is not an accident:
the terminal interface was never the agent. Everything that happens — a token
of an answer, a tool starting, a permission being asked for, the cost changing
— is already published on an event bus, and the TUI is one subscriber that
happens to draw. A browser is a second subscriber that happens to send JSON.

So this holds the same objects `comodor` holds — a gateway, a brain, a tool
registry, one loop — and does three things the terminal does differently:

* **It keeps the events.** A browser can reload, or be opened a minute after
  the work started, and it needs the transcript rather than whatever arrives
  next. Every event is appended to a log with a sequence number, and a client
  says where it got to.
* **It runs one turn at a time.** A terminal enforces that by having one
  keyboard. Nothing stops two tabs from both hitting send, so a lock does.
* **It answers permission prompts by id.** The worker thread blocks on a
  `Request` exactly as it does for the TUI; the browser posts the choice.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from ..agent import AgentLoop, Conversation
from ..agent.spawn import spawner
from ..config import Config
from ..events import Event, EventBus, Kind, Request
from ..learning import LearningEngine
from ..mcp import MCPManager
from ..providers.gateway import Gateway
from ..safety import CheckpointStore, PermissionEngine, Redactor
from ..skills import load_for as load_skills
from ..tools import ToolRegistry

#: How many events are kept for a reloading browser. A long session produces
#: tens of thousands; what a reader needs is the recent past, and the session
#: transcript on disk is the record.
HISTORY = 4_000


class Session:
    """The agent, plus what a disconnected browser needs to catch up on."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.bus = EventBus()
        self.gateway = Gateway(config)
        self.checkpoints = CheckpointStore(config.paths.checkpoints)
        self.memory = LearningEngine(
            config, self.bus, self.gateway, checkpoints=self.checkpoints,
            redact=Redactor([entry.api_key for entry in config.providers.values()
                             if entry.api_key]),
        )
        self.permissions = PermissionEngine(config, self.bus)
        self.permissions.on_denied = self.memory.on_denied
        self.skills = load_skills(config)
        self.mcp = MCPManager(config.mcp.servers) if config.mcp.enabled else None
        self.conversation = Conversation()
        self.agent = AgentLoop(
            config, self.gateway,
            ToolRegistry(skills=self.skills, mcp=self.mcp, config=config,
                         spawn=spawner(config, self.gateway, self.bus,
                                       skills=self.skills, mcp=self.mcp)),
            self.bus, self.permissions, self.conversation, self.memory,
            skills=self.skills,
        )

        self._log: list[dict[str, Any]] = []
        self._sequence = 0
        self._lock = threading.Lock()
        self._arrived = threading.Condition(self._lock)
        self._pending: dict[str, Request] = {}
        self._turn = threading.Lock()
        self.busy = False

        self.bus.subscribe(self._record)

    # -- taking events off the bus ----------------------------------------- #

    def _record(self, event: Event) -> None:
        """Called on whatever thread emitted. Cheap, and never raises."""
        try:
            frame = self._as_json(event)
        except Exception:
            return
        if frame is None:
            return
        with self._arrived:
            self._sequence += 1
            frame["seq"] = self._sequence
            self._log.append(frame)
            if len(self._log) > HISTORY:
                del self._log[:len(self._log) - HISTORY]
            self._arrived.notify_all()

    def _as_json(self, event: Event) -> dict[str, Any] | None:
        kind = event.kind
        payload = {key: value for key, value in event.payload.items()
                   if key != "request"}

        if kind is Kind.REQUEST:
            request: Request | None = event.payload.get("request")
            if request is None:
                return None
            # Held so the answer can find it. The worker thread is blocked on
            # this object right now.
            self._pending[request.id] = request
            payload = {"id": request.id, "prompt": request.prompt,
                       "options": list(request.options), "detail": request.detail,
                       # Not "kind": a Request has one of its own, and spread
                       # into the frame it silently overwrote the event's,
                       # turning every permission prompt into an event of kind
                       # "permission" that the page was not listening for.
                       "about": request.kind}

        return {**_plain(payload), "kind": kind.value, "at": time.time()}

    # -- what a browser asks for ------------------------------------------- #

    def since(self, cursor: int) -> list[dict[str, Any]]:
        with self._lock:
            return [frame for frame in self._log if frame["seq"] > cursor]

    def wait_for(self, cursor: int, timeout: float = 25.0) -> list[dict[str, Any]]:
        """Events after ``cursor``, waiting for one if there are none.

        The wait has a ceiling so the response ends by itself: a stream held
        open forever is a stream a proxy eventually kills, and a client that
        cannot tell a dead connection from a quiet one reconnects too late.
        """
        deadline = time.monotonic() + timeout
        with self._arrived:
            while True:
                ready = [frame for frame in self._log if frame["seq"] > cursor]
                if ready:
                    return ready
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._arrived.wait(remaining)

    def state(self) -> dict[str, Any]:
        usage = self.conversation.usage
        return {
            "provider": self.config.provider,
            "model": self.config.active_model(),
            "mode": self.config.agent.mode,
            "loop": self.config.agent.loop,
            "busy": self.busy,
            "cursor": self._sequence,
            "usage": {
                "prompt": usage.prompt_tokens,
                "output": usage.output_tokens,
                "cached": usage.cached_tokens,
                "cost": round(usage.cost_usd, 4),
                "hit_rate": round(usage.cache_hit_rate, 3),
            },
            "context": {
                "limit": self.config.agent.context_limit,
            },
            "project": str(self.config.paths.project),
        }

    # -- what a browser does ------------------------------------------------ #

    def send(self, text: str) -> bool:
        """Start a turn. False if one is already running."""
        if not text.strip():
            return False
        if not self._turn.acquire(blocking=False):
            return False

        def work() -> None:
            self.busy = True
            self.bus.emit(Kind.STATUS, busy=True)
            try:
                self.agent.run(text)
            except Exception as error:                # never lose the worker
                self.bus.emit(Kind.ERROR, text=f"{type(error).__name__}: {error}")
            finally:
                self.busy = False
                self.bus.emit(Kind.STATUS, busy=False)
                self._turn.release()

        threading.Thread(target=work, name="comodor-web-turn", daemon=True).start()
        return True

    def answer(self, request_id: str, choice: str) -> tuple[bool, str]:
        """Answer a waiting prompt. Returns whether it took, and why not.

        The choice has to be one the request offered. Accepting anything else
        and reporting success is the worst available behaviour: the permission
        engine does not recognise the word, treats the turn as refused, and the
        caller is told it worked.
        """
        request = self._pending.get(request_id)
        if request is None:
            return False, "nothing is waiting on that"
        if request.answered:
            return False, "that was already answered"
        if request.options and choice not in request.options:
            return False, (f"{choice!r} is not one of the choices: "
                           f"{', '.join(request.options)}")

        self._pending.pop(request_id, None)
        request.answer(choice)
        return True, ""

    def interrupt(self) -> None:
        self.agent.interrupt()

    def set_mode(self, mode: str) -> bool:
        if mode not in ("act", "plan", "chat"):
            return False
        self.config.agent.mode = mode
        self.bus.emit(Kind.STATUS, mode=mode)
        return True

    def close(self) -> None:
        # Deny anything still waiting, or a worker thread blocks until timeout.
        for request in list(self._pending.values()):
            if not request.answered:
                request.answer(request.options[-1] if request.options else "no")
        self._pending.clear()
        try:
            self.agent.tools.close()
        except Exception:
            pass
        try:
            self.memory.close()
        except Exception:
            pass
        if self.mcp is not None:
            try:
                self.mcp.close()
            except Exception:
                pass


def _plain(value: Any) -> Any:
    """Whatever will survive `json.dumps`, and nothing that will not."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "as_dict"):
        try:
            return _plain(value.as_dict())
        except Exception:
            pass
    return str(value)
