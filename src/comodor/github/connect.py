"""Connecting an installation, and resolving a repository to one.

Two things live here. The first is the installation flow as this machine sees
it: open a browser at the Worker, wait for the person to choose an account and
its repositories, and come back with an installation the Worker has already
verified against GitHub. The second is the lookup every repository operation
starts with — `ifekri/Comodor` to an installation to a token.

**The agent never trusts an installation id it was handed.** GitHub sends one
to the Worker's setup URL as a query parameter, and a query parameter is
something anybody can type. The Worker authenticates as the app and asks
GitHub what that installation actually is before it says anything back, and
what returns here is that verified answer. This module's job is to not undo
that: it reads the Worker's response over TLS and nothing else.

**No new account system.** The installation belongs to the machine that
completed the flow, recorded in that machine's own config. There is no
`comodor_user_id`, because Comodor has no users to have ids — it is a program
somebody runs, and the file it writes is theirs.

**What makes it this machine's.** An installation id is not a credential: it is
a small integer that appears in URLs. So `connect` generates a key pair for the
connection, sends only the public half, and gets back a *grant* — the Worker's
signed statement that this installation belongs to that key. Every later
request carries the grant and a signature made with the private half, and the
Worker reads the installation id out of the grant rather than out of the
request. Knowing an id is then worth nothing; holding the key is everything.
"""

from __future__ import annotations

import json
import secrets
import time
import webbrowser
from dataclasses import dataclass
from typing import Any

from ..config import Config, GitHubInstallation
from ..net import http
from . import identity
from .identity import ClientKey, IdentityError
from .tokens import InstallationToken, TokenError, redact

#: One call to the Worker.
TIMEOUT = 30.0

#: What joins the fields of a signed request. A newline, because none of the
#: fields can contain one - so no two different sets of fields can produce the
#: same bytes to sign, and a boundary cannot be shifted to move meaning from
#: one field into the next.
SEPARATOR = "\n"


class ConnectError(RuntimeError):
    """The connection could not be completed. Safe to show."""


