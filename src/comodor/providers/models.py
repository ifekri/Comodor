"""What a provider can actually run today.

The catalogue carries a handful of model names per provider, written by hand.
That is fine as a default for somebody who has not chosen — and wrong as the
list of what is available, which is what it was being used for. OpenRouter
alone publishes four hundred models and the catalogue named six of them, three
of which were a year old. Somebody picking from that list is picking from a
list of what was true when the file was edited.

So the list comes from the provider. Three things make that safe to do on a
path somebody is waiting on:

**No key needed, where none is needed.** OpenRouter and the local runtimes
publish their catalogues to anybody. That is the common case and it costs
nothing to ask.

**Cached, with the age visible.** A fetch per panel open would be rude to the
provider and slow for the user. The answer is kept on disk and re-used until
it is stale, and what is returned says when it was fetched — so a caller can
show "checked an hour ago" rather than implying it is live when it is not.

**Stale beats absent, and both beat invented.** If the network is down, the
cached list is served and marked stale. If there is no cache either, the
catalogue's hand-written names are served and marked as what they are: a
guess. Nothing here ever presents one as the other.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import catalogue

#: How long a fetched list is treated as current. Model catalogues change
#: daily at the fast-moving providers and never at the slow ones; six hours is
#: short enough to pick up a launch the same day and long enough that opening
#: a settings panel five times does not make five requests.
FRESH_FOR = 6 * 3600

#: The whole of the time budget for asking. This runs where somebody is
#: waiting, and a provider having a bad afternoon must not become Comodor
#: having one.
TIMEOUT = (4.0, 8.0)


@dataclass
class Model:
    """One model, as the provider describes it."""

    id: str
    name: str = ""
    context: int = 0
    #: The most it will write in one answer, where the provider says.
    max_output: int = 0
    #: Dollars per million tokens, in and out. Zero means free; None means the
    #: provider did not say, which is different and is not shown as free.
    input_cost: float | None = None
    output_cost: float | None = None
    #: Whether it can call a tool. The first question for an agent, not the
    #: second: a model without this does not give you a slower Comodor, it
    #: gives you one that cannot read a file.
    tools: bool | None = None
    #: Whether it can be shown a picture — what decides if screen control works.
    vision: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name or self.id,
                "context": self.context, "max_output": self.max_output,
                "input_cost": self.input_cost, "output_cost": self.output_cost,
                "tools": self.tools, "vision": self.vision}


@dataclass
class Listing:
    """What was found, and how much to trust it."""

    provider: str
    models: list[Model] = field(default_factory=list)
    #: "live" — asked just now. "cached" — asked recently, re-used.
    #: "stale" — the cache is old and the provider could not be reached.
    #: "catalogue" — nobody could be asked, so these are the built-in names.
    source: str = "catalogue"
    fetched_at: float = 0.0
    error: str = ""

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at) if self.fetched_at else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "models": [model.as_dict() for model in self.models],
            "source": self.source,
            "fetched_at": self.fetched_at,
            "age_seconds": round(self.age_seconds),
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# asking
# --------------------------------------------------------------------------- #


def listing(provider: str, api_key: str = "", base_url: str = "",
            cache_root: Path | None = None, refresh: bool = False) -> Listing:
    """Every model this provider offers, from the provider where possible."""
    spec = catalogue.get(provider)
    endpoint = base_url or (spec.base_url if spec else "")

    cached = _read_cache(provider, cache_root)
    if cached and not refresh and cached.age_seconds < FRESH_FOR:
        cached.source = "cached"
        return cached

    fetched, why = _ask(provider, endpoint, api_key)
    if fetched:
        found = Listing(provider=provider, models=fetched, source="live",
                        fetched_at=time.time())
        _write_cache(found, cache_root)
        return found

    if cached:
        # Old, and still the truth as of when it was asked. Said to be old.
        cached.source = "stale"
        cached.error = why
        return cached

    return Listing(provider=provider, source="catalogue", error=why,
                   models=[Model(id=name) for name in (spec.models if spec else ())])


def _ask(provider: str, base_url: str, api_key: str) -> tuple[list[Model], str]:
    """One request, or a reason there is no answer."""
    if not base_url:
        return [], "that provider has no endpoint to ask"

    from ..net import http

    url = f"{base_url.rstrip('/')}/models"
    headers: dict[str, str] = {}
    if api_key:
        # Anthropic wants its own header; everything else here is
        # OpenAI-compatible and takes a bearer token.
        if provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    session = http.Session()
    try:
        response = session.get(url, headers=headers, timeout=TIMEOUT)
        if response.status_code == 401 or response.status_code == 403:
            return [], "that key was refused"
        if response.status_code >= 400:
            return [], f"the provider answered {response.status_code}"
        payload = response.json()
    except Exception as error:
        return [], f"{type(error).__name__}"
    finally:
        try:
            session.close()
        except Exception:
            pass

    models = _parse(payload)
    return (models, "") if models else ([], "the provider listed nothing")


def _parse(payload: Any) -> list[Model]:
    """Read the shapes the providers actually send.

    OpenAI's `{"data": [{"id": ...}]}` is the common one. OpenRouter uses it
    and adds `name`, `context_length` and `pricing`. Anthropic sends
    `display_name`. Anything unrecognised still yields its ids, because an id
    is the only field that is required to be useful.
    """
    entries = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    models: list[Model] = []
    for entry in entries:
        if isinstance(entry, str):
            models.append(Model(id=entry))
            continue
        if not isinstance(entry, dict):
            continue
        identifier = str(entry.get("id") or entry.get("name") or "").strip()
        if not identifier:
            continue
        pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
        top = entry.get("top_provider") if isinstance(entry.get("top_provider"), dict) else {}
        shape = entry.get("architecture") if isinstance(entry.get("architecture"), dict) else {}
        parameters = entry.get("supported_parameters")

        # `None` rather than `False` where the provider said nothing. "It
        # cannot do this" and "nobody told us" are different, and only one of
        # them is worth warning somebody about.
        tools = None
        if isinstance(parameters, list):
            tools = "tools" in parameters
        modalities = shape.get("input_modalities")
        vision = "image" in modalities if isinstance(modalities, list) else None

        models.append(Model(
            id=identifier,
            name=str(entry.get("name") or entry.get("display_name") or ""),
            context=_as_int(entry.get("context_length")
                            or entry.get("context_window")
                            or top.get("context_length")),
            max_output=_as_int(top.get("max_completion_tokens")
                               or entry.get("max_output_tokens")),
            input_cost=_per_million(pricing.get("prompt")),
            output_cost=_per_million(pricing.get("completion")),
            tools=tools,
            vision=vision,
        ))

    # Sorted by id, case-insensitively, and by the parts around the slash so
    # `anthropic/claude-opus-5` and `anthropic/claude-sonnet-5` sit together
    # rather than wherever byte order puts a capital letter.
    models.sort(key=lambda model: [part.lower() for part in model.id.split("/")])
    return models


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _per_million(value: Any) -> float | None:
    """Providers quote per token; people think per million.

    `None` rather than `0.0` when nothing was quoted: a model whose price is
    unknown and a model that is free are different facts, and showing the
    first as the second is the kind of small lie that costs somebody money.
    """
    if value is None or value == "":
        return None
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# keeping the answer
# --------------------------------------------------------------------------- #


def _cache_file(provider: str, cache_root: Path | None) -> Path | None:
    if cache_root is None:
        return None
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in provider)
    return Path(cache_root) / "cache" / f"models-{safe}.json"


def _read_cache(provider: str, cache_root: Path | None) -> Listing | None:
    path = _cache_file(provider, cache_root)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Listing(
            provider=provider,
            models=[Model(**entry) for entry in payload.get("models", [])],
            fetched_at=float(payload.get("fetched_at") or 0.0),
        )
    except Exception:
        # A half-written or hand-edited cache is a cache to ignore, never a
        # reason to fail: this is on the path to a settings panel.
        return None


def _write_cache(found: Listing, cache_root: Path | None) -> None:
    path = _cache_file(found.provider, cache_root)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "fetched_at": found.fetched_at,
            "models": [model.as_dict() for model in found.models],
        }), encoding="utf-8")
    except OSError:
        pass
