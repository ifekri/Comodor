"""Sessions behind the endpoint: one per client, or one per request.

An OpenAI client is stateless, and most of the time that is exactly right —
each request carries its history, and the server needs nothing between them.
But Comodor is an agent, and an agent's value across requests is its memory:
the recall of lessons, the learned rules, the running conversation whose
earlier tool results a later question builds on.

So the mapping is explicit, which is the only kind of state worth having:

* **No header** — one session per request, made and thrown away. Nothing is
  remembered between requests, which is what the protocol promises.
* **``X-Comodor-Session: <id>``** — one session per id, kept, with the
  agent's own conversation history. The id comes back in the response under
  ``comodor.session``; a client that wants continuity echoes it.

Sessions no client has spoken to for a while are closed, not kept: each one
holds a live model gateway, a tool registry and the brain, and an endpoint
that quietly accumulated those would leak a small program's worth of memory
per abandoned tab.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from ..config import Config

#: A session unused for this long is closed and dropped.
IDLE_TTL = 1800.0
#: Swept this often by whichever request happens to arrive.
SWEEP_EVERY = 300.0


class Talk:
    """One client's session, and how a request is answered on it."""

    def __init__(self, config: Config, identifier: str) -> None:
        from ..web.session import Session

        self.id = identifier
        self.session = Session(config)
        self.lock = threading.Lock()
        self.last_used = time.monotonic()

    @property
    def busy(self) -> bool:
        return self.session.busy

    def run(self, text: str, prior: list[dict[str, str]] | None = None,
            mode: str = "", patience: float = 600.0) -> dict[str, Any]:
        """One whole turn, waited for. Serialized per session.

        ``prior`` is the history the client sent and we do not keep. It is
        quoted into the task as prose — context the client insisted on —
        rather than written into the agent's conversation, because the
        stored history should read as what actually happened here, not as a
        re-enactment of somebody else's transcript.

        ``mode`` is honoured only when the client names a known one; an
        unknown word leaves the configured mode alone rather than guessing.
        """
        task = _with_prior(text, prior or [])

        with self.lock:
            self.last_used = time.monotonic()
            if self.session.busy:
                # Another request is mid-turn on this session. Refusing is
                # the honest answer: splicing a second task into a running
                # turn is what the busy-input modes exist for on the
                # channels, and none of them is what an OpenAI client asked
                # for. It retries; nothing is lost.
                return {"text": "", "steps": 0, "stopped": "busy", "error":
                        "a turn is already running on this session"}
            if mode:
                self.session.set_mode(mode)
            if not self.session.send(task):
                return {"text": "", "steps": 0, "stopped": "busy", "error":
                        "the turn could not be started"}
            return self._wait(patience)

    def _wait(self, patience: float) -> dict[str, Any]:
        """Drain the event log until the turn ends, then read the answer."""
        cursor = self.session.cursor
        deadline = time.monotonic() + patience
        text_parts: list[str] = []
        steps = 0

        while time.monotonic() < deadline:
            events = self.session.wait_for(cursor, timeout=8.0)
            if events:
                cursor = self.session.cursor
            for event in events:
                kind = event.get("kind")
                if kind == "assistant_delta":
                    text_parts.append(str(event.get("text") or ""))
                elif kind == "assistant_end" and event.get("text"):
                    # The end event is the whole message; the deltas that
                    # arrived before it are the same words in pieces.
                    text_parts = [str(event.get("text"))]
                elif kind == "step":
                    steps += 1
                elif kind == "turn_end":
                    return self._outcome(text_parts, steps,
                                         str(event.get("stopped") or "done"))
                elif kind == "cancelled":
                    return self._outcome(text_parts, steps, "cancelled")

        return {"text": "".join(text_parts), "steps": steps,
                "stopped": "timeout", "error": "the turn outlived its patience"}

    def _outcome(self, text_parts: list[str], steps: int,
                 stopped: str) -> dict[str, Any]:
        """The answer plus what the loop charged, from the session's own
        accounting. Usage lives on the conversation, not on the events."""
        try:
            state = self.session.state() or {}
        except Exception:
            state = {}
        prompt = int((state.get("usage") or {}).get("prompt") or 0)
        output = int((state.get("usage") or {}).get("output") or 0)
        cost = float((state.get("usage") or {}).get("cost") or 0.0)

        class _Usage:
            prompt_tokens = prompt
            output_tokens = output
            total = prompt + output
            cost_usd = cost

        class _Result:
            usage = _Usage()

        return {"text": "".join(text_parts), "steps": steps, "stopped": stopped,
                "result": _Result()}

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


def _with_prior(text: str, prior: list[dict[str, str]]) -> str:
    """The history a client sent, quoted in front of the task.

    Kept short — each turn trimmed — because this is a courtesy to a
    stateless client, not a transcript to re-read: the agent's recall is
    what decides what matters, and a wall of quoted prose at the front of
    every request is a tax on every turn that pays for it.
    """
    kept = [item for item in prior if item.get("text", "").strip()][-6:]
    if not kept:
        return text
    lines = []
    for item in kept:
        speaker = "User" if item.get("role") == "user" else "Assistant"
        body = item["text"].strip()
        if len(body) > 1200:
            body = body[:1200] + " …"
        lines.append(f"{speaker}: {body}")
    return ("Earlier in this conversation (sent by the client for context):\n\n"
            + "\n\n".join(lines) + "\n\nNow the task:\n\n" + text)


class SessionMap:
    """Every live session, keyed by the id a client presented."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._talks: dict[str, Talk] = {}
        self._swept = time.monotonic()
        self._counter = 0

    def for_session(self, presented: str) -> Talk:
        """The session to answer on, new if there is none.

        An id that names no live session starts a fresh one — a client that
        sends a stale id after a restart gets a working endpoint rather
        than a 404, and the fresh id it gets back tells it so.
        """
        now = time.monotonic()
        with self._lock:
            if now - self._swept > SWEEP_EVERY:
                self._sweep(now)
            talk = self._talks.get(presented)
            if talk is None:
                self._counter += 1
                identifier = (presented if presented
                              else f"api-{time.strftime('%Y%m%d-%H%M%S')}"
                                   f"-{self._counter:04d}")
                talk = Talk(self.config, identifier)
                self._talks[identifier] = talk
            talk.last_used = now
            return talk

    def _sweep(self, now: float) -> None:
        dead = [key for key, talk in self._talks.items()
                if now - talk.last_used > IDLE_TTL]
        for key in dead:
            talk = self._talks.pop(key)
            talk.close()
        self._swept = now

    def close_all(self) -> None:
        with self._lock:
            talks = list(self._talks.values())
            self._talks.clear()
        for talk in talks:
            talk.close()
