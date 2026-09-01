"""A webhook channel: events in, agent work out.

WhatsApp posts its messages to a URL and Comodor answers; CI, monitoring,
Git hosts and home-automation systems all speak the same shape — POST some
JSON when something happens. This module is the general case of that: one
small HTTP server, a list of subscriptions (path + secret + prompt
template), and an agent turn per accepted event.

The security posture is WhatsApp's, generalised, because it was the one
thing about that channel that was already right:

* **Every subscription has a secret, and the signature covers the raw
  bytes.** Verified with HMAC-SHA256 and compared in constant time, before
  any JSON is parsed. A subscription without a secret answers 404 rather
  than 401 — a status that reveals the endpoint exists is a footprint.
* **The agent never writes from a webhook unless the subscription says
  so.** ``allow_writes`` is per-subscription and false by default, and a
  webhook is exactly the actor that must not inherit a channel's trust: it
  is a machine talking, and machines misconfigure each other.
* **The answer comes back synchronously when the requester waits.** GitHub
  gives a request ten seconds; the run takes minutes. So the response is
  ``{"status": "accepted"}`` at once and the turn runs on its own thread;
  a subscription that names a ``reply_url`` gets the finished answer
  delivered there when it lands.
"""

from .server import Server, run
from .subs import Subscriptions, load

__all__ = ["Server", "run", "Subscriptions", "load"]
