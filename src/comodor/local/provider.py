"""The bridge between a downloaded file and the rest of Comodor.

Almost nothing happens here, which is the point. A llama.cpp server speaks the
OpenAI API, so :class:`OpenAICompatProvider` already knows how to drive one —
all that is missing is somebody to start it and say which port it landed on.

The one real decision is *when*. Loading a four-gigabyte model takes seconds to
tens of seconds, and doing it in ``build_provider`` would mean every
``comodor`` invocation sat at a blank screen before printing anything, whether
or not the person was about to ask the model anything at all. So the server
starts on the first request instead, and the interface is told what is
happening while it loads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from ..providers.base import Message, StreamEvent, ToolSpec
from ..providers.openai_compat import OpenAICompatProvider
from . import Runner, RuntimeFailed, RuntimeMissing, load, store_for


class LocalProvider:
    """A model on this machine, started when it is first needed."""

    kind = "local"

    def __init__(self, name: str = "local", model: str = "",
                 user_dir: Path | None = None, label: str = "Local",
                 timeout: float = 600.0, runner: Runner | None = None,
                 on_loading: Any = None) -> None:
        self.name = name
        self.model = model
        self.label = label
        self.timeout = timeout
        self.user_dir = Path(user_dir) if user_dir else None
        self._runner = runner or Runner()
        self._inner: OpenAICompatProvider | None = None
        #: Called once with the model's name when a load actually begins, so an
        #: interface can say "loading Qwen2.5 Coder 7B…" rather than appearing
        #: to hang. Not called when the server is already up.
        self.on_loading = on_loading

    # -- the part that does the work -------------------------------------- #

    def _ready(self) -> OpenAICompatProvider:
        """Make sure a server is up, and return something pointed at it."""
        running = self._runner.running
        if self._inner is not None and running is not None:
            running.touch()
            return self._inner

        if not self.model:
            raise RuntimeFailed(
                "no local model is selected — `comodor local list` shows what "
                "is downloaded")

        catalogue = load(self.user_dir, allow_network=False)
        model = catalogue.get(self.model)
        if model is None:
            raise RuntimeFailed(
                f"{self.model!r} is not in the model list. It may have been "
                f"removed from the catalogue; `comodor local list` shows what "
                f"is available.")

        store = store_for(self.user_dir) if self.user_dir else None
        if store is None:
            raise RuntimeFailed("there is nowhere to look for model files")
        held = store.have(model)
        if held is None:
            raise RuntimeFailed(
                f"{model.name} is not downloaded — `comodor local get "
                f"{model.id}` fetches it")
        if not held.complete:
            raise RuntimeFailed(
                f"{model.name} is only partly downloaded — `comodor local get "
                f"{model.id}` continues it")

        if self.on_loading is not None:
            try:
                self.on_loading(model)
            except Exception:
                pass

        server = self._runner.serve(model, held.path)
        self._inner = OpenAICompatProvider(
            name=self.name,
            base_url=server.base_url,
            # llama.cpp does not check one, and OpenAI clients insist on
            # sending something.
            api_key="local",
            model=model.id,
            timeout=self.timeout,
            label=self.label,
        )
        return self._inner

    # -- the provider surface --------------------------------------------- #

    def stream(self, messages: list[Message], *, tools: list[ToolSpec] | None = None,
               **kwargs: Any) -> Iterator[StreamEvent]:
        return self._ready().stream(messages, tools=tools, **kwargs)

    def list_models(self) -> list[str]:
        """What is downloaded, not what could be.

        Deliberately different from every other provider, where the list is
        what the vendor offers. Here a model that is not on the disk cannot be
        selected, so listing one would offer a choice that fails.
        """
        if self.user_dir is None:
            return []
        try:
            catalogue = load(self.user_dir, allow_network=False)
        except Exception:
            return []
        store = store_for(self.user_dir)
        return [held.model.id for held in store.everything(catalogue)
                if held.complete]

    def close(self) -> None:
        """Give the memory back.

        A 7B model is several gigabytes of resident set. Leaving it behind
        because a session ended is the kind of thing people notice an hour
        later when something else will not start.
        """
        if self._inner is not None:
            try:
                self._inner.close()
            except Exception:
                pass
            self._inner = None
        self._runner.stop()


def build(entry: Any, user_dir: Path | None = None,
          on_loading: Any = None) -> LocalProvider:
    """Make one from a configured provider entry."""
    return LocalProvider(
        name=entry.name or "local",
        model=entry.model,
        user_dir=user_dir,
        label=entry.display if hasattr(entry, "display") else "Local",
        timeout=getattr(entry, "timeout", 600.0),
        on_loading=on_loading,
    )


__all__ = ["LocalProvider", "RuntimeFailed", "RuntimeMissing", "build"]
