"""Turning write access off, for the chats that are already using it.

The live-settings watcher fixed half of this: a running bot now notices that
`allow_writes` changed. What it did not do was reach the conversations already
open. Each one holds a `Session` built with the `Config` the bot started with,
and the only place the setting was consulted was where a conversation is
*made* — so a chat that had already entered Act stayed in Act, and its next
turn could still edit files and run commands.

That is the wrong way round. Somebody turns write access off precisely because
something is going wrong, and the chats it took effect on were the ones that
had never used it. The reported finding:

    When writes off is saved after a chat has entered Act mode, this only
    replaces the service's configuration. Each existing Conversation retains a
    Session built with the previous Config and remains in Act, while subsequent
    turns do not recheck allow_writes.

These tests drive the real services against a real configuration file, changed
the way the terminal changes it — from another `load`, in another process's
shape — because the bug lived exactly in the gap between those two objects.
"""

from __future__ import annotations

import pytest

from comodor.channels.settings import hold_the_line, keep_current
from comodor.config import Config, Paths, load


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """A configuration on disk with writes on, loaded as a daemon loads it."""
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("COMODOR_HOME", str(home))

    first = Config(paths=Paths(user=home, project=work))
    first.telegram.token = "123:abc"
    first.telegram.allowed = [7]
    first.telegram.allow_writes = True
    first.slack.bot_token = "xoxb-1"
    first.slack.allowed = ["U1"]
    first.slack.allow_writes = True
    first.whatsapp.token = "wa"
    first.whatsapp.phone_number_id = "1"
    first.whatsapp.allowed = ["15550001111"]
    first.whatsapp.allow_writes = True
    first.discord.token = "a.b.c"
    first.discord.allowed = [9]
    first.discord.allow_writes = True
    first.save()

    config = load(cwd=work, use_environment=False)
    # These tests write to the file they are given. If it is ever not the
    # temporary one, they must not run at all.
    assert tmp_path in config.paths.config_file.parents, \
        f"not isolated: {config.paths.config_file}"
    return config


def turn_writes_off(config: Config, section: str) -> None:
    """What `comodor <channel> writes off` does, from another process."""
    fresh = load(cwd=config.paths.project, use_environment=False)
    getattr(fresh, section).allow_writes = False
    fresh.save()


# --------------------------------------------------------------------------- #
# the finding, on the channel it was reported against
# --------------------------------------------------------------------------- #


def test_a_chat_already_in_act_is_moved_back_when_writes_are_revoked(saved):
    from comodor.telegram.bot import Service

    service = Service(saved, bot=_Mute())
    talk = service._conversation(4242)
    talk.session.set_mode("act")
    assert talk.session.config.agent.mode == "act"

    turn_writes_off(saved, "telegram")
    keep_current(service)

    again = service._conversation(4242)

    assert again is talk, "a new conversation would hide the bug, not fix it"
    assert again.session.config.agent.mode == "plan", \
        "the chat kept Act after write access was taken away"


def test_the_person_is_told_rather_than_left_to_discover_it(saved):
    """A mode that changes underneath somebody with no explanation reads as
    the bot ignoring them — which is the bug the live-settings work fixed."""
    from comodor.telegram.bot import Service

    bot = _Mute()
    service = Service(saved, bot=bot)
    service._conversation(4242).session.set_mode("act")

    turn_writes_off(saved, "telegram")
    keep_current(service)
    service._conversation(4242)

    said = " ".join(text for _, text in bot.sent)
    assert "plan mode" in said, "the mode changed and nothing said so"
    assert "turned off" in said, "it never says why"


def test_saying_so_may_fail_without_costing_the_revocation(saved):
    """The notice is worth having and the revocation is worth more. A send
    that raises must not put the chat back where it was."""
    from comodor.telegram.bot import Service

    class Broken(_Mute):
        def send(self, *args, **kwargs):
            raise RuntimeError("Telegram is unreachable")

    service = Service(saved, bot=Broken())
    talk = service._conversation(4242)
    talk.session.set_mode("act")

    turn_writes_off(saved, "telegram")
    keep_current(service)

    assert service._conversation(4242).session.config.agent.mode == "plan"


