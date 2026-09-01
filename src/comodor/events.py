"""The one channel between the agent worker and the UI thread.

The agent runs in a background thread; Rich renders from the main thread. They
share no mutable state — the worker only *emits* events and the UI only *reads*
them. That rule is what keeps the interface responsive while a tool is running
and makes the whole agent reusable headlessly: swap the subscriber and the same
loop drives a JSON stream instead of a terminal.

One flow needs to go the other way — asking the user to approve a tool call —
so :class:`Request` carries its own reply slot. The worker blocks on it while
the UI keeps painting.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator


class Kind(str, Enum):
    """Every event the agent can emit."""

    # conversation
    USER_MESSAGE = "user_message"
    ASSISTANT_START = "assistant_start"
    ASSISTANT_DELTA = "assistant_delta"          # streamed token(s)
    ASSISTANT_END = "assistant_end"
    REASONING_DELTA = "reasoning_delta"          # extended-thinking stream

    # tools
    TOOL_START = "tool_start"
    TOOL_OUTPUT = "tool_output"                  # incremental output (shell)
    TOOL_END = "tool_end"

    # lifecycle
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    STEP = "step"                                # one loop iteration completed
    CANCELLED = "cancelled"

    # the screen, when the agent is driving one
    SCREEN = "screen"                            # a frame, or an action on one

    # side channels
    STATUS = "status"                            # provider/model/connection
    USAGE = "usage"                              # tokens + cost + context fill
    MEMORY = "memory"                            # lessons recalled or learned
    TODO = "todo"                                # task list changed
    NOTICE = "notice"                            # transient toast
    ERROR = "error"
    REQUEST = "request"                          # needs an answer from the user
    DELEGATE = "delegate"                        # background delegate state changed


@dataclass(slots=True)
class Event:
    kind: Kind
    payload: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    @property
    def text(self) -> str:
        return str(self.payload.get("text", ""))


@dataclass
class Request:
    """A question the worker needs answered before it can continue.

    Used for permission prompts. The worker calls :meth:`wait`; the UI renders
    the dialog and calls :meth:`answer`. A timeout means "denied", so a
    forgotten prompt can never wedge the agent forever.
    """

    id: str
    prompt: str
    options: list[str]
    detail: str = ""
    kind: str = "permission"
    meta: dict[str, Any] = field(default_factory=dict)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)
    _answer: str | None = field(default=None, repr=False)

    def answer(self, choice: str) -> None:
        self._answer = choice
        self._done.set()

    def wait(self, timeout: float | None = None) -> str:
        if self._done.wait(timeout):
            return self._answer or (self.options[-1] if self.options else "no")
        return self.options[-1] if self.options else "no"

    @property
    def answered(self) -> bool:
        return self._done.is_set()


Subscriber = Callable[[Event], None]


class EventBus:
    """Fan-out queue: every subscriber sees every event, in order.

    Subscribers are called on the emitting thread, so they must be cheap — the
    UI subscriber just appends to its own queue and returns.
    """

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._lock = threading.Lock()
        self._closed = False

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

        return unsubscribe

    def emit(self, kind: Kind, **payload: Any) -> Event:
        event = Event(kind=kind, payload=payload)
        self.publish(event)
        return event

    @property
    def listening(self) -> bool:
        """Whether anything would see an event published now.

        A question needs somewhere to be answered. The bus existing is not the
        same as somebody being there, and a request published into an empty
        room waits for its full timeout before defaulting to no.
        """
        with self._lock:
            return bool(self._subscribers) and not self._closed

    def publish(self, event: Event) -> None:
        with self._lock:
            if self._closed:
                return
            targets = list(self._subscribers)
        for subscriber in targets:
            try:
                subscriber(event)
            except Exception:
                # A broken subscriber must never take down the agent mid-task.
                pass

    def ask(self, request: Request) -> Request:
        """Emit a question and hand the caller the object to wait on."""
        self.publish(Event(kind=Kind.REQUEST, payload={"request": request}))
        return request

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._subscribers.clear()


class EventQueue:
    """A subscriber that buffers events for a consumer to drain at its own pace.

    The UI drains this once per frame: rendering never blocks the agent, and a
    burst of stream deltas collapses into a single repaint.
    """

    def __init__(self, bus: EventBus, maxsize: int = 0) -> None:
        self._queue: queue.Queue[Event] = queue.Queue(maxsize)
        self._unsubscribe = bus.subscribe(self._queue.put)

    def drain(self, limit: int = 512) -> list[Event]:
        events: list[Event] = []
        for _ in range(limit):
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def wait(self, timeout: float) -> Event | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def __iter__(self) -> Iterator[Event]:
        while True:
            yield self._queue.get()

    def close(self) -> None:
        self._unsubscribe()


class Cancellation:
    """Cooperative cancellation, checked between agent steps and stream chunks."""

    def __init__(self) -> None:
        self._flag = threading.Event()

    def cancel(self) -> None:
        self._flag.set()

    def reset(self) -> None:
        self._flag.clear()

    @property
    def cancelled(self) -> bool:
        return self._flag.is_set()

    def raise_if_cancelled(self) -> None:
        if self._flag.is_set():
            raise Cancelled()


class Cancelled(Exception):
    """Raised inside the worker when the user pressed Esc."""
