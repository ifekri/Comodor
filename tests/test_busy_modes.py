"""Busy modes: the second message while a turn runs.

Queue is the default and unchanged behaviour. Interrupt stops the running
turn and starts the new one, saying plainly what happened. Both are decided
per channel in the settings file."""

from __future__ import annotations

import threading

from comodor.channels.busy import (
    POLL_SECONDS,
    SETTLE_SECONDS,
    interrupt_note,
    normalise,
    start_or_steer,
)
from comodor.channels.settings import keep_current


class FakeSession:
    """send() fails while busy; interrupt releases it after a moment."""

    def __init__(self, busy_turns: int = 1, release_after: float = 0.0):
        self.refusals_left = busy_turns
        self.release_after = release_after
        self.interrupted = False
        self.reason = ""
        self.refusals: list[str] = []

    def send(self, text, images=None):
        if self.refusals_left > 0:
            self.refusals_left -= 1
            if self.release_after:
                threading.Timer(self.release_after,
                                lambda: setattr(self, "refusals_left", 0)
                                ).start()
            return False
        return True

    def interrupt(self, reason: str = "stop"):
        self.interrupted = True
        self.reason = reason

    @property
    def busy(self) -> bool:
        return self.refusals_left > 0


# -- normalisation -------------------------------------------------------------- #

def test_unknown_modes_fall_back_to_queue():
    assert normalise("queue") == "queue"
    assert normalise("interrupt") == "interrupt"
    for odd in ("", None, "steer", "interupt", 7):
        assert normalise(odd) == "queue", f"{odd!r} must not become interrupt"


# -- queue (the default) ---------------------------------------------------------- #

def test_queue_refuses_exactly_as_before():
    session = FakeSession()
    refused: list[str] = []
    result = start_or_steer(session, "hello", None, "queue", refused.append)
    assert result.started is False
    assert refused == ["Something is already running. Stop it first."]
    assert not session.interrupted


# -- interrupt ------------------------------------------------------------------ #

def test_interrupt_cancels_and_starts_the_new_turn():
    session = FakeSession(release_after=0.05)
    refused: list[str] = []
    result = start_or_steer(session, "hello", None, "interrupt",
                            refused.append)
    assert result.started is True
    assert refused == []
    assert session.interrupted
    assert session.reason == "interrupt", "the stop must carry its reason"


def test_interrupt_that_cannot_start_says_so():
    session = FakeSession(busy_turns=99)
    refused: list[str] = []
    result = start_or_steer(session, "hello", None, "interrupt",
                            refused.append)
    assert result.started is False
    assert refused and "could not start" in refused[0]
    assert session.interrupted


# -- the stopped turn's note -------------------------------------------------------- #

def test_the_note_names_interrupt_and_checkpoints():
    note = interrupt_note({"reason": "interrupt"})
    assert "new message" in note
    assert "checkpoint" in note


def test_a_plain_stop_gets_no_note():
    assert interrupt_note({"reason": "stop"}) == ""
    assert interrupt_note({}) == ""
    assert interrupt_note(None) == ""


# -- live settings reach the mode -------------------------------------------------- #

def test_busy_mode_is_a_channel_setting_with_queue_default():
    from comodor.config import Config

    config = Config()
    assert config.telegram.busy_mode == "queue"
    assert config.whatsapp.busy_mode == "queue"
    assert config.slack.busy_mode == "queue"


def test_busy_mode_survives_a_save_and_load(tmp_path, monkeypatch):
    from comodor.config import load, save_user_config

    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    config = load(cwd=tmp_path / "work", use_environment=False)
    config.telegram.busy_mode = "interrupt"
    config.slack.busy_mode = "interrupt"
    save_user_config(config)

    again = load(cwd=tmp_path / "work", use_environment=False)
    assert again.telegram.busy_mode == "interrupt"
    assert again.slack.busy_mode == "interrupt"
    assert again.whatsapp.busy_mode == "queue", "channels are independent"


# -- a changed setting reaches a running bot ------------------------------------------- #

def test_the_watcher_picks_up_a_busy_mode_change(tmp_path, monkeypatch):
    from comodor.config import load, save_user_config

    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    config = load(cwd=tmp_path / "work", use_environment=False)
    config.telegram.token = "1:x"
    config.telegram.allowed = [7]
    save_user_config(config)
    running = load(cwd=tmp_path / "work", use_environment=False)

    service = _WatcherStub(running)
    config = load(cwd=tmp_path / "work", use_environment=False)
    config.telegram.busy_mode = "interrupt"
    save_user_config(config)

    keep_current(service)
    assert service.config.telegram.busy_mode == "interrupt"


class _WatcherStub:
    """Just enough of a channel service for keep_current."""

    def __init__(self, config):
        from comodor.channels.settings import Settings

        self.settings = Settings(config)
        self.config = config


# -- timing ------------------------------------------------------------------------ #

def test_the_settle_wait_is_short():
    assert SETTLE_SECONDS <= 3.0
    assert POLL_SECONDS < 0.5
