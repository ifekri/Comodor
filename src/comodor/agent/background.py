"""Background delegates: the parent keeps answering while children work.

A synchronous delegate already exists — the parent hands over one brief, waits,
and gets the answer. This module is the same shape with one difference: the
parent does not wait. It is told at once that the work started, keeps its turn,
and the finished answer arrives later as its own turn, never spliced into the
middle of anything.

The rules are all structural, because rules a model can talk its way around
are decoration:

* **Slots, not a queue.** ``max_background`` run at once; a call beyond that is
  refused immediately with a plain error. A model cannot stockpile work it will
  never supervise.
* **Completions wait for a turn boundary.** A finished child's answer is held
  until the caller asks for it between turns — never injected mid-stream, which
  would break the request's alternation and every cached prefix behind it.
* **Nothing survives a crash in disguise.** State is persisted; on reload, a
  delegate that was running when the process died is reported ``lost``, not
  pretended to be alive.
"""

from __future__ import annotations

import itertools
import json
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..events import Cancellation, EventBus, Kind


@dataclass
class DelegateRun:
    """One background delegate, from launch to delivery."""

    id: str
    brief: str
    label: str = ""
    state: str = "running"           # running | done | failed | stopped | lost
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    steps: int = 0
    tool_calls: int = 0
    tokens: int = 0
    answer: str = ""
    error: str = ""
    delivered: bool = False

    def as_dict(self, brief_chars: int = 120) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label or self.brief[:brief_chars],
            "state": self.state, "steps": self.steps,
            "tool_calls": self.tool_calls, "tokens": self.tokens,
            "elapsed": round((self.ended_at or time.time()) - self.started_at, 1),
            "error": self.error[:200],
        }