@dataclass(frozen=True)
class Pending:
    """A flow that has been started and not yet finished."""

    #: Signed by the Worker, short-lived, and bound to the nonce below. Not
    #: one-time: marking one used needs somewhere to write the mark and there
    #: is no store, so saying "one-time" would be a claim the architecture
    #: cannot keep. What it does give is that a state cannot be invented or
    #: edited, it expires in fifteen minutes, and a receipt derived from it is
    #: refused by any agent whose nonce does not match - so a state seen in a
    #: URL cannot become a connection on somebody else's machine.
    state: str
    #: The random half of the state, which the receipt is signed against. Kept
    #: separately so this attempt can tell its own receipt from any other.
    nonce: str
    #: Where to send the person. Carries the state, so the Worker can tie the
    #: GitHub redirect back to this attempt.
    url: str
    expires_at: float
    #: This connection's key pair. Generated before the flow starts, because
    #: the public half has to travel inside the state the Worker signs — it is
    #: what the grant will name. Written to disk only once the installation is
    #: known, so an abandoned flow leaves no key behind.
    key: ClientKey | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class Connector:
    """Talks to the Worker at `comodor.ai` and to nothing else.

    Every method here is one HTTPS call to an endpoint that holds the app's
    private key. The key is never sent, never received, and never on this
    machine.
    """

    def __init__(self, config: Config, timeout: float = TIMEOUT) -> None:
        self.config = config
        self.timeout = timeout

    @property
    def base(self) -> str:
        return str(self.config.github.endpoint or "https://comodor.ai").rstrip("/")

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base}/api/integrations/github/{path.lstrip('/')}"
        try:
            answer = http.post(url, json=body, timeout=self.timeout,
                               headers={"accept": "application/json"})
        except Exception as problem:
            raise ConnectError(
                f"could not reach {self.base}: {redact(problem)}") from None

        try:
            found = json.loads(answer.content.decode("utf-8", "replace"))
        except ValueError:
            raise ConnectError(
                f"{self.base} answered {answer.status_code} with "
                f"something that is not JSON") from None

        if not (200 <= answer.status_code < 300):
            said = str(found.get("error") or found.get("message") or "")
            raise ConnectError(
                f"{self.base} refused: {redact(said) or answer.status_code}")
        return found if isinstance(found, dict) else {}

    # -- starting ---------------------------------------------------------- #

    def begin(self) -> Pending:
        """Ask the Worker to start a flow, and get the URL to open.

        The state is made by the Worker rather than here, because the Worker
        is what has to recognise it later and it is the only side that can say
        whether one has been used. A state the agent invented would have to be
        registered anyway, which is the same round trip with an extra way to
        get it wrong.

        The key pair is made here, first, and only its public half is sent. The
        Worker puts that key inside the signed state, so it arrives at `setup`
        unaltered and becomes the key the grant names. Nothing about this
        connection can be claimed by a machine that does not hold the other
        half.
        """
        key = identity.generate()
        found = self._post("install", {
            # Not a secret and not an identity: a label, so somebody looking at
            # a half-finished flow can tell which machine started it.
            "client": "comodor-agent",
            # Public, by construction. It is safe in a URL, safe in a log, and
            # useless without the private half that stays on this machine.
            "public_key": key.public,
        })
        state = str(found.get("state") or "")
        nonce = str(found.get("nonce") or "")
        url = str(found.get("url") or "")
        if not state or not url or not nonce:
            raise ConnectError("the endpoint did not return a flow to follow")
        if not url.startswith("https://"):
            raise ConnectError(f"refusing to open a non-HTTPS URL: {url[:60]}")

        seconds = float(found.get("expires_in") or 900)
        return Pending(state=state, nonce=nonce, url=url,
                       expires_at=time.time() + seconds, key=key)

    def open(self, pending: Pending) -> bool:
        """Open the browser. False if there is none — the URL is printed then."""
        try:
            return bool(webbrowser.open(pending.url))
        except Exception:
            return False

    # -- finishing ---------------------------------------------------------- #

    def collect(self, pending: Pending, receipt: str) -> GitHubInstallation:
        """Turn the receipt from the browser into a verified installation.

        The receipt is what the setup page showed: what GitHub confirmed about
        the installation, signed by the Worker. This hands it back for the
        signature to be checked, and gets the installation.

        Why a person copies a line rather than the browser posting it: there
        is nowhere on the server to leave it. A signed receipt needs no
        storage, and the person is the one party present at both the browser
        that installed the app and the terminal that asked for it. Copying is
        the join.

        The nonce is checked here rather than only at the Worker. The Worker
        proves the receipt is one it issued; matching the nonce proves it
        belongs to *this* attempt, so a receipt from somebody else's flow —
        pasted in by mistake or otherwise — is refused rather than connected.
        """
        text = (receipt or "").strip()
        if not text:
            raise ConnectError("nothing was pasted")

        found = self._post("claim", {"receipt": text})
        status = str(found.get("status") or "")

        if status == "cancelled":
            raise ConnectError("the installation was cancelled on GitHub")
        if status != "connected":
            raise ConnectError(f"the endpoint said {status or 'nothing'}")

        if str(found.get("nonce") or "") != pending.nonce:
            raise ConnectError(
                "that receipt belongs to a different connection attempt. "
                "Run `comodor github connect` again and use the line from "
                "the page it opens.")

        grant = str(found.get("grant") or "")
        if not grant:
            raise ConnectError(
                "the endpoint completed the installation but issued no grant, "
                "so this machine could not prove the connection is its own. "
                "Nothing has been saved.")
        if pending.key is None:
            raise ConnectError("this attempt has no client key to save")

        installation = _installation_from(found.get("installation") or {})
        installation.grant = grant

        # Written only now. An abandoned flow - a browser closed, a receipt
        # never pasted - leaves nothing on disk, and the file is named after an
        # installation that has been verified rather than one somebody typed.
        try:
            identity.save(self.config.paths.user,
                          installation.installation_id, pending.key)
        except IdentityError as problem:
            raise ConnectError(
                f"the connection was made but its key could not be saved: "
                f"{problem}. Nothing has been recorded, because a connection "
                f"whose key is missing cannot be used.") from None

        return installation

    # -- using it ----------------------------------------------------------- #

    def _signed(self, action: str, installation_id: int) -> dict[str, Any]:
        """A request body that proves who is asking.

        Four things, and each is load-bearing:

        * the **grant**, which is the Worker's own signed statement of which
          installation belongs to which key. The installation id is read from
          there, so it is never something the caller gets to choose;
        * a **timestamp**, so a captured request stops working;
        * a **nonce**, so two requests in the same second are still distinct;
        * a **signature** over all of it, made with the private key, which is
          the only part an attacker cannot produce.

        The signed bytes are laid out exactly as the Worker lays them out -
        including the action - so a signature made for `verify` cannot be
        presented at `token`.
        """
        found = self.config.github.find_by_id(installation_id)
        if found is None or not found.grant:
            raise TokenError(
                f"installation {installation_id} has no grant on this machine. "
                f"Run `comodor github connect` to reconnect it.")

        try:
            key = identity.load(self.config.paths.user, installation_id)
        except IdentityError as problem:
            raise TokenError(str(problem)) from None

        timestamp = int(time.time())
        nonce = secrets.token_urlsafe(24)
        # The separator is a newline and no field can contain one, so no two
        # different sets of fields ever sign the same bytes.
        message = SEPARATOR.join(("comodor-github-v1", action, found.grant,
                                  str(timestamp), nonce)).encode("utf-8")
        return {
            "grant": found.grant,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": key.sign(message),
        }

    def mint(self, installation_id: int) -> InstallationToken:
        """One short-lived installation token, from the Worker.

        The Worker signs an app JWT with the private key, exchanges it for
        this token, and returns the token alone. The JWT never leaves it.

        The request carries no installation id. It carries a grant, and the
        Worker takes the id out of that - which is the whole of the fix, since
        an id in the body was something anybody could write.
        """
        found = self._post("token", self._signed("token", int(installation_id)))
        token = str(found.get("token") or "")
        if not token:
            raise TokenError("the endpoint returned no token")
        expires_at = float(found.get("expires_at") or (time.time() + 3000))
        return InstallationToken(token=token, expires_at=expires_at,
                                 installation_id=int(installation_id))

    def verify(self, installation_id: int) -> GitHubInstallation | None:
        """What GitHub says this installation is, now.

        None when it is gone — uninstalled, or suspended. Permissions change
        after a connection is made, and a stale record either refuses work
        that would succeed or attempts work that cannot.

        Signed like `mint`, and for the same reason: an unsigned `verify` would
        answer questions about installations the asker has no relationship
        with, which is a directory of other people's accounts.
        """
        found = self._post("verify", self._signed("verify", int(installation_id)))
        if str(found.get("status") or "") == "gone":
            return None
        installation = _installation_from(found.get("installation") or {})
        installation.updated_at = time.time()
        return installation

    def disconnect(self, installation_id: int) -> None:
        """Tell the Worker to forget this installation.

        Best effort. The local record is removed either way: somebody
        disconnecting because they no longer trust something should not be
        told "sorry, the server is down".

        The private key goes with it. Leaving it behind would leave the one
        piece of this connection that is actually secret sitting on disk after
        the person asked for the connection to be gone.
        """
        try:
            self._post("disconnect", self._signed("disconnect",
                                                  int(installation_id)))
        except (ConnectError, TokenError):
            pass
        identity.forget(self.config.paths.user, int(installation_id))


def _installation_from(payload: dict[str, Any]) -> GitHubInstallation:
    """One installation, from what the Worker verified against GitHub.

    Every field is coerced rather than trusted: this arrives over the network,
    and a string where an integer is expected should be a clear refusal here
    rather than a TypeError somewhere later.
    """
    try:
        installation_id = int(payload.get("installation_id") or 0)
        account = payload.get("account") or {}
        account_id = int(account.get("id") or 0)
    except (TypeError, ValueError):
        raise ConnectError("the endpoint sent an installation it cannot be") \
            from None

    if not installation_id:
        raise ConnectError("the endpoint sent no installation id")

    permissions = payload.get("permissions") or {}
    if not isinstance(permissions, dict):
        permissions = {}

    now = time.time()
    return GitHubInstallation(
        installation_id=installation_id,
        account_id=account_id,
        account_login=str(account.get("login") or ""),
        account_type=str(account.get("type") or ""),
        repository_selection=str(payload.get("repository_selection") or ""),
        permissions={str(k): str(v) for k, v in permissions.items()},
        created_at=now,
        updated_at=now,
    )


def new_state() -> str:
    """A state token, for the Worker and for tests of the same shape."""
    return secrets.token_urlsafe(32)
