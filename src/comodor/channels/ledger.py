"""At-least-once delivery for the channel bots.

A chat turn can end after the answer was produced and before it reached the
network: the process is killed mid-send, the network is down for the reply
but was up for the work, or the daemon is restarted while a message sits in
a send queue. The agent remembers the work; the human waiting for the
answer remembers only silence.

This ledger is the fix, and it is deliberately small. Every outbound reply
to a chat is appended to a JSONL file *before* it is sent, as ``pending``;
a successful send marks the record ``sent``. On daemon start, records still
``pending`` and younger than a day are redelivered once, prefixed so the
human can tell a fresh answer from a recovered one. Older than a day the
human has moved on and the record is only cleaned away.

The rules that keep it honest:

* **Pending, not queued.** The ledger does not do the sending — the bot
  does. It only remembers what was tried, so a crash cannot erase an
  answer that was produced but never arrived.
* **At-most-once redelivery.** A pending record is redelivered once, and
  if that fails it is marked ``failed`` and left. A bot that retries forever
  turns one lost message into a flood.
* **Best effort in both directions.** Writing the record or the marker must
  never break the send itself; the ledger failing means delivery degrades
  to exactly what existed before this file.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

#: A pending answer older than this is not redelivered: the conversation it
#: belonged to has been idle for a day, and a recovered reply to a day-old
#: message is more likely to confuse than to help.
FRESH_WINDOW = 24 * 3600.0

#: Redelivery happens once. A second failure marks the record failed.
MAX_ATTEMPTS = 1

#: Records older than this are dropped from the file.
KEEP_DAYS = 7.0

#: Prefixed on a recovered reply, so "♻️" in a chat means one thing.
RECOVERED_PREFIX = "♻️ (redelivered after a restart)\n"


class DeliveryLedger:
    """The JSONL file behind one platform's outbound replies."""

    def __init__(self, path: Path, platform: str) -> None:
        self.path = path
        self.platform = platform
        self._lock = threading.Lock()
        self._ensure()

    def _ensure(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    # -- the write path ------------------------------------------------------ #

    def record(self, chat_id: Any, body: str) -> str:
        """Note an answer about to be sent. Returns its record id.

        The body itself rides the pending line: after a crash there is no
        conversation to rebuild it from, and a ledger that remembers only
        that an answer existed redelivers silence. Long answers are kept in
        full — a recovered reply that is cut off is a new kind of lie.
        """
        identifier = f"{int(time.time() * 1000):x}-{id(body) % 100000:x}"
        with self._lock:
            self._append({
                "platform": self.platform,
                "chat_id": _plain_id(chat_id),
                "record_id": identifier,
                "body": body,
                "status": "pending",
                "attempts": 0,
                "ts": time.time(),
            })
        return identifier

    def mark(self, record_id: str, status: str) -> None:
        """Move one record to sent or failed."""
        with self._lock:
            self._append({
                "platform": self.platform,
                "record_id": record_id,
                "status": status,
                "attempts": 0,
                "ts": time.time(),
            })

    # -- recovery ------------------------------------------------------------ #

    def unclaimed(self, now: float | None = None) -> list[dict[str, Any]]:
        """Pending answers still worth delivering, oldest first.

        Latest state per record wins: the file holds both the pending line
        and the later marker, and only the last line for a record counts.
        """
        now = time.time() if now is None else now
        state: dict[str, dict[str, Any]] = {}
        with self._lock:
            for entry in self._entries():
                identifier = str(entry.get("record_id") or "")
                if identifier:
                    state[identifier] = entry
        pending = [entry for entry in state.values()
                   if entry.get("status") == "pending"
                   and now - float(entry.get("ts") or 0) <= FRESH_WINDOW]
        return sorted(pending, key=lambda entry: float(entry.get("ts") or 0))

    # -- housekeeping ---------------------------------------------------------- #

    def sweep(self) -> int:
        """Rewrite the file without anything older than the keep window."""
        cutoff = time.time() - KEEP_DAYS * 24 * 3600.0
        with self._lock:
            entries = [entry for entry in self._entries()
                       if float(entry.get("ts") or 0) >= cutoff
                       and entry.get("status") in ("pending", "sent", "failed")]
            self._rewrite(entries)
        return len(entries)

    # -- the send wrapper ------------------------------------------------------ #

    def send(
        self, chat_id: Any, body: str,
        deliver: Callable[[Any, str], Any],
    ) -> Any:
        """Deliver one reply through the ledger: note, send, mark.

        Everything the bot needs is here, so each send path is one call and
        nobody has to remember the three steps. A `deliver` that raises is
        marked failed and re-raised — the bot keeps its own error handling.
        """
        identifier = self.record(chat_id, body)
        try:
            result = deliver(chat_id, body)
        except BaseException:
            self.mark(identifier, "failed")
            raise
        self.mark(identifier, "sent")
        return result

    # -- the file ---------------------------------------------------------- #

    def _entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        entries: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                entries.append(record)
        return entries

    def _append(self, entry: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass                       # best effort, as the module says

    def _rewrite(self, entries: list[dict[str, Any]]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                "".join(json.dumps(entry, ensure_ascii=False) + "\n"
                        for entry in entries), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            pass


def _plain_id(chat_id: Any) -> str:
    """A chat id that will survive JSON unchanged — str or int both fine."""
    return chat_id if isinstance(chat_id, str) else str(chat_id)


def resume(
    ledger: DeliveryLedger, deliver: Callable[[Any, str], Any],
) -> int:
    """Redeliver what a restart left pending. Returns how many went out.

    Each recovered body is prefixed so the human can tell it apart, and the
    record is marked sent when the send took. A send that fails is marked
    failed and the rest of the queue continues — one dead chat must not
    hold every recovered answer.
    """
    delivered = 0
    for entry in ledger.unclaimed():
        identifier = str(entry.get("record_id") or "")
        if not identifier:
            continue
        # The pending line carries the body itself, written at record time:
        # after a crash there is no conversation to rebuild it from.
        body = str(entry.get("body") or "")
        if not body:
            # A pending line with nothing to say cannot be delivered — mark
            # it so the next resume does not look at it again.
            ledger.mark(identifier, "failed")
            continue
        try:
            deliver(entry.get("chat_id"), RECOVERED_PREFIX + body)
        except Exception:
            ledger.mark(identifier, "failed")
            continue
        ledger.mark(identifier, "sent")
        delivered += 1
    return delivered