class BackgroundDelegates:
    """The slots, the threads, and the finished answers waiting to be read.

    One instance per session. The tool adds work; the loop drains completions
    at the turn boundary; the interface lists and stops what is running.
    """

    def __init__(self, config: Any, bus: EventBus, spawner: Callable[..., Any],
                 persist_path: Path | None = None) -> None:
        self.config = config
        self.bus = bus
        self.spawner = spawner
        self.persist_path = persist_path
        self._runs: dict[str, DelegateRun] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._threads: list[threading.Thread] = []
        self._cancelled: set[str] = set()
        self._cancels: dict[str, Cancellation] = {}
        self._load()

    # -- launching --------------------------------------------------------- #

    @property
    def slots_busy(self) -> int:
        with self._lock:
            return sum(1 for run in self._runs.values() if run.state == "running")

    @property
    def listening(self) -> bool:
        """Whether anything is around to see a completion event.

        The manager existing is not the same as someone draining its turns.
        Completions only become conversation at a turn boundary, and only an
        interface that polls between turns does that.
        """
        return self.bus.listening

    def start(self, brief: str, label: str = "", write: bool = False,
              cwd: Any = None) -> tuple[bool, str, str]:
        """Launch one delegate. Returns (accepted, id, why-not).

        Refused rather than queued when every slot is busy: the error says
        what is running and how to wait, so the next attempt is an informed
        one instead of a repeat.
        """
        limit = self.config.delegation.max_background
        cancel = Cancellation()
        with self._lock:
            running = sum(1 for run in self._runs.values()
                          if run.state == "running")
            if running >= limit:
                return False, "", (
                    f"all {limit} background slots are busy — the answer to a "
                    "new one would arrive unsupervised. Wait for one of: "
                    + ", ".join(sorted(run.id for run in self._runs.values()
                                       if run.state == "running"))
                    + " to finish, or run this task synchronously.")
            identifier = f"d{next(self._counter)}"
            run = DelegateRun(id=identifier, brief=brief, label=label)
            self._runs[identifier] = run

        self._cancels[identifier] = cancel
        thread = threading.Thread(
            target=self._work,
            args=(identifier, brief, write, cwd, cancel),
            daemon=True, name=f"comodor-delegate-{identifier}",
        )
        with self._lock:
            # Written before the thread exists, not after it. Two reasons, and
            # the second is the bug this change is for: a crash in the gap
            # between starting a worker and recording it left no evidence of
            # the delegate at all, which is the one thing this file is for.
            # And a worker that finished inside that gap wrote `done`, which
            # this line then overwrote with the `running` it had read a moment
            # earlier.
            self._persist()

            # Started and registered without letting go of the lock, so a
            # launch is one indivisible step as far as `wait()` is concerned.
            #
            # Both orderings are wrong on their own. Appending first exposes a
            # thread that has not started, and joining one of those raises
            # `RuntimeError: cannot join thread before it is started`, which
            # aborts the rest of shutdown. Appending afterwards leaves a
            # started-but-unlisted thread, and a `wait()` landing there returns
            # having joined nothing — so shutdown closes the tools and the
            # history underneath a delegate that is still working.
            #
            # `wait()` takes this same lock to take its snapshot, so it either
            # sees the finished launch or waits for it. The worker does not
            # need the lock until it has a result, so holding it across
            # `start()` blocks nobody who is doing anything.
            try:
                thread.start()
            except RuntimeError as problem:
                # The runtime would not give us a thread. Nothing is going to
                # move this run out of `running`, so it must not be left there:
                # the slot would be occupied for the rest of the session, and
                # the next one would read the record and report a task that
                # never ran as lost.
                self._runs.pop(identifier, None)
                self._persist()
                self._cancels.pop(identifier, None)
                return False, "", (
                    f"the delegate could not be started: {problem}")
            self._threads.append(thread)

        self._emit(identifier, "started")
        return True, identifier, ""

    def _work(self, identifier: str, brief: str, write: bool, cwd: Any,
              cancel: Cancellation) -> None:
        run: DelegateRun | None = None
        try:
            loop = self.spawner(cwd=cwd, mode="act" if write else "plan",
                                max_steps=12, max_seconds=600.0, cancel=cancel)
            result = loop.run(brief)
            with self._lock:
                run = self._runs.get(identifier)
                if run is None:
                    return
                run.steps = result.steps
                run.tool_calls = result.tool_calls
                run.tokens = result.usage.prompt_tokens
                run.ended_at = time.time()
                if identifier in self._cancelled:
                    run.state = "stopped"
                    run.answer = ""
                elif result.stopped == "error":
                    run.state = "failed"
                    run.error = result.error
                elif not (result.text or "").strip():
                    run.state = "failed"
                    run.error = (f"stopped after {result.steps} steps without "
                                 f"an answer ({result.stopped})")
                else:
                    run.state = "done"
                    run.answer = (result.text or "").strip()
                # Persisted before releasing the lock: the moment `slots_busy`
                # says this run is finished, the file must agree. Persisting
                # outside it once let a reload read "running" for work that
                # had visibly ended — exactly the lie `lost` must never tell.
                self._persist()
        except Exception as error:               # the thread must never leak
            with self._lock:
                run = self._runs.get(identifier)
                if run is not None:
                    run.state = "failed"
                    run.error = f"{type(error).__name__}: {error}"
                    run.ended_at = time.time()
                    self._persist()
        if run is not None:
            self._emit(identifier, run.state)

    # -- draining ---------------------------------------------------------- #

    def take_pending(self) -> list[dict[str, Any]]:
        """Finished answers not yet delivered, oldest first, marked delivered.

        Read at a turn boundary and turned into turns there — the boundary is
        the only place a new message can join the conversation without
        breaking the alternation the provider caches against.
        """
        with self._lock:
            done = [run for run in sorted(self._runs.values(),
                                          key=lambda item: item.ended_at)
                    if run.state in ("done", "failed", "stopped", "lost")
                    and not run.delivered]
            for run in done:
                run.delivered = True
        return [run.as_dict() | {"answer": run.answer, "brief": run.brief}
                for run in done]

    def restore(self, identifiers: list[str]) -> None:
        """Put back completions a caller could not deliver after all.

        Taking marks them delivered; if the turn that was meant to carry them
        did not start, they must not silently vanish.
        """
        with self._lock:
            for identifier in identifiers:
                run = self._runs.get(identifier)
                if run is not None:
                    run.delivered = False

    # -- control ----------------------------------------------------------- #

    def stop(self, identifier: str) -> bool:
        with self._lock:
            run = self._runs.get(identifier)
            if run is None or run.state != "running":
                return False
            self._cancelled.add(identifier)
            cancel = self._cancels.get(identifier)
        if cancel is not None:
            cancel.cancel()                        # interrupt immediately
        self._emit(identifier, "stopping")
        return True

    def stop_all(self) -> int:
        with self._lock:
            running = [run.id for run in self._runs.values()
                       if run.state == "running"]
            cancels = [self._cancels[identifier] for identifier in running
                       if identifier in self._cancels]
            self._cancelled.update(running)
        for cancel in cancels:
            cancel.cancel()
        for identifier in running:
            self._emit(identifier, "stopping")
        return len(running)

    def listing(self) -> list[dict[str, Any]]:
        with self._lock:
            return [run.as_dict() for run in
                    sorted(self._runs.values(), key=lambda item: item.id)]

    def running_ids(self) -> list[str]:
        with self._lock:
            return [run.id for run in self._runs.values()
                    if run.state == "running"]

    def wait(self, timeout: float = 30.0) -> None:
        """Block until everything running settles — used at shutdown.

        The copy is taken under the lock. Reading the list while `start()`
        appends to it is the sort of race that costs nothing until the day it
        costs a shutdown, and the copy is three items long.
        """
        deadline = time.monotonic() + timeout
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        with self._lock:
            self._threads = [thread for thread in self._threads
                             if thread.is_alive()]

    # -- plumbing ---------------------------------------------------------- #

    def _emit(self, identifier: str, state: str) -> None:
        try:
            with self._lock:
                run = self._runs.get(identifier)
                payload = run.as_dict() if run else {"id": identifier}
            payload["state"] = state
            self.bus.emit(Kind.DELEGATE, **payload)
        except Exception:
            pass

    # -- crash safety -------------------------------------------------------- #

    def _persist(self) -> None:
        """Write the runs to the session's directory, best-effort.

        This is not a queue and not a resume mechanism. It is the evidence:
        after a crash the next session can say plainly what was running and
        mark it lost, rather than leaving silent orphans behind.

        **The caller must hold `_lock`.** Snapshotting and writing are one
        step, and separating them is not a style question — it is how a
        finished delegate came to be recorded as running:

            main                                  worker
            ──────────────────────────────────────────────────────────
            _snapshot()  → "running"
                                                  state = "done"
                                                  _snapshot() → "done"
                                                  write("done")
            write("running")   ← older, and last

        The next session read `running` and reported a delegate that had
        finished perfectly well as lost.

        The lock is not taken here because `_work` calls this while already
        holding it and `threading.Lock` is not reentrant. Making it an
        `RLock` would work and would also make the requirement invisible;
        requiring it of callers keeps it somewhere a reader can see it, and
        `test_every_persist_happens_while_the_lock_is_held` keeps it true.
        """
        if self.persist_path is None:
            return
        try:
            document = self._snapshot()
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(json.dumps(document, indent=1),
                                         encoding="utf-8")
        except OSError:
            pass

    def _snapshot(self) -> dict[str, Any]:
        """The document to persist. The caller holds `_lock`.

        It used to say the lock was needed only "when the snapshot must agree
        with the state they just changed", which sounds like a narrow case and
        is in fact every case: a snapshot that does not agree with the state is
        one that can be written after a newer one.
        """
        return {
            "saved_at": time.time(),
            "runs": [vars(run) | {} for run in self._runs.values()],
        }

    def _load(self) -> None:
        """Mark anything that was mid-flight when the process died as lost.

        A resumed session must not pretend a child is still working. Nothing
        here resurrects one; the record exists so the answer to "what
        happened to those three background tasks?" is honest.
        """
        if self.persist_path is None or not self.persist_path.exists():
            return
        try:
            document = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(document, dict):
            return
        changed = False
        highest = 0
        for record in document.get("runs") or []:
            if not isinstance(record, dict) or not record.get("id"):
                continue
            if record.get("state") != "running":
                continue
            run = DelegateRun(
                id=str(record["id"]), brief=str(record.get("brief", "")),
                label=str(record.get("label", "")), state="lost",
                steps=int(record.get("steps") or 0),
                tool_calls=int(record.get("tool_calls") or 0),
                tokens=int(record.get("tokens") or 0),
            )
            run.ended_at = time.time()
            run.error = "the session ended while this was running"
            run.delivered = False              # type: ignore[attr-defined]
            with self._lock:
                self._runs[run.id] = run
                highest = max(highest, _id_number(run.id))
            changed = True
        if changed:
            with self._lock:
                self._counter = itertools.count(highest + 1)
                # Nothing else is running yet - this is construction - but the
                # rule is that every write happens under the lock, and a rule
                # with one exception is a rule somebody will copy the exception
                # from.
                self._persist()


