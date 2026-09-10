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
    REQUEST_EXPIRED = "request_expired"          # nobody answered in time
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

    Resolution is a **claim**, not an assignment. Exactly one of "the person
    answered" and "the wait gave up" can win, and the loser is told: a request
    that timed out has already been acted on, so accepting a late answer would
    tell a client its decision landed when the worker had moved on. Both paths
    run on different threads and can arrive in the same instant, which is why
    this is a lock and not a flag read.
    """

    id: str
    prompt: str
    options: list[str]
    detail: str = ""
    kind: str = "permission"
    meta: dict[str, Any] = field(default_factory=dict)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)
    _answer: str | None = field(default=None, repr=False)
    _claim: threading.Lock = field(default_factory=threading.Lock, repr=False)

    #: What the waiter falls back to when nobody answers. The last option,
    #: which for every request this program raises is the safe one: `deny` for
    #: a permission, and a value the question decoder reads as cancelled.
    @property
    def fallback(self) -> str:
        return self.options[-1] if self.options else "no"

    @property
    def choice(self) -> str:
        """The answer taken, or the fallback if none was."""
        return self._answer or self.fallback

    def answer(self, choice: str) -> bool:
        """Take this answer, unless the request is already resolved.

        Returns whether it was taken. A caller that gets `False` must not tell
        anybody their decision was accepted.
        """
        with self._claim:
            if self._done.is_set():
                return False
            self._answer = choice
            self._done.set()
            return True

    def expire(self) -> bool:
        """Claim this request as unanswered, unless somebody answered first.

        Returns whether the claim was made, which is the only safe way to know
        a timeout is the reason the wait ended rather than a reply that landed
        in the same instant.
        """
        with self._claim:
            if self._done.is_set():
                return False
            self._answer = self.fallback
            self._done.set()
            return True

    def wait(self, timeout: float | None = None) -> str:
        if self._done.wait(timeout):
            return self._answer or self.fallback
        return self.fallback

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

    def resolve(self, request: Request,
                timeout: float | None = None) -> tuple[str, bool]:
        """Ask, wait, and say out loud if nobody came.

        Returns ``(choice, expired)``.

        Every blocking interaction in Comodor used to be ``ask(...).wait(t)``
        at the call site, which is correct for the worker and silent for
        everybody else: when the wait gave up, the request stayed open as far
        as any client knew. A card on screen stayed actionable for a decision
        the core had already taken, and answering it produced a resolution
        event for a choice nothing acted on.

        Publishing the expiry is what makes the timeout observable, and doing
        it here rather than at four call sites is what makes it impossible to
        forget. The claim inside :meth:`Request.expire` decides who won, so a
        reply landing in the same instant is not reported twice.
        """
        self.ask(request)
        request.wait(timeout)
        if request.expire():
            self.publish(Event(kind=Kind.REQUEST_EXPIRED,
                               payload={"request": request,
                                        "choice": request.choice}))
            return request.choice, True
        return request.choice, False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._subscribers.clear()


class ScopedBus:
    """A view of an EventBus that stamps an origin on everything it publishes.

    A delegate's loop emits the same kinds the parent's does — assistant
    messages, tool calls, a task list — and on the shared bus those are
    indistinguishable from the parent's own turn: a session relay would stream
    the child's raw answer as the parent's message, and the child's plan would
    replace the parent's. Stamping an origin is what lets a subscriber tell
    "said by this session's turn" from "said by work that turn launched"
    without the child knowing who is listening.

    Only publishing is scoped. `subscribe` is not offered: somebody who wants
    the child's events subscribes to the parent and reads the origin, which is
    what it is for. Requests ride to the parent unchanged apart from the tag —
    a permission the child needs answered is still a question for the person,
    and the reply travels on the `Request` object itself, not on the bus.
    """

    def __init__(self, parent: EventBus, origin: str) -> None:
        self._parent = parent
        self._origin = origin

    @property
    def origin(self) -> str:
        return self._origin

    @property
    def listening(self) -> bool:
        return self._parent.listening

    def emit(self, kind: Kind, **payload: Any) -> Event:
        payload.setdefault("origin", self._origin)
        return self._parent.emit(kind, **payload)

    def publish(self, event: Event) -> None:
        event.payload.setdefault("origin", self._origin)
        self._parent.publish(event)

    def ask(self, request: Request) -> Request:
        self.publish(Event(kind=Kind.REQUEST, payload={"request": request}))
        return request

    def resolve(self, request: Request,
                timeout: float | None = None) -> tuple[str, bool]:
        """The same claim-and-publish-expiry dance as the parent's `resolve`.

        Mirrored rather than delegated because the events must leave through
        *this* bus to carry the origin; the reasoning is EventBus.resolve's.
        """
        self.ask(request)
        request.wait(timeout)
        if request.expire():
            self.publish(Event(kind=Kind.REQUEST_EXPIRED,
                               payload={"request": request,
                                        "choice": request.choice}))
            return request.choice, True
        return request.choice, False


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
