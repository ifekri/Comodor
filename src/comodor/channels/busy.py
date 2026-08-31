"""What a new message does when a turn is already running.

Every channel used to answer this the same way: refuse the message and ask
the human to stop the running work first. That is a queue behind a human —
they hold the message in their head and resend it. It remains the default,
because interrupting an agent that edits files and runs commands on the
strength of a second message arriving unprompted is a decision somebody
should make consciously, per channel, in their own settings file.

The second choice, `interrupt`, stops the running turn and starts the new
one. What keeps that safe:

* an interrupt is not a rollback. Every file write the running turn made is
  already a checkpoint (`tools/fs.py` snapshots before every write), so the
  stop leaves completed work exactly as it was — undoable, not erased;
* the stop is cooperative: the loop sees the cancellation flag, emits its
  own `cancelled` event, and the interface renders "stopped" as it already
  does when the human presses stop;
* if the new turn cannot start even after the interrupt (the worker thread
  is still draining, say), the message is refused with that said plainly
  rather than silently dropped.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

#: How long the strategy is willing to wait for the running turn to release
#: the session after an interrupt, before trying to start anyway.
SETTLE_SECONDS = 3.0
#: How often that wait is re-checked.
POLL_SECONDS = 0.05


def interrupt_note(event: dict | None) -> str:
    """The line a stopped turn carries when it stopped for a new message.

    The loop already emits a `reason` on the cancelled event; this turns it
    into the one sentence the spec asks for. A plain stop gets nothing —
    the human pressed it and knows.
    """
    reason = str((event or {}).get("reason") or "")
    if reason == "interrupt":
        return (" — stopped because a new message arrived; completed file "
                "work is kept as checkpoints")
    return ""


def normalise(value: object) -> str:
    """The configured busy mode, coerced to one of the two names.

    Unknown values fall back to the default rather than blowing up at
    message time — a typo in a settings file must not disable a channel.
    """
    mode = str(value or "").strip().lower()
    return mode if mode in ("queue", "interrupt") else "queue"


@dataclass
class BusyResult:
    """Whether the message started, and what to tell the human when not."""

    started: bool
    note: str = ""


def start_or_steer(
    session: object,
    text: str,
    images: list[str] | None,
    mode: str,
    refuse: Callable[[str], None],
) -> BusyResult:
    """Try to start a turn, and when busy, apply the channel's busy mode.

    `refuse` is the bot's own way of answering the human (each channel
    carries its formatting and its menu), so the strategy stays channel-
    blind and each `_start_turn` stays one call.

    Queue mode is exactly the old behaviour. Interrupt mode cancels the
    running turn, waits briefly for it to settle, and tries again.
    """
    if session.send(text, images=images):
        return BusyResult(started=True)

    if normalise(mode) != "interrupt":
        refuse("Something is already running. Stop it first.")
        return BusyResult(started=False)

    session.interrupt("interrupt")
    deadline = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < deadline and session.busy:
        time.sleep(POLL_SECONDS)
    if session.send(text, images=images):
        return BusyResult(started=True)
    refuse("The running turn stopped, but the next one could not start yet. "
           "Send it again in a moment.")
    return BusyResult(started=False)
