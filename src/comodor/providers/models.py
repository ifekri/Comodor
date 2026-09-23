"""What a provider can actually run today.

The catalogue carries a handful of model names per provider, written by hand.
That is fine as a starting hint for somebody who has not chosen — and wrong as
the list of what is available, which is what it was being used for. OpenRouter
alone publishes four hundred models and the catalogue named six of them, three
of which were a year old. Somebody picking from that list is picking from a
list of what was true when the file was edited.

So the list comes from the provider. Five things make that safe to do on a path
somebody is waiting on:

**No key needed, where none is needed.** OpenRouter and the local runtimes
publish their catalogues to anybody. That is the common case and it costs
nothing to ask.

**The request carries what the provider's own requests carry.** Authentication
and any configured extra headers (tenant, workspace, routing) travel with the
``/models`` call, so an endpoint that needs them is not a provider that
"generates but cannot list".

**Cached, with the age visible.** A fetch per panel open would be rude to the
provider and slow for the user. The answer is kept on disk and re-used until it
is stale, and what is returned says when it was fetched — so a caller can show
"checked an hour ago" rather than implying it is live when it is not.

**Stale beats absent, and absent beats invented.** If the network is down, the
cached list is served and marked stale. If there is no cache either, nothing is
served as availability: the caller gets an empty list, the reason, and a small
hand-written *fallback hint* kept deliberately separate and labelled unverified.
A static list is never presented as the provider's current models. An
*incomplete* listing — a paginated walk that did not finish — is not
authoritative either, and is never cached as if it were.

**A cache belongs to one endpoint and one credential.** The cache identity is
the provider, its normalized base URL, *and* a non-reversible fingerprint of the
effective credential/header scope. Two accounts behind one endpoint can see
different models, so account A's list must not be served to account B. Only a
bounded digest is kept; no key, token or header value is ever stored or logged.
"""

from __future__ import annotations

import hashlib
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

#: Pagination guards. A provider that never says "that is all" must not hang
#: the picker, so the loop is bounded by pages and by models and every request
#: carries its own timeout. Reaching a bound is *not* a complete listing.
MAX_PAGES = 10
MAX_MODELS = 1000
PAGE_LIMIT = 100

#: Application headers a provider's own adapter sends on every request. A
#: ``/models`` request must carry them too: a provider that attributes or
#: routes on them would otherwise list nothing while generation still worked.
#: The values match the adapter's own defaults; this is the one source both
#: read.
_APP_HEADERS: dict[str, dict[str, str]] = {
    "openrouter": {"HTTP-Referer": "https://github.com/ifekri/comodor",
                   "X-Title": "Comodor"},
}


def app_headers(provider: str) -> dict[str, str]:
    """The provider's own application headers, by provider id."""
    return dict(_APP_HEADERS.get(provider, {}))


@dataclass
class Model:
    """One model, as the provider describes it.

    Every field but `id` may be unknown: the provider is not required to tell
    us a window, a price or a capability, and "it did not say" is `None` (or
    zero), never a confident `False` or `0.0`.
    """

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
    #: gives you one that cannot read a file. `None` when nobody said.
    tools: bool | None = None
    #: Whether it can be shown a picture — what decides if screen control works.
    vision: bool | None = None
    #: "" unknown | "agent" | "other". Set only from structured type metadata
    #: (e.g. OpenRouter's output modalities); never inferred from the name.
    category: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name or self.id,
                "context": self.context, "max_output": self.max_output,
                "input_cost": self.input_cost, "output_cost": self.output_cost,
                "tools": self.tools, "vision": self.vision,
                "category": self.category}


