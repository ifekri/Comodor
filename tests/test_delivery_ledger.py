"""The delivery ledger: a reply noted before it is sent, redelivered after
a crash, and swept when it is too old to matter."""

from __future__ import annotations

import json
import time
from pathlib import Path

from comodor.channels.ledger import FRESH_WINDOW, RECOVERED_PREFIX, DeliveryLedger, resume


def _ledger(tmp_path: Path, platform: str = "telegram") -> DeliveryLedger:
    return DeliveryLedger(tmp_path / "delivery" / f"{platform}.jsonl", platform)


# -- the write path ------------------------------------------------------------ #

def test_a_send_is_noted_before_it_is_marked(tmp_path):
    ledger = _ledger(tmp_path)
    seen: list[str] = []

    def deliver(chat_id, body):
        seen.append(ledger._entries()[-1]["status"])   # observed mid-send
        return {"ok": True}

    ledger.send(42, "the answer", deliver)
    assert seen == ["pending"], "the record must exist before the send"
    assert ledger._entries()[-1]["status"] == "sent"


def test_a_failing_send_is_marked_failed_and_reraised(tmp_path):
    ledger = _ledger(tmp_path)

    class Problem(Exception):
        pass

    def deliver(chat_id, body):
        raise Problem("network gone")

    try:
        ledger.send(42, "the answer", deliver)
        raised = False
    except Problem:
        raised = True
    assert raised
    assert ledger._entries()[-1]["status"] == "failed"


def test_a_ledger_failure_never_breaks_the_send(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    # A directory where the file belongs makes every append fail.
    ledger.path.unlink(missing_ok=True)
    ledger.path.mkdir(parents=True)

    def deliver(chat_id, body):
        return {"ok": True}

    assert ledger.send(42, "the answer", deliver) == {"ok": True}


# -- recovery ---------------------------------------------------------------- #

def test_a_crash_after_generating_the_answer_redelivers_once(tmp_path):
    """The spec's own case: the run finished, the send did not happen, the
    daemon is killed. On start the reply goes out once, marked as recovered."""
    ledger = _ledger(tmp_path)
    ledger.record("777", "the forgotten answer")
    # No marker ever written — the process died between record and send.

    sent: list[tuple[object, str]] = []
    delivered = resume(ledger, lambda chat, body: sent.append((chat, body)))

    assert delivered == 1
    chat, body = sent[0]
    assert chat == "777"
    assert body.startswith(RECOVERED_PREFIX)
    assert "the forgotten answer" in body
    assert ledger.unclaimed() == [], "redelivery must be at-most-once"


def test_a_second_resume_sends_nothing(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record("777", "body")
    resume(ledger, lambda chat, body: None)
    again = resume(ledger, lambda chat, body: None)
    assert again == 0


def test_a_failed_redelivery_is_marked_and_not_retried(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record("777", "body")

    def dead(chat, body):
        raise RuntimeError("no route")

    assert resume(ledger, dead) == 0
    assert ledger.unclaimed() == []


def test_a_pending_reply_older_than_a_day_is_left(tmp_path):
    ledger = _ledger(tmp_path)
    identifier = ledger.record("777", "stale body")
    with ledger._lock:
        entries = ledger._entries()
        for entry in entries:
            if entry.get("record_id") == identifier:
                entry["ts"] -= FRESH_WINDOW + 60
        ledger._rewrite(entries)

    assert resume(ledger, lambda chat, body: None) == 0


def test_recovery_continues_past_one_dead_chat(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record("dead", "first")
    ledger.record("alive", "second")

    def deliver(chat, body):
        if chat == "dead":
            raise RuntimeError("refused")

    delivered = resume(ledger, deliver)
    assert delivered == 1, "the living chat still gets its answer"


def test_recovery_marks_a_bodyless_record_failed(tmp_path):
    ledger = _ledger(tmp_path)
    with ledger._lock:
        ledger._append({"platform": "telegram", "chat_id": "1",
                        "record_id": "x", "status": "pending",
                        "attempts": 0, "ts": time.time()})
    assert resume(ledger, lambda chat, body: None) == 0
    statuses = {entry["status"] for entry in ledger._entries()}
    assert "failed" in statuses


# -- housekeeping ----------------------------------------------------------- #

def test_the_sweep_drops_old_records_and_keeps_recent(tmp_path):
    ledger = _ledger(tmp_path)
    old = ledger.record("1", "old")
    new = ledger.record("2", "new")
    with ledger._lock:
        entries = ledger._entries()
        for entry in entries:
            if entry.get("record_id") == old:
                entry["ts"] -= 8 * 24 * 3600
        ledger._rewrite(entries)

    kept = ledger.sweep()
    ids = {entry.get("record_id") for entry in ledger._entries()}
    assert kept == 1 and old not in ids and new in ids


def test_the_file_is_json_lines_a_human_can_read(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record(5, "body")
    line = ledger.path.read_text(encoding="utf-8").strip().splitlines()[0]
    record = json.loads(line)
    assert record["platform"] == "telegram"
    assert record["chat_id"] == "5"
    assert record["status"] == "pending"


def test_platforms_do_not_share_a_file(tmp_path):
    telegram = _ledger(tmp_path, "telegram")
    whatsapp = _ledger(tmp_path, "whatsapp")
    telegram.record("1", "a")
    whatsapp.record("2", "b")
    assert len(telegram._entries()) == 1
    assert len(whatsapp._entries()) == 1
