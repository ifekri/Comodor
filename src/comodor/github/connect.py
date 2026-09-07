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

#: Which connection protocol this agent speaks.
#:
#: 1. The browser shows a signed receipt and the person copies it into the
#:    terminal. Every released Comodor before this one.
#: 2. The Worker holds the result briefly and this machine collects it itself,
#:    by signing a poll with the key the grant already names. Nothing to copy.
#:
#: Asked for on `install`. The Worker answers with what it actually gave —
#: a deployment that cannot hold a result says 1 — so an agent talking to an
#: older Worker falls back rather than polling something that will never have
#: an answer for it.
PROTOCOL = 2
PROTOCOL_RECEIPT = 1

#: How often to ask whether the browser has finished.
#:
#: Two seconds is under the threshold where a person starts wondering whether
#: it is working, and thirty polls a minute is nothing to a Worker. It is a
#: floor rather than a target: `wait_for` sleeps between calls rather than
#: spinning, so a slow round trip simply makes the interval longer.
POLL_EVERY = 2.0

#: What a signed poll is asking to do. Part of what is signed, so a signature
#: made for one action cannot be presented as another.
CLAIM_ACTION = "claim"

#: The version tag on what a poll signs. Distinct from the grant's on purpose:
#: two schemes that share a prefix are two schemes one of which can be
#: presented as the other.
FLOW_SCHEME = "comodor-github-flow-v1"

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

    #: Signed by the Worker, short-lived, unforgeable and unmodifiable. Not
    #: one-time: marking one used needs somewhere to write the mark and there
    #: is no store, so saying "one-time" would be a claim the architecture
    #: cannot keep.
    #:
    #: It is also not a credential. A state names an installation nobody has
    #: proved they own; what turns one into a connection is the browser
    #: authorising with GitHub at the end of the flow, where GitHub confirms
    #: the installation belongs to the person signed in. A state seen in a URL
    #: gets its holder as far as that check and no further.
    state: str
    #: Which attempt this is. Inside the signed payload, so it cannot be
    #: changed - but the payload is base64 rather than encrypted, so anybody
    #: holding the state can read it. It is a correlation id, not a secret:
    #: matching it means a receipt pasted from another flow is refused rather
    #: than connected, which is a guard against confusion and not against an
    #: attacker.
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
    #: What the Worker actually agreed to, which may be less than was asked
    #: for. An older deployment cannot hold a result, so it answers 1 and the
    #: person copies a line as before.
    protocol: int = PROTOCOL_RECEIPT

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def automatic(self) -> bool:
        """Whether the terminal can collect the result by itself."""
        return self.protocol >= PROTOCOL and self.key is not None

    @property
    def seconds_left(self) -> float:
        return max(0.0, self.expires_at - time.time())


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
            # a half-finished flow can tell which machine started it. It shares
            # a spelling with the GitHub App's slug and is not the same thing —
            # this says what started the flow, not which app is being installed.
            "client": "comodor-agent",
            # Public, by construction. It is safe in a URL, safe in a log, and
            # useless without the private half that stays on this machine.
            "public_key": key.public,
            # What this agent can do. The Worker decides what it actually gets.
            "protocol": PROTOCOL,
        })
        state = str(found.get("state") or "")
        nonce = str(found.get("nonce") or "")
        url = str(found.get("url") or "")
        if not state or not url or not nonce:
            raise ConnectError("the endpoint did not return a flow to follow")
        if not url.startswith("https://"):
            raise ConnectError(f"refusing to open a non-HTTPS URL: {url[:60]}")

        # The deadline comes from the Worker. A second copy of the lifetime
        # here would drift the first time the server's changed, and the
        # terminal would either give up early or wait past the point where a
        # result can still exist.
        seconds = float(found.get("expires_in") or 900)
        agreed = int(found.get("protocol") or PROTOCOL_RECEIPT)
        return Pending(state=state, nonce=nonce, url=url,
                       expires_at=time.time() + seconds, key=key,
                       protocol=agreed)

    def open(self, pending: Pending) -> bool:
        """Open the browser. False if there is none — the URL is printed then."""
        try:
            return bool(webbrowser.open(pending.url))
        except Exception:
            return False

    # -- finishing ---------------------------------------------------------- #

    def _poll_once(self, pending: Pending) -> dict[str, Any]:
        """Ask the Worker whether the browser has finished.

        Signed, because a state is not a secret. It travels in a URL — the
        address bar, the history, the referrer GitHub sends — and its nonce is
        plain base64 inside it, so anybody who saw the link knows the flow.
        What they do not have is the private half of the key this machine
        generated before the flow started, whose public half is inside the
        signed state and is the key the grant names. Signing with it proves
        this is the machine the grant is *for*, which is the actual question.

        The timestamp and per-request nonce bound replay: the Worker refuses a
        signature outside a small window, and the result is handed over once
        and deleted, so a replay that arrives after this one gets nothing.
        """
        if pending.key is None:
            raise ConnectError("this attempt has no client key to sign with")

        timestamp = int(time.time())
        # Long enough that two polls a second apart cannot collide, and it is
        # inside what is signed so it cannot be swapped for another request's.
        request_nonce = secrets.token_urlsafe(18)
        message = SEPARATOR.join((FLOW_SCHEME, CLAIM_ACTION, pending.state,
                                  str(timestamp), request_nonce))
        return self._post("claim", {
            "state": pending.state,
            "timestamp": timestamp,
            "nonce": request_nonce,
            "signature": pending.key.sign(message.encode("utf-8")),
        })

    def wait_for(self, pending: Pending, *, on_tick=None,
                 interval: float = POLL_EVERY,
                 sleep=time.sleep, now=time.monotonic) -> GitHubInstallation:
        """Wait for the browser, and return what it authorised.

        The deadline is the Worker's, carried on `pending`. A second lifetime
        written here would drift the first time the server's changed, and this
        end would either give up while a result still existed or wait past the
        point where one could.

        `sleep` and `now` are arguments so a test can run the whole loop
        without spending the time. Nothing here busy-waits: every pass either
        blocks on a request or sleeps.
        """
        if not pending.automatic:
            raise ConnectError(
                "this connection is not one the terminal can finish by itself")

        deadline = now() + pending.seconds_left
        while True:
            found = self._poll_once(pending)
            status = str(found.get("status") or "")

            if status == "connected":
                return self._accept(pending, found)
            if status == "cancelled":
                raise ConnectError("the installation was cancelled on GitHub")
            if status == "expired":
                raise ConnectError(
                    "that connection link expired before it was used. Run "
                    "`comodor github connect` again.")
            if status and status != "pending":
                raise ConnectError(f"the endpoint said {status}")

            if on_tick is not None:
                on_tick()
            if now() >= deadline:
                raise ConnectError(
                    "nobody finished the authorisation in time. Nothing has "
                    "been connected.")
            # Never past the deadline: a sleep that overshoots turns a clean
            # timeout into one extra pointless request.
            sleep(min(interval, max(0.0, deadline - now())))


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
        belongs to *this* attempt, so a receipt from another flow - pasted in
        by mistake, most likely - is refused rather than connected.

        That check is for confusion, not for an attacker. The nonce is
        readable by anybody holding the state, so it stops nobody who is
        trying. What stops them is the grant inside the receipt: it names the
        public key of the machine that started the flow, and it is issued only
        after GitHub confirms, as the signed-in user, that the installation is
        theirs. A receipt collected by the wrong machine names a key that
        machine does not have.
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

        return self._accept(pending, found)

    def _accept(self, pending: Pending, found: dict[str, Any]) -> GitHubInstallation:
        """Everything that has to be true before anything is written down.

        One place, called by both protocols. The receipt path and the polling
        path differ in how the answer arrives and in nothing else that
        matters, and two copies of these checks would be two things to keep in
        step — with the copy that drifts being the one nobody is looking at.

        The nonce is checked here rather than only at the Worker. The Worker
        proves the answer is one it issued; matching the nonce proves it
        belongs to *this* attempt. That check is against confusion rather than
        against an attacker: the nonce is readable by anybody holding the
        state. What stops an attacker is the grant, which names the public key
        of the machine that started the flow and is issued only after GitHub
        confirms, as the signed-in user, that the installation is theirs.
        """
        if str(found.get("nonce") or "") != pending.nonce:
            raise ConnectError(
                "that result belongs to a different connection attempt. "
                "Run `comodor github connect` again.")

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

        # Written only now. An abandoned flow - a browser closed, an
        # authorisation never finished - leaves nothing on disk, and the file
        # is named after an installation that has been verified rather than
        # one somebody typed.
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