@dataclass
class Listing:
    """What was found, and how much to trust it."""

    provider: str
    models: list[Model] = field(default_factory=list)
    #: "live" — asked just now, and the walk finished. "cached" — asked
    #: recently, re-used. "stale" — the cache is old and the provider could not
    #: be reached, or the walk did not finish. "unavailable" — nothing could be
    #: asked and there is no cache; `models` is empty and `fallback` carries an
    #: unverified onboarding hint.
    source: str = "unavailable"
    fetched_at: float = 0.0
    error: str = ""
    #: The normalized base URL this listing was fetched from.
    endpoint: str = ""
    #: A small, hand-written hint, offered only when nothing could be asked.
    #: It is **not** availability and must be labelled as unverified wherever
    #: it is shown.
    fallback: list[str] = field(default_factory=list)

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at) if self.fetched_at else 0.0

    @property
    def agent_models(self) -> list[Model]:
        """The agent-facing set: everything whose type is not "not an agent".

        A model whose type is unknown stays: "we do not know" is not a reason
        to hide something the provider says is available. Only structured
        metadata that says the model is not a text/agent model removes it.
        """
        return [model for model in self.models if model.category != "other"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            # The picker set: a caller that offers models to an agent gets the
            # agent-facing set. The full listing is still here for diagnostics.
            "models": [model.as_dict() for model in self.agent_models],
            "all_models": [model.as_dict() for model in self.models],
            "source": self.source,
            "fetched_at": self.fetched_at,
            "age_seconds": round(self.age_seconds),
            "error": self.error,
            "endpoint": self.endpoint,
            "fallback": list(self.fallback),
        }


# --------------------------------------------------------------------------- #
# asking
# --------------------------------------------------------------------------- #


def endpoint_of(provider: str, base_url: str = "") -> str:
    """The provider's effective endpoint, normalized for cache identity."""
    spec = catalogue.get(provider)
    raw = base_url or (spec.base_url if spec else "")
    return (raw or "").strip().rstrip("/")


def effective_headers(provider: str, api_key: str = "",
                      extra: dict[str, str] | None = None) -> dict[str, str]:
    """The headers a discovery request carries, merged one way.

    Authentication first, then the provider's own application headers, then the
    configured extra headers (which win). Header names are compared
    case-insensitively by HTTP, so a custom header may not silently duplicate an
    authentication header under a different case. No value is logged.
    """
    headers: dict[str, str] = {}
    if api_key:
        if provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    headers.update(app_headers(provider))
    for name, value in (extra or {}).items():
        if name and value is not None:
            headers[str(name)] = str(value)
    return headers


def auth_scope(headers: dict[str, str] | None) -> str:
    """A non-reversible fingerprint of the credential/header scope.

    Availability depends on who is asking: two accounts behind one endpoint can
    see different models, so the cache must not carry one account's list into
    another. Only a bounded SHA-256 digest is kept — never a raw key, token or
    header value — and header order does not change the identity.
    """
    if not headers:
        return "public"
    material = "\n".join(f"{str(name).lower()}\u0000{headers[name]}"
                         for name in sorted(headers, key=lambda n: str(n).lower()))
    return hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:16]


def scope_for(provider: str, api_key: str = "",
              headers: dict[str, str] | None = None) -> str:
    """The cache scope for one provider and credential/header set."""
    return auth_scope(effective_headers(provider, api_key, headers))


def listing(provider: str, api_key: str = "", base_url: str = "",
            cache_root: Path | None = None, refresh: bool = False,
            headers: dict[str, str] | None = None) -> Listing:
    """Every model this provider offers, from the provider where possible.

    Live first (and only when the listing is complete); a fresh cache next; an
    old cache only as stale evidence; and nothing but a labelled fallback hint
    when neither is available. An incomplete listing and a failed `refresh`
    both leave the last cache in place rather than destroying or overwriting
    it, and neither is ever cached as authoritative.
    """
    spec = catalogue.get(provider)
    endpoint = endpoint_of(provider, base_url)
    scope = scope_for(provider, api_key, headers)

    cached = _read_cache(provider, cache_root, endpoint, scope)
    if cached and not refresh and cached.age_seconds < FRESH_FOR:
        cached.source = "cached"
        return cached

    models, why, complete = _ask(provider, endpoint, api_key, headers)
    if complete and models:
        found = Listing(provider=provider, models=models, source="live",
                        fetched_at=time.time(), endpoint=endpoint)
        _write_cache(found, cache_root, scope)
        return found

    # Not an authoritative listing: never mark it live, never write a cache.
    if cached:
        cached.source = "stale"
        cached.error = why
        return cached

    return Listing(provider=provider, source="unavailable", error=why,
                   endpoint=endpoint,
                   fallback=list(spec.fallback_models if spec else ()))