def test_a_chat_already_in_plan_is_left_alone_and_says_nothing(saved):
    """Nothing changed for it, so there is nothing to announce.

    Worth stating that `agent.mode` defaults to `act`: a chat that has never
    touched the mode buttons is in Act, not out of it, so this has to put it
    in plan deliberately to be the case it claims to be."""
    from comodor.telegram.bot import Service

    bot = _Mute()
    service = Service(saved, bot=bot)
    service._conversation(4242).session.set_mode("plan")

    turn_writes_off(saved, "telegram")
    keep_current(service)
    bot.sent.clear()
    service._conversation(4242)

    assert bot.sent == [], "it announced a change that did not happen"


def test_a_chat_left_on_the_default_is_revoked_like_any_other(saved):
    """`agent.mode` defaults to `act`, so most chats reach the revocation
    without anybody having pressed anything. That is the common case, not the
    edge one."""
    from comodor.telegram.bot import Service

    service = Service(saved, bot=_Mute())
    talk = service._conversation(4242)
    assert talk.session.config.agent.mode == "act", "the default moved"

    turn_writes_off(saved, "telegram")
    keep_current(service)

    assert service._conversation(4242).session.config.agent.mode == "plan"


def test_writes_still_on_leaves_act_alone(saved):
    """The recheck runs on every fetch. It must only ever fire on revocation,
    or Act becomes unusable."""
    from comodor.telegram.bot import Service

    service = Service(saved, bot=_Mute())
    talk = service._conversation(4242)
    talk.session.set_mode("act")

    for _ in range(5):
        service._conversation(4242)

    assert talk.session.config.agent.mode == "act"


# --------------------------------------------------------------------------- #
# and the same on the other three, because all four had it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("section", ["telegram", "slack", "whatsapp",
                                     "discord"])
def test_the_recheck_moves_a_session_out_of_act(saved, section):
    """`hold_the_line` itself, against each channel's settings block."""
    from comodor.web.session import Session

    talk = _Talk(Session(saved))
    talk.session.set_mode("act")

    turn_writes_off(saved, section)
    fresh = load(cwd=saved.paths.project, use_environment=False)

    moved = hold_the_line(fresh, section, talk)

    assert moved is True
    assert talk.session.config.agent.mode == "plan"
    talk.session.close()


@pytest.mark.parametrize("module", ["comodor.telegram.bot", "comodor.slack.bot",
                                    "comodor.whatsapp.bot",
                                    "comodor.discord.bot"])
def test_every_channel_rechecks_where_it_hands_out_a_conversation(module):
    """Checked against the source: the call has to be in `_conversation`, not
    beside it. Every one of these built the gate into the branch that makes a
    new conversation, which is the one case that was never the problem."""
    import importlib
    import inspect

    service = importlib.import_module(module).Service
    source = inspect.getsource(service._conversation)

    assert "hold_the_line(" in source, \
        f"{module} still only checks writes when the conversation is made"


def test_a_recheck_that_raises_costs_the_notice_not_the_turn(saved):
    """Anything reached through `getattr` here can be missing or broken in a
    way this must survive: it is on the path of every single message."""
    class Exploding:
        @property
        def session(self):
            raise RuntimeError("boom")

    assert hold_the_line(saved, "telegram", Exploding()) is False


def test_an_unknown_section_is_not_an_error(saved):
    assert hold_the_line(saved, "carrier-pigeon", _Talk(None)) is False


class _Mute:
    """A bot that records what it was asked to send and sends nothing."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send(self, chat, text, **kwargs):
        self.sent.append((chat, text))
        return {"message_id": len(self.sent)}

    def typing(self, *args, **kwargs) -> None:
        pass

    def answer_callback(self, *args, **kwargs) -> None:
        pass


class _Talk:
    """The one attribute `hold_the_line` reaches for."""

    def __init__(self, session) -> None:
        self.session = session