def _id_number(identifier: str) -> int:
    digits = "".join(character for character in identifier if character.isdigit())
    return int(digits) if digits else 0


#: The budget for one completion's answer. The full text can be an enormous
#: thing a child assembled; the parent needs enough to act on, not all of it.
#: Long answers spill to a file and stay reachable rather than being cut off.
SUMMARY_FLOOR = 2_000


def completion_turn(record: dict[str, Any],
                    summary_max: int = 24_000) -> str:
    """Format one finished delegate as the text of a new turn.

    The payload is self-contained — the parent may have drifted into entirely
    other work since it launched this — and it is the text of a *user* turn,
    because at a turn boundary a finished answer is simply something that
    happened and is being reported.
    """
    identifier = record.get("id", "?")
    label = record.get("label") or ""
    head = f"Background task {identifier}"
    if label:
        head += f" ({label})"
    state = record.get("state", "done")
    if state == "done":
        body = str(record.get("answer", "")).strip()
        spilled = ""
        limit = max(SUMMARY_FLOOR, summary_max)
        if len(body) > limit:
            kept = body[:limit]
            cut = kept.rfind("\n")
            if cut > SUMMARY_FLOOR:
                kept = kept[:cut]
            spilled = overflow_spill(identifier, body)
            body = (kept + "\n\n[The full answer was longer than the budget. "
                    f"{spilled}]")
        return f"[{head} finished]\n\n{body}"
    if state == "stopped":
        return f"[{head} was stopped before it finished.]"
    if state == "lost":
        return (f"[{head} was lost: the session ended while it was running, "
                "so its answer does not exist.]")
    error = str(record.get("error", "")).strip() or "no details"
    return f"[{head} failed: {error}]"


def overflow_spill(identifier: str, full: str, ctx: Any = None) -> str:
    """The full answer, kept rather than dropped — Comodor's overflow rule.

    Returns the sentence saying where the whole text went. Failure to write
    the spill file is not fatal: the summary still arrives.
    """
    from ..tools import overflow

    try:
        if ctx is not None:
            target = overflow._write(full, ctx, f"delegate-{identifier}-answer")
            if target is not None:
                return (f"all of it is at {target} — read it with read_file "
                        "using offset and limit, or search it with grep")
            return "the full text could not be written to a file"
        target = Path(tempfile.gettempdir()) / \
            f"comodor-delegate-{identifier}-answer.txt"
        target.write_text(full, encoding="utf-8", errors="replace")
        return (f"all of it is at {target} — read it with read_file using "
                "offset and limit, or search it with grep")
    except OSError:
        return "the full text could not be written to a file"