def cached(provider: str, base_url: str = "",
           cache_root: Path | None = None, api_key: str = "",
           headers: dict[str, str] | None = None) -> Listing | None:
    """The last list kept on disk, if any, with no network call.

    `source` is `cached` while the list is still fresh and `stale` once it is
    old. `None` when nothing has been kept for this provider, endpoint and
    credential scope — in which case availability is unknown, not false. This
    is the offline reader for a caller that must not touch the network (e.g.
    `comodor doctor`).
    """
    endpoint = endpoint_of(provider, base_url)
    scope = scope_for(provider, api_key, headers)
    found = _read_cache(provider, cache_root, endpoint, scope)
    if found is None:
        return None
    found.source = "cached" if found.age_seconds < FRESH_FOR else "stale"
    return found


def _ask(provider: str, base_url: str, api_key: str,
         headers: dict[str, str] | None) -> tuple[list[Model], str, bool]:
    """A request (or a bounded page-walk): `(models, reason, complete)`.

    `complete` is true only when the provider's answer is the whole list. A
    single OpenAI-style response is complete when it arrives; a paginated walk
    is complete only when it reaches the end. A partial walk is returned with
    `complete=False`, so the caller never treats it as authoritative.
    """
    if not base_url:
        return [], "that provider has no endpoint to ask", False

    from ..net import http

    session = http.Session()
    try:
        if provider == "anthropic":
            return _ask_anthropic(session, base_url, api_key, headers)
        return _ask_openai(session, base_url, api_key, headers, provider)
    finally:
        try:
            session.close()
        except Exception:
            pass


def _status_reason(status: int) -> str:
    if status in (401, 403):
        return "that key was refused"
    return f"the provider answered {status}"


def _ask_openai(session: Any, base_url: str, api_key: str,
                headers: dict[str, str] | None,
                provider: str) -> tuple[list[Model], str, bool]:
    url = f"{base_url.rstrip('/')}/models"
    try:
        response = session.get(url,
                               headers=effective_headers(provider, api_key, headers),
                               timeout=TIMEOUT)
        if response.status_code >= 400:
            return [], _status_reason(response.status_code), False
        payload = response.json()
    except Exception as error:
        return [], f"{type(error).__name__}", False

    models = _parse(payload, provider)
    if not models:
        return [], "the provider listed nothing", True
    return models, "", True


def _ask_anthropic(session: Any, base_url: str, api_key: str,
                   headers: dict[str, str] | None) -> tuple[list[Model], str, bool]:
    """Anthropic's model list, walked a page at a time.

    Its endpoint is paginated (`has_more` / `last_id`), so asking once shows
    only the first page. The walk is bounded by `MAX_PAGES` and `MAX_MODELS`,
    de-duplicates ids, and stops the moment the provider says there is no more.
    A walk that hits a bound, a repeated cursor, a missing cursor or a failing
    page is **incomplete** and is reported as such — never as a live listing.
    """
    url = f"{base_url.rstrip('/')}/models"
    request_headers = effective_headers("anthropic", api_key, headers)
    collected: list[Model] = []
    seen: set[str] = set()
    cursors: set[str] = set()
    after = ""
    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"limit": PAGE_LIMIT}
        if after:
            params["after_id"] = after
        try:
            response = session.get(url, headers=request_headers, params=params,
                                   timeout=TIMEOUT)
            if response.status_code >= 400:
                return collected, _status_reason(response.status_code), False
            payload = response.json()
        except Exception as error:
            return collected, f"{type(error).__name__}", False

        for model in _parse(payload, "anthropic"):
            if model.id and model.id not in seen:
                seen.add(model.id)
                collected.append(model)

        more = bool(payload.get("has_more")) if isinstance(payload, dict) else False
        if not more:
            return collected, ("" if collected else "the provider listed nothing"), True

        last_id = str(payload.get("last_id") or "") if isinstance(payload, dict) else ""
        if not last_id:
            return collected, "the provider's page had no cursor", False
        if last_id == after or last_id in cursors:
            return collected, "the provider's paging cursor repeated", False
        if len(collected) >= MAX_MODELS:
            return collected, "the model list exceeded the discovery limit", False
        cursors.add(last_id)
        after = last_id

    return collected, "the model list exceeded the page limit", False


