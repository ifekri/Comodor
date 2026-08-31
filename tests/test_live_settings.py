"""A running bot noticing that its settings changed.

The bug, reported from Telegram: no matter how many times you tap **Act**, it
stays off.

It was not the button. `comodor telegram writes on` writes `allow_writes: true`
to the configuration file and prints "Turns started from Telegram may now edit
files and run commands" — but the bot is a detached process holding the
configuration it started with. It went on refusing Act, with a message telling
the user to run the command they had just run. Nothing about it looked like a
bug from either end, which is why it lasted.

All three channels had it, and it was never only about `allow_writes`: every
setting changed from the terminal or the web panel while a bot was running was
invisible to that bot.
"""

from __future__ import annotations

import json

import pytest

from comodor.channels.settings import Settings, keep_current
from comodor.config import Config, Paths, load


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """A real configuration on disk, loaded the way a daemon loads it.

    `load()` resolves its own paths and ignores any handed to `Config`, so the
    home has to be set through the environment or this writes to the real one.
    """
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("COMODOR_HOME", str(home))

    first = Config(paths=Paths(user=home, project=work))
    first.telegram.token = "123:abc"
    first.telegram.allowed = [7]
    first.telegram.allow_writes = False
    first.save()

    config = load(cwd=work, use_environment=False)
    # These tests write to, break and delete the file they are given. If it is
    # ever not the temporary one, they must not run at all.
    assert tmp_path in config.paths.config_file.parents, \
        f"not isolated: {config.paths.config_file}"
    return config


def turn_writes_on(config: Config) -> None:
    """What `comodor telegram writes on` does, from another process."""
    fresh = load(cwd=config.paths.project, use_environment=False)
    fresh.telegram.allow_writes = True
    fresh.save()


# --------------------------------------------------------------------------- #
# the bug
# --------------------------------------------------------------------------- #


def test_a_change_on_disk_reaches_a_running_service(saved):
    watcher = Settings(saved)

    assert watcher.current().telegram.allow_writes is False
    turn_writes_on(saved)

    assert watcher.current().telegram.allow_writes is True
    assert watcher.reloads == 1


def test_the_service_object_itself_is_updated(saved):
    class Bot:
        def __init__(self, config):
            self.config = config
            self.settings = Settings(config)

    bot = Bot(saved)
    turn_writes_on(saved)
    keep_current(bot)

    assert bot.config.telegram.allow_writes is True, \
        "the service is still holding what it started with"


def test_act_stops_being_refused_once_writes_are_on(saved):
    """The reported symptom, end to end: the same check that refused Act now
    permits it, without the process restarting."""
    from comodor.telegram.bot import Service

    service = Service(saved, bot=object())
    assert service.config.telegram.allow_writes is False

    turn_writes_on(saved)
    keep_current(service)

    assert service.config.telegram.allow_writes is True


# --------------------------------------------------------------------------- #
# and what it must not do
# --------------------------------------------------------------------------- #


def test_an_untouched_file_is_not_reloaded(saved):
    """A `stat` per message is nothing. A full load per message is not."""
    watcher = Settings(saved)

    for _ in range(50):
        watcher.current()

    assert watcher.reloads == 0


def test_the_same_object_comes_back_when_nothing_changed(saved):
    watcher = Settings(saved)

    assert watcher.current() is watcher.current()


def test_a_broken_file_leaves_the_last_good_one_in_place(saved):
    """The person editing the file by hand is not the person in the chat."""
    watcher = Settings(saved)
    saved.paths.config_file.write_text("{ not json", encoding="utf-8")

    kept = watcher.current()

    assert kept.telegram.token == "123:abc"
    assert watcher.reloads == 0


def test_a_deleted_file_leaves_the_last_good_one_in_place(saved):
    watcher = Settings(saved)
    saved.paths.config_file.unlink()

    assert watcher.current().telegram.token == "123:abc"


def test_a_service_with_no_watcher_still_works(saved):
    """Every test in the suite builds services directly, and so does the ACP
    agent. Nothing may require the watcher to exist."""
    class Old:
        def __init__(self, config):
            self.config = config

    bare = Old(saved)

    assert keep_current(bare) is saved


def test_a_rewrite_within_the_same_second_is_still_noticed(saved):
    """Modification time has one-second resolution on some filesystems, so
    size is checked as well — two settings toggled quickly must not be missed."""
    watcher = Settings(saved)
    path = saved.paths.config_file

    document = json.loads(path.read_text(encoding="utf-8"))
    document.setdefault("telegram", {})["allow_writes"] = True
    document["telegram"]["pair_window"] = 999
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    assert watcher.current().telegram.allow_writes is True


# --------------------------------------------------------------------------- #
# every channel, not just the one that was reported
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module,builder", [
    ("comodor.telegram.bot", "telegram"),
    ("comodor.slack.bot", "slack"),
    ("comodor.whatsapp.bot", "whatsapp"),
])
def test_every_channel_service_watches_its_settings(module, builder):
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module).Service)

    assert "Settings(config)" in source, f"{builder} does not watch its file"
    assert "keep_current(self)" in source, \
        f"{builder} watches the file and never asks it"
