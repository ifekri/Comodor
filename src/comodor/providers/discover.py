"""Credentials and models this machine already has.

Setting up an agent means finding an API key, which means a billing page, a
new secret to keep, and a decision about which provider to pay. That is the
tedious part, and for a lot of people it is unnecessary: the machine already
has what is needed and nobody asked it.

Two kinds of "already", and they are found differently.

**Something running here.** Ollama and LM Studio serve an OpenAI-compatible
endpoint on a known port and need no key at all. If one is running, the
correct first offer is not a list of billing pages — it is "this is here, and
it has these three models". Found by asking the port, because a binary on disk
is not a server that is up, and the question `/v1/models` answers is exactly
"are you there, and what can you do".

**A key already in the environment.** `OPENROUTER_API_KEY` and its siblings
are read and applied by the configuration layer already; what was missing was
saying so. Somebody who exported a key an hour ago should be told it was
found, not asked to paste it again.

Three rules, because this runs on the first-run path and a first run must not
hang or lie:

* **Fast or absent.** A probe that takes two seconds is a setup wizard that
  pauses for no reason on every machine without a local model. The timeout is
  short, the probes run together, and a slow answer is the same as no answer.
* **Never fatal.** Every failure here is a thing not offered, never an error.
* **Nothing is claimed that was not seen.** A runtime is reported only if it
  answered, and its models are the ones it listed rather than the ones the
  catalogue guesses.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Iterable

from .. import catalogue

#: Long enough for a server on this machine, short enough that two of them not
#: being there is not a pause anybody notices. Local means local: a runtime
#: that needs more than this to say hello is not one to put in front of
#: somebody on their first run.
PROBE_TIMEOUT = (0.35, 1.5)

#: How many models to name. The rest are still there; this is a first
#: impression, not a catalogue.
SHOW_MODELS = 8


@dataclass
class Running:
    """A model server answering on this machine."""

    provider: str
    label: str
    base_url: str
    models: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Answering is not enough — it has to have something loaded.

        Ollama with no models pulled answers `/v1/models` with an empty list.
        Offering it would be offering a provider that fails on the first
        request, which is worse than not offering it.
        """
        return bool(self.models)

    @property
    def summary(self) -> str:
        if not self.models:
            return "running, but no models are installed yet"
        shown = ", ".join(self.models[:3])
        more = len(self.models) - 3
        return f"{shown}{f', and {more} more' if more > 0 else ''}"


@dataclass
class Held:
    """A provider whose key is already in the environment."""

    provider: str
    label: str
    variable: str


def local_specs() -> list[catalogue.ProviderSpec]:
    """The catalogue entries that describe something running on this machine."""
    return [spec for spec in catalogue.CATALOGUE
            if not spec.needs_key and spec.base_url
            and ("localhost" in spec.base_url or "127.0.0.1" in spec.base_url)]


def running_here(specs: Iterable[catalogue.ProviderSpec] | None = None,
                 timeout: tuple[float, float] = PROBE_TIMEOUT) -> list[Running]:
    """Ask each local port whether anything is listening, all at once.

    Together rather than one after another: two runtimes that are both absent
    would otherwise cost two timeouts, and the whole point is that somebody
    with no local model never notices this ran.
    """
    found: list[Running] = []
    lock = threading.Lock()

    def ask(spec: catalogue.ProviderSpec) -> None:
        models = _models_at(spec.base_url, timeout)
        if models is None:
            return
        with lock:
            found.append(Running(provider=spec.id, label=spec.label,
                                 base_url=spec.base_url,
                                 models=models[:SHOW_MODELS]))

    threads = [threading.Thread(target=ask, args=(spec,), daemon=True)
               for spec in (specs if specs is not None else local_specs())]
    for thread in threads:
        thread.start()
    # Joined with a ceiling of their own, so a socket that neither answers nor
    # refuses cannot hold up a first run.
    deadline = sum(timeout) + 0.5
    for thread in threads:
        thread.join(timeout=deadline)

    found.sort(key=lambda item: (not item.usable, item.provider))
    return found


def _port_is_open(base_url: str, deadline: float) -> bool:
    """Is anything accepting connections there, on either address family?

    Asked with a socket before the HTTP client is built, because this is the
    expensive half. `localhost` resolves to both `::1` and `127.0.0.1`, and a
    closed port on Windows drops the connection attempt rather than refusing
    it — so a sequential probe pays the timeout twice for a machine that has
    no local model, which is most machines.

    Both families are tried at once. Assuming IPv4 would be faster and would
    miss a runtime bound only to `::1`, and something running that does not
    get found is the one outcome this whole module exists to avoid.
    """
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(base_url)
    host, port = parts.hostname or "localhost", parts.port
    if not port:
        port = 443 if parts.scheme == "https" else 80

    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False

    open_ports: list[bool] = []
    lock = threading.Lock()

    def knock(family: int, address: tuple) -> None:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(deadline)
                sock.connect(address)
        except OSError:
            return
        with lock:
            open_ports.append(True)

    knocks = [threading.Thread(target=knock, args=(family, address), daemon=True)
              for family, _, _, _, address in addresses]
    for thread in knocks:
        thread.start()
    for thread in knocks:
        thread.join(timeout=deadline + 0.2)
    return bool(open_ports)


def _models_at(base_url: str, timeout: tuple[float, float]) -> list[str] | None:
    """What this endpoint says it can run, or None if nothing answered."""
    from ..net import http

    if not _port_is_open(base_url, deadline=timeout[0]):
        return None

    # No retries. A refused connection to a port on this machine is a complete
    # answer the first time, and the default policy turns "nothing is running"
    # into three attempts and two backoffs — which is the whole cost of this,
    # paid by everybody who has no local model.
    session = http.Session(retry=http.Retry(total=0, retry_on_connection_error=False))
    try:
        response = session.get(f"{base_url.rstrip('/')}/models", timeout=timeout)
        if response.status_code >= 400:
            return None
        payload = response.json()
    except Exception:
        # Refused, timed out, answered with something that is not JSON: all of
        # them mean the same thing here, which is that there is nothing to
        # offer.
        return None
    finally:
        try:
            session.close()
        except Exception:
            pass

    entries = payload.get("data", payload) if isinstance(payload, dict) else payload
    models: list[str] = []
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("id"):
            models.append(str(entry["id"]))
        elif isinstance(entry, str):
            models.append(entry)
    return sorted(models)


def keys_in_the_environment() -> list[Held]:
    """Providers whose key is already exported.

    The configuration layer reads and applies these on its own; this is only
    so the wizard can say which ones it found. Somebody who exported a key an
    hour ago should be told, not asked to paste it again.

    The value is never returned — only which variable held it. A first-run
    screen has no business quoting a secret back at the room.
    """
    held: list[Held] = []
    for spec in catalogue.CATALOGUE:
        if not spec.env_key:
            continue
        if os.environ.get(spec.env_key, "").strip():
            held.append(Held(provider=spec.id, label=spec.label,
                             variable=spec.env_key))
    return held