def _parse(payload: Any, provider: str = "") -> list[Model]:
    """Read the shapes the providers actually send.

    OpenAI's `{"data": [{"id": ...}]}` is the common one. OpenRouter uses it
    and adds `name`, `context_length` and `pricing`. Anthropic sends
    `display_name`, `max_input_tokens` and `max_tokens`. Anything unrecognised
    still yields its ids, because an id is the only field that is required to
    be useful.

    A capability the provider did not describe stays `None`; only structured
    metadata sets it. The model's *type* (agent vs other) comes from structured
    output modalities where a provider supplies them, never from the name.
    """
    entries = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    models: list[Model] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            identifier = entry
        elif isinstance(entry, dict):
            identifier = str(entry.get("id") or entry.get("name") or "").strip()
        else:
            continue
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        if isinstance(entry, str):
            models.append(Model(id=entry))
            continue
        pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
        top = entry.get("top_provider") if isinstance(entry.get("top_provider"), dict) else {}
        shape = entry.get("architecture") if isinstance(entry.get("architecture"), dict) else {}
        capabilities = (entry.get("capabilities")
                        if isinstance(entry.get("capabilities"), dict) else {})
        parameters = entry.get("supported_parameters")

        # `None` rather than `False` where the provider said nothing. "It
        # cannot do this" and "nobody told us" are different, and only one of
        # them is worth warning somebody about.
        tools = None
        if isinstance(parameters, list):
            tools = "tools" in parameters
        elif isinstance(capabilities.get("tools"), bool):
            tools = capabilities["tools"]

        modalities = shape.get("input_modalities")
        vision = "image" in modalities if isinstance(modalities, list) else None
        if vision is None and isinstance(capabilities.get("vision"), bool):
            vision = capabilities["vision"]

        output = shape.get("output_modalities")
        category = ("agent" if "text" in output else "other") \
            if isinstance(output, list) else ""

        models.append(Model(
            id=identifier,
            name=str(entry.get("name") or entry.get("display_name") or ""),
            context=_as_int(entry.get("context_length")
                            or entry.get("context_window")
                            or entry.get("max_input_tokens")
                            or top.get("context_length")),
            max_output=_as_int(top.get("max_completion_tokens")
                               or entry.get("max_output_tokens")
                               or entry.get("max_tokens")),
            input_cost=_per_million(pricing.get("prompt")),
            output_cost=_per_million(pricing.get("completion")),
            tools=tools,
            vision=vision,
            category=category,
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


def _digest(value: str) -> str:
    """A short, non-reversible identity for a cache key component."""
    if not value:
        return "default"
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def _cache_file(provider: str, cache_root: Path | None, endpoint: str = "",
                scope: str = "public") -> Path | None:
    if cache_root is None:
        return None
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in provider)
    return (Path(cache_root) / "cache"
            / f"models-{safe}-{_digest(endpoint)}-{_digest(scope)}.json")


def _read_cache(provider: str, cache_root: Path | None, endpoint: str = "",
                scope: str = "public") -> Listing | None:
    path = _cache_file(provider, cache_root, endpoint, scope)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        stored_endpoint = str(payload.get("endpoint") or "")
        stored_scope = str(payload.get("scope") or "")
        if endpoint and stored_endpoint and stored_endpoint != endpoint:
            return None
        if stored_scope and stored_scope != scope:
            return None
        return Listing(
            provider=provider,
            models=[Model(**entry) for entry in payload.get("models", [])],
            fetched_at=float(payload.get("fetched_at") or 0.0),
            endpoint=stored_endpoint or endpoint,
        )
    except Exception:
        # A half-written or hand-edited cache is a cache to ignore, never a
        # reason to fail: this is on the path to a settings panel.
        return None


def _write_cache(found: Listing, cache_root: Path | None,
                 scope: str = "public") -> None:
    path = _cache_file(found.provider, cache_root, found.endpoint, scope)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "fetched_at": found.fetched_at,
            "endpoint": found.endpoint,
            "scope": scope,
            "models": [model.as_dict() for model in found.models],
        }), encoding="utf-8")
    except OSError:
        pass
