"""Optional external memory, in service of the local brain.

Comodor's memory is a local file. Some people will want more than that —
cloud personalisation that follows them across machines, or a team-shared
shelf of facts — and the honest way to offer it is as a *mirror*, never as
the brain itself:

* **The local store is the source of truth.** Facts are written here first
  and confirmed here; the provider is told afterwards. Unplug the provider
  and nothing changes but one log line.
* **At most one provider.** Two would mean two schemas to keep honest and
  two services with the same private facts, for no gain anyone can name.
  Configuring a second is refused with the first named.
* **Recall augmentation is additive and capped.** What the provider
  remembers is offered to the briefing under a token ceiling, marked as
  coming from outside; it can add context, never replace it.
* **The key lives in the environment, never on disk** — the same rule as
  every other credential this program accepts, and the reason the config
  file names an environment variable rather than holding the key.

Failure semantics are deliberate and asymmetric: a provider that cannot be
reached is logged and skipped (it is an *addition* — fail-open), while a
configuration that names two providers or no key is refused outright (it
is a *setup error* — fail-closed). The security gates keep their
fail-closed rule; only the sugar is allowed to spoil.
"""

from .base import Provider, ProviderError, build
from .http_generic import HttpGeneric

__all__ = ["Provider", "ProviderError", "build", "HttpGeneric"]
