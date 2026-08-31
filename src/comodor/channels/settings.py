"""Letting a running bot notice that its settings changed.

A channel bot is a detached process. It loads the configuration once at start
and, until now, never looked again — so every setting changed while it was
running had no effect on it, and the command that changed the setting said it
had worked.

The one people hit is `allow_writes`:

    $ comodor telegram writes on
     Writes are on
     Turns started from Telegram may now edit files and run commands.

They were not. The bot was still holding the configuration it started with, so
tapping **Act** in the chat went on being refused — with a message telling the
user to run the command they had just run. Nothing about it looked like a bug
from either side, which is why it survived.

It is fixed here rather than in each bot because all three have it, and because
the next setting somebody changes from the web panel would have the same
problem.

**How.** The file's modification time is checked before each update is handled,
and the configuration is reloaded only when it has moved. A `stat` per message
is nothing; a reload is rare. `Config.save` writes through a temporary file and
renames it, so a reload can never see half a file.

**What is not replaced.** Only the configuration. The conversations, the
sockets and everything else the bot is holding are untouched — this answers
"what am I allowed to do" and nothing else.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ..config import Config


class Settings:
    """A configuration that notices when its file changes underneath it."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._path = Path(config.paths.config_file)
        self._seen = self._stamp()
        self._lock = threading.Lock()
        #: How many times it has actually reloaded. Read by the tests, and by
        #: anyone wondering whether this is doing anything.
        self.reloads = 0

    @property
    def config(self) -> Config:
        return self._config

    def _stamp(self) -> tuple[float, int]:
        """Modification time and size. Two fields because a file can be
        rewritten within the same clock tick, and a size change is the cheap
        way to notice that."""
        try:
            info = self._path.stat()
        except OSError:
            return (0.0, 0)
        return (info.st_mtime, info.st_size)

    def _readable(self) -> bool:
        """Whether the file is there and is still JSON.

        `load` does not answer this. It is built for startup, where a broken
        file must not stop the program, so it falls back to defaults and says
        nothing. At startup that is right — there is nothing better to fall
        back to. Here there is: the configuration the bot is already running
        on. Accepting `load`'s defaults would drop the token and empty the
        allowed list, which locks the owner out of their own bot, mid
        conversation, because of a stray comma in a file they were editing.
        """
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(document, dict)

    def current(self) -> Config:
        """The configuration as the file now says, reloading if it moved.

        Never raises. A configuration file that has been broken by hand is a
        reason to keep running on the last good one, not a reason for the bot
        to fall over — the person editing it is not the person in the chat.
        """
        stamp = self._stamp()
        if stamp == self._seen:
            return self._config

        with self._lock:
            # Checked again inside the lock: two updates arriving together
            # would otherwise both reload.
            if stamp == self._seen:
                return self._config
            # Taken before the read either way. A file that is broken now stays
            # broken until it is next written, and re-reading it on every
            # message would be a read per message for as long as it takes
            # somebody to notice their typo.
            self._seen = stamp
            if not self._readable():
                return self._config
            try:
                from ..config import load

                fresh = load(cwd=Path(self._config.paths.project))
            except Exception:
                return self._config

            self._config = fresh
            self.reloads += 1
            return self._config


def keep_current(service: Any) -> Config:
    """The freshest configuration for a service, whatever it was built with.

    Services hold `self.config` directly and there are three of them, so this
    is the one line each has to call. A service built before this existed, or
    one in a test, has no watcher and simply gets what it had.
    """
    watcher = getattr(service, "settings", None)
    if watcher is None:
        return service.config
    fresh = watcher.current()
    if fresh is not service.config:
        service.config = fresh
    return fresh
