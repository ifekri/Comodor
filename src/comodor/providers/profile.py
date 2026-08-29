"""What the model in front of us can actually do.

Comodor sends every model the same thing: sixteen tool schemas, an instruction
to call tools in parallel, and a context gauge that reads a million tokens.
That is right for Sonnet and wrong for a seven-billion-parameter model on
somebody's laptop, and the second case is the one the project claims to serve.

`ModelInfo.supports_tools` and `supports_vision` have been in the registry all
along and nothing has ever read them.

The consequential field is the window. `agent.context_limit` defaults to a
million, and `_maybe_compact` falls back to 128k when it is unset — **neither
number has anything to do with the model**. Point Comodor at a 32k local model
and compaction never fires: the conversation grows past what the model can
read, and the first sign of it is the provider refusing the request. The fix is
not a better default, it is asking.

Three places are asked, in order of how much they can be trusted:

1. **The built-in registry**, when it has real facts. `registry.knows` exists
   precisely to separate those from the safe defaults `lookup` invents.
2. **The provider's own catalogue**, from the cache on disk. OpenRouter and the
   local runtimes publish a window per model and it has already been fetched
   for the model picker. Nothing here goes to the network — a turn is not the
   place to wait on somebody's API.
3. **What the user configured**, which is the last word if they set it and the
   only answer if nobody else has one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import registry

#: Below this a model cannot hold a system prompt, a tool set and a
#: conversation at once, and a "limit" that small is far likelier to be a
#: mis-parsed catalogue entry than a real window.
IMPLAUSIBLE = 2_000

#: Where a model is small enough that the full tool set is a large fraction of
#: what it can read before the conversation starts.
CRAMPED = 40_000


@dataclass(frozen=True)
class Profile:
    """What to send this model, and what not to."""

    model: str
    #: Tokens it can read in one request. Never zero.
    context: int
    #: Where that number came from: registry | provider | configured.
    source: str
    #: Whether it can be asked for several tool calls in one turn.
    parallel_tools: bool = True
    #: Whether an image may be attached.
    vision: bool = False
    #: Whether it can use tools at all. A model that cannot is not usable for
    #: coding, and saying so at the point of choosing beats finding out on the
    #: sixth turn of a task.
    tools: bool = True

    @property
    def cramped(self) -> bool:
        return self.context < CRAMPED


def of(config: Any, cache_root: Path | None = None) -> Profile:
    """The profile for whatever this config is pointed at."""
    model = getattr(config, "model", "") or ""
    configured = int(getattr(config.agent, "context_limit", 0) or 0)

    info = registry.lookup(model)
    known = registry.knows(model)

    context, source = _window(config, model, configured, info, known, cache_root)

    return Profile(
        model=model,
        context=context,
        source=source,
        # Only claimed where it is known. Assuming a model we have never heard
        # of can field six calls at once is how a local runtime returns one
        # malformed blob and the turn is wasted.
        parallel_tools=bool(known and info.supports_tools),
        vision=bool(known and info.supports_vision),
        tools=bool(info.supports_tools) if known else True,
    )


def _window(config: Any, model: str, configured: int, info: Any, known: bool,
            cache_root: Path | None) -> tuple[int, str]:
    """The window to work to, and where the number came from.

    Where two sources disagree the **smaller** wins. Compacting sooner than
    strictly necessary costs a summary; compacting later than the model can
    bear costs the turn, and the error that reports it does not say what
    happened.
    """
    candidates: list[tuple[int, str]] = []
    if known and info.context:
        candidates.append((int(info.context), "registry"))

    from_provider = _from_catalogue(config, model, cache_root)
    if from_provider:
        candidates.append((from_provider, "provider"))

    if configured >= IMPLAUSIBLE:
        candidates.append((configured, "configured"))

    if not candidates:
        # Nobody knows, and the configured number was either unset or too small
        # to be real — it did not reach the list above. Falling back to it here
        # would reinstate the very value that was rejected, so the registry's
        # own default stands instead.
        return (int(registry.DEFAULT_CONTEXT), "configured")

    return min(candidates, key=lambda pair: pair[0])


def _from_catalogue(config: Any, model: str, cache_root: Path | None) -> int:
    """The window the provider published, from the cache and never the network.

    A turn is not the place to wait on somebody's API, and the model picker has
    usually filled this in already.
    """
    if not model:
        return 0
    provider = getattr(config, "provider", "") or ""
    if not provider:
        return 0

    root = cache_root
    if root is None:
        paths = getattr(config, "paths", None)
        root = getattr(paths, "user", None) if paths is not None else None
    if root is None:
        return 0

    try:
        from . import models as catalogue

        cached = catalogue._read_cache(provider, Path(root))
        if cached is None:
            return 0
        wanted = model.strip().lower()
        for entry in cached.models:
            if str(entry.id).strip().lower() == wanted and entry.context:
                return int(entry.context)
    except Exception:
        # A cache is a convenience. Failing to read one must never be the
        # reason a turn does not happen.
        return 0
    return 0
