"""The agent half of proving who is asking for a token.

An earlier version of this integration would mint a GitHub installation token
for anybody who sent an `installation_id`. Installation ids are small integers
that appear in URLs, so that was a hole wide enough to reach somebody else's
repositories through. The fix is a key pair per connection: the public half
travels in the install flow, the Worker returns a signed grant naming it, and
every later request carries a signature only the private half can make.

The Worker's half of this is tested in `workers/site/github/authorisation.test.mjs`,
where forgery is checked against the runtime that actually verifies. What is
checked here is the half that lives on this machine, which is a different set
of risks:

* the signature must be one Web Crypto accepts, not merely one this file can
  verify against itself - so there is a round trip against a known-good vector;
* the private key must reach disk unreadable by anybody else, and must leave
  when the connection does;
* no request that could do something may go out without a grant and a
  signature, including when the caller passes an installation id directly;
* the id must come from the stored grant, never from the argument.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
from typing import Any

import pytest

from comodor.config import Config, GitHubInstallation
from comodor.github import identity
from comodor.github.connect import ConnectError, Connector, Pending
from comodor.github.identity import ClientKey, IdentityError
from comodor.github.tokens import TokenError

# --------------------------------------------------------------------------- #
# scaffolding
# --------------------------------------------------------------------------- #


class Answer:
    """What the project's HTTP client returns, in the parts this reads."""

    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status_code = status
        self.content = json.dumps(body if body is not None else {}).encode()
        self.headers: dict[str, str] = {}


class Endpoint:
    """A stand-in Worker that records exactly what was sent to it."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> Answer:
        leaf = url.rstrip("/").rsplit("/", 1)[-1]
        self.sent.append((leaf, dict(kwargs.get("json") or {})))
        found = self.answers.get(leaf)
        if isinstance(found, Answer):
            return found
        return Answer(200, found if found is not None else {})

    def body(self, leaf: str) -> dict[str, Any]:
        for name, sent in self.sent:
            if name == leaf:
                return sent
        raise AssertionError(f"nothing was sent to {leaf}")


def a_home(tmp_path, monkeypatch) -> Config:
    """A config whose user directory is a temporary one.

    `COMODOR_HOME` rather than reaching into `Paths`, because that is the
    switch the program itself documents and a test that bypasses it would stop
    covering the path people actually take.
    """
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path))
    from comodor.paths import resolve as resolve_paths
    return Config(paths=resolve_paths(tmp_path))


def connected(tmp_path, monkeypatch, endpoint: Endpoint,
              installation_id: int = 7) -> tuple[Connector, Config, ClientKey]:
    """A connector with one connection already made, key and grant in place."""
    config = a_home(tmp_path, monkeypatch)
    monkeypatch.setattr("comodor.net.http.post", endpoint.post)

    key = identity.generate()
    identity.save(config.paths.user, installation_id, key)
    config.github.remember(GitHubInstallation(
        installation_id=installation_id, account_id=1,
        account_login="ifekri", account_type="User",
        permissions={"contents": "write"}, grant="g2.the-grant.sig"))

    return Connector(config), config, key


# --------------------------------------------------------------------------- #
# the signature itself
# --------------------------------------------------------------------------- #


def test_a_signature_verifies_against_a_known_good_vector():
    """RFC 6979 makes signing deterministic, so a vector is possible at all.

    This is the property everything else rests on: the bytes this produces are
    an ECDSA P-256 signature as the rest of the world reads one. The vector
    below was produced by this implementation and *confirmed by Web Crypto* -
    the same `crypto.subtle.verify` the Worker calls. If the curve arithmetic
    here ever drifts, this fails rather than the integration failing in
    production against a runtime nobody can debug from here.
    """
    private = int(
        "c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721", 16)
    key = ClientKey(private=private, public=_public_of(private))

    first = key.sign(b"sample")
    second = key.sign(b"sample")

    assert first == (
        "79SLKqy2qP0RQN2c1F6B1p0sh3tWqvmRw00OqE6vNxYI"
        "NONq0pqDvyvJOF5JHWCZyP350e1nqn6l9R-TeChXqQ")

    # Deterministic: the same message and key give the same signature. A
    # different one each time would mean `k` came from somewhere random, which
    # is the failure mode that leaks private keys.
    assert first == second
    assert first != key.sign(b"sample.")
    assert len(identity._unb64(first)) == 64        # r || s, raw, not DER


def test_two_signatures_over_different_messages_share_no_nonce():
    """The classic ECDSA break, checked directly.

    Two signatures made with the same `k` reveal the private key by simple
    algebra. `r` is derived from `k` alone, so an equal `r` across two
    different messages is exactly that failure, visible from outside.
    """
    key = identity.generate()

    first = identity._unb64(key.sign(b"one"))[:32]
    second = identity._unb64(key.sign(b"two"))[:32]

    assert first != second


def test_a_public_key_is_the_uncompressed_point_web_crypto_reads():
    key = identity.generate()
    raw = identity._unb64(key.public)

    assert len(raw) == 65
    assert raw[0] == 0x04        # uncompressed, which is what `importKey` takes


def test_a_fingerprint_is_the_hash_of_the_key_the_worker_hashes():
    """The Worker computes SHA-256 over the raw key bytes. So must this, or a
    grant would never match the key that asked for it."""
    key = identity.generate()
    expected = hashlib.sha256(identity._unb64(key.public)).digest()

    assert identity._unb64(key.fingerprint) == expected


def test_a_private_key_is_never_in_a_repr():
    """A stack trace carrying this is the whole secret in a log file."""
    key = identity.generate()

    assert str(key.private) not in repr(key)
    assert f"{key.private:x}" not in repr(key)


# --------------------------------------------------------------------------- #
# keeping the key
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows has no POSIX mode bits to check")
def test_a_saved_key_is_readable_only_by_its_owner(tmp_path):
    key = identity.generate()
    path = identity.save(tmp_path, 7, key)

    mode = stat.S_IMODE(path.stat().st_mode)

    assert not mode & stat.S_IRGRP
    assert not mode & stat.S_IROTH
    assert identity.is_private(tmp_path, 7)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows has no POSIX mode bits to check")
def test_a_key_that_became_world_readable_is_reported(tmp_path):
    """A careless `chmod -R`, or a copy through a permissive umask. Reported
    rather than trusted, because the whole scheme rests on this file."""
    identity.save(tmp_path, 7, identity.generate())
    os.chmod(identity.key_path(tmp_path, 7), 0o644)

    assert not identity.is_private(tmp_path, 7)


def test_a_key_survives_being_written_and_read(tmp_path):
    key = identity.generate()
    identity.save(tmp_path, 7, key)

    back = identity.load(tmp_path, 7)

    assert back.private == key.private
    assert back.public == key.public
    assert back.sign(b"x") == key.sign(b"x")


def test_a_missing_key_says_the_connection_cannot_be_used(tmp_path):
    with pytest.raises(IdentityError) as caught:
        identity.load(tmp_path, 7)

    said = str(caught.value)
    assert "github connect" in said


def test_a_damaged_key_is_refused_rather_than_half_read(tmp_path):
    identity.save(tmp_path, 7, identity.generate())
    identity.key_path(tmp_path, 7).write_text("not a key\n", encoding="utf-8")

    with pytest.raises(IdentityError):
        identity.load(tmp_path, 7)


def test_forgetting_a_key_that_is_not_there_is_not_an_error(tmp_path):
    """Disconnecting must always work."""
    identity.forget(tmp_path, 7)         # must not raise


# --------------------------------------------------------------------------- #
# the nine properties, from this side
# --------------------------------------------------------------------------- #


def test_an_installation_id_alone_does_not_produce_a_request(tmp_path,
                                                             monkeypatch):
    """The original hole, from the agent's side.

    Nothing here can turn a bare id into a call. Without a stored grant there
    is no request to make, so the refusal happens before the network.
    """
    config = a_home(tmp_path, monkeypatch)
    endpoint = Endpoint({"token": {"token": "ghs_x"}})
    monkeypatch.setattr("comodor.net.http.post", endpoint.post)

    with pytest.raises(TokenError) as caught:
        Connector(config).mint(12345)

    assert endpoint.sent == []
    assert "no grant" in str(caught.value)


def test_a_connection_whose_key_is_gone_does_not_reach_the_network(tmp_path,
                                                                   monkeypatch):
    """A grant without its key is not an identity - it is a public statement
    anybody could have copied out of a config file."""
    endpoint = Endpoint({"token": {"token": "ghs_x"}})
    connector, config, _ = connected(tmp_path, monkeypatch, endpoint)
    identity.forget(config.paths.user, 7)

    with pytest.raises(TokenError):
        connector.mint(7)

    assert endpoint.sent == []


def test_a_token_request_carries_a_grant_and_never_an_installation_id(
        tmp_path, monkeypatch):
    """The id is read out of the grant at the Worker. Sending one would be a
    field the Worker must be careful to ignore; not sending one is better."""
    endpoint = Endpoint({"token": {"token": "ghs_x",
                                   "expires_at": time.time() + 3000}})
    connector, _, _ = connected(tmp_path, monkeypatch, endpoint)

    connector.mint(7)
    sent = endpoint.body("token")

    assert sent["grant"] == "g2.the-grant.sig"
    assert "installation_id" not in sent
    assert set(sent) == {"grant", "timestamp", "nonce", "signature"}


def test_a_verify_request_is_signed_too(tmp_path, monkeypatch):
    """An unsigned `verify` answers questions about installations the asker
    has no relationship with, which is a directory of other people's
    accounts."""
    endpoint = Endpoint({"verify": {
        "status": "ok",
        "installation": {"installation_id": 7,
                         "account": {"id": 1, "login": "ifekri",
                                     "type": "User"},
                         "permissions": {"contents": "read"}}}})
    connector, _, _ = connected(tmp_path, monkeypatch, endpoint)

    connector.verify(7)
    sent = endpoint.body("verify")

    assert sent["grant"] == "g2.the-grant.sig"
    assert "installation_id" not in sent
    assert sent["signature"]


def test_a_signature_covers_the_action_so_one_cannot_be_moved_to_the_other(
        tmp_path, monkeypatch):
    """A `verify` signature presented at `token` must not work.

    Without the action in the signed bytes, an attacker who obtained a
    signature for the harmless endpoint would hold one for the endpoint that
    mints credentials.
    """
    endpoint = Endpoint({"token": {"token": "ghs_x"},
                         "verify": {"status": "gone"}})
    connector, _, key = connected(tmp_path, monkeypatch, endpoint)

    connector.mint(7)
    connector.verify(7)

    minting = endpoint.body("token")
    verifying = endpoint.body("verify")

    assert minting["signature"] != verifying["signature"]

    # And concretely: what the mint signed does not verify as a verify.
    from comodor.github.connect import SEPARATOR
    as_a_verify = SEPARATOR.join(
        ("comodor-github-v1", "verify", minting["grant"],
         str(minting["timestamp"]), minting["nonce"])).encode()
    assert key.sign(as_a_verify) != minting["signature"]


def test_every_request_carries_a_fresh_nonce(tmp_path, monkeypatch):
    """Two mints in the same second must still be two distinct requests."""
    endpoint = Endpoint({"token": {"token": "ghs_x"}})
    connector, _, _ = connected(tmp_path, monkeypatch, endpoint)

    connector.mint(7)
    connector.mint(7)

    nonces = [sent["nonce"] for leaf, sent in endpoint.sent if leaf == "token"]

    assert len(nonces) == 2
    assert nonces[0] != nonces[1]
    assert all(len(one) >= 16 for one in nonces)   # the Worker's floor


def test_a_request_carries_a_timestamp_the_worker_can_judge(tmp_path,
                                                            monkeypatch):
    endpoint = Endpoint({"token": {"token": "ghs_x"}})
    connector, _, _ = connected(tmp_path, monkeypatch, endpoint)

    connector.mint(7)
    sent = endpoint.body("token")

    assert isinstance(sent["timestamp"], int)
    assert abs(sent["timestamp"] - int(time.time())) < 5


def test_the_signature_is_over_exactly_the_bytes_the_worker_rebuilds(
        tmp_path, monkeypatch):
    """The layout is the contract between the two halves.

    Both sides join with a newline, in this order, with this prefix. This test
    spells the layout out literally rather than importing the helper, so a
    change to one side that silently changes the other is caught here instead
    of at the first real request.
    """
    endpoint = Endpoint({"token": {"token": "ghs_x"}})
    connector, _, key = connected(tmp_path, monkeypatch, endpoint)

    connector.mint(7)
    sent = endpoint.body("token")

    expected = "\n".join(("comodor-github-v1", "token", sent["grant"],
                          str(sent["timestamp"]), sent["nonce"])).encode()

    assert sent["signature"] == key.sign(expected)


def test_the_grant_decides_the_installation_not_the_argument(tmp_path,
                                                             monkeypatch):
    """Two connections, and a mint for one must never carry the other's grant.

    This is the mismatch case from the other side: the Worker reads the id out
    of the grant, so sending the wrong grant would mint for the wrong account.
    """
    endpoint = Endpoint({"token": {"token": "ghs_x"}})
    connector, config, _ = connected(tmp_path, monkeypatch, endpoint)

    other = identity.generate()
    identity.save(config.paths.user, 9, other)
    config.github.remember(GitHubInstallation(
        installation_id=9, account_id=2, account_login="comodor-ai",
        account_type="Organization", grant="g2.the-other-grant.sig"))

    connector.mint(9)

    assert endpoint.body("token")["grant"] == "g2.the-other-grant.sig"


def test_each_connection_signs_with_its_own_key(tmp_path, monkeypatch):
    """One machine's two connections are two identities. A key that signed for
    one must not be able to speak for the other."""
    endpoint = Endpoint({"token": {"token": "ghs_x"}})
    connector, config, first = connected(tmp_path, monkeypatch, endpoint)

    second = identity.generate()
    identity.save(config.paths.user, 9, second)
    config.github.remember(GitHubInstallation(
        installation_id=9, account_login="comodor-ai", grant="g2.other.sig"))

    assert first.public != second.public
    assert identity.key_path(config.paths.user, 7) \
        != identity.key_path(config.paths.user, 9)


# --------------------------------------------------------------------------- #
# the flow that establishes all of it
# --------------------------------------------------------------------------- #


def test_connecting_sends_the_public_key_and_never_the_private_one(tmp_path,
                                                                   monkeypatch):
    endpoint = Endpoint({"install": {
        "state": "comodor.abc.def", "nonce": "the-nonce",
        "url": "https://github.com/apps/comodor/installations/new?state=x",
        "expires_in": 900}})
    config = a_home(tmp_path, monkeypatch)
    monkeypatch.setattr("comodor.net.http.post", endpoint.post)

    pending = Connector(config).begin()
    sent = endpoint.body("install")

    assert sent["public_key"] == pending.key.public
    assert str(pending.key.private) not in json.dumps(sent)
    assert f"{pending.key.private:064x}" not in json.dumps(sent)


def test_an_abandoned_flow_leaves_no_key_on_disk(tmp_path, monkeypatch):
    """A browser closed, a receipt never pasted. Nothing should be left."""
    endpoint = Endpoint({"install": {
        "state": "s", "nonce": "n",
        "url": "https://github.com/apps/x/installations/new"}})
    config = a_home(tmp_path, monkeypatch)
    monkeypatch.setattr("comodor.net.http.post", endpoint.post)

    Connector(config).begin()

    assert not (config.paths.user / "github").exists()


def test_completing_a_flow_stores_the_grant_and_the_key(tmp_path, monkeypatch):
    endpoint = Endpoint({"claim": {
        "status": "connected", "nonce": "mine", "grant": "g2.issued.sig",
        "installation": {"installation_id": 11,
                         "account": {"id": 1, "login": "ifekri",
                                     "type": "User"}}}})
    config = a_home(tmp_path, monkeypatch)
    monkeypatch.setattr("comodor.net.http.post", endpoint.post)

    key = identity.generate()
    pending = Pending(state="s", nonce="mine", url="https://x",
                      expires_at=time.time() + 900, key=key)
    found = Connector(config).collect(pending, "a-receipt")

    assert found.grant == "g2.issued.sig"
    assert found.usable
    assert identity.load(config.paths.user, 11).public == key.public


def test_a_completed_flow_with_no_grant_saves_nothing(tmp_path, monkeypatch):
    """A Worker that verified the installation but issued no grant leaves this
    machine unable to prove the connection is its own. Recording it would
    produce a connection that reads as working and fails at first use."""
    endpoint = Endpoint({"claim": {
        "status": "connected", "nonce": "mine",
        "installation": {"installation_id": 11,
                         "account": {"id": 1, "login": "ifekri",
                                     "type": "User"}}}})
    config = a_home(tmp_path, monkeypatch)
    monkeypatch.setattr("comodor.net.http.post", endpoint.post)

    pending = Pending(state="s", nonce="mine", url="https://x",
                      expires_at=time.time() + 900, key=identity.generate())

    with pytest.raises(ConnectError) as caught:
        Connector(config).collect(pending, "a-receipt")

    assert "no grant" in str(caught.value)
    assert not (config.paths.user / "github").exists()


def test_disconnecting_removes_the_private_key(tmp_path, monkeypatch):
    """The one piece of this connection that is actually secret must not sit
    on disk after the person asked for the connection to be gone."""
    endpoint = Endpoint({"disconnect": {"status": "forgotten"}})
    connector, config, _ = connected(tmp_path, monkeypatch, endpoint)
    assert identity.key_path(config.paths.user, 7).exists()

    connector.disconnect(7)

    assert not identity.key_path(config.paths.user, 7).exists()


def test_disconnecting_removes_the_key_even_when_the_server_is_unreachable(
        tmp_path, monkeypatch):
    endpoint = Endpoint({})
    connector, config, _ = connected(tmp_path, monkeypatch, endpoint)

    def refuse(url, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr("comodor.net.http.post", refuse)
    connector.disconnect(7)

    assert not identity.key_path(config.paths.user, 7).exists()


def test_disconnecting_something_with_no_grant_still_removes_the_key(
        tmp_path, monkeypatch):
    """`_signed` raises when there is no grant. That must not stop the local
    removal - a person disconnecting is not asking permission."""
    config = a_home(tmp_path, monkeypatch)
    monkeypatch.setattr("comodor.net.http.post", Endpoint({}).post)
    identity.save(config.paths.user, 7, identity.generate())

    Connector(config).disconnect(7)

    assert not identity.key_path(config.paths.user, 7).exists()


# --------------------------------------------------------------------------- #
# what a stale record looks like
# --------------------------------------------------------------------------- #


def test_a_record_without_a_grant_is_not_usable():
    """A leftover from before grants existed reads fine and fails at first
    use. `usable` is how `status` says so up front instead."""
    assert not GitHubInstallation(installation_id=7).usable
    assert GitHubInstallation(installation_id=7, grant="g2.x.y").usable


def test_a_grant_from_before_the_actor_was_named_is_not_usable():
    """A `g1.` grant says which key owns which installation and no more.

    The endpoint cannot tell from one whether the person who made the
    connection still has access, so it refuses them. Reporting that here means
    `comodor github status` says "reconnect" rather than the refusal arriving
    in the middle of a turn.
    """
    assert not GitHubInstallation(installation_id=7, grant="g1.old.sig").usable


def test_refreshing_permissions_does_not_drop_the_grant():
    """`verify` returns current permissions and no grant. Replacing the record
    with it must not silently break the connection it just confirmed."""
    config = Config()
    config.github.remember(GitHubInstallation(
        installation_id=7, account_login="ifekri", grant="g2.kept.sig"))

    config.github.remember(GitHubInstallation(
        installation_id=7, account_login="ifekri",
        permissions={"contents": "read"}))

    found = config.github.find_by_id(7)
    assert found.grant == "g2.kept.sig"
    assert found.permissions == {"contents": "read"}


def test_reconnecting_replaces_the_grant_rather_than_keeping_the_old_one():
    """`connect` writes a new key over the old one. A record still naming the
    previous grant would sign with a key that grant does not name."""
    config = Config()
    config.github.remember(GitHubInstallation(
        installation_id=7, grant="g1.old.sig"))

    config.github.remember(GitHubInstallation(
        installation_id=7, grant="g2.new.sig"))

    assert config.github.find_by_id(7).grant == "g2.new.sig"


def test_a_grant_is_written_to_the_config_and_read_back(tmp_path, monkeypatch):
    """It has to survive the round trip, or every connection breaks on the
    next run. This is the `list[dataclass]` path, which nothing else uses."""
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path))
    from comodor.paths import resolve as resolve_paths

    config = Config(paths=resolve_paths(tmp_path))
    config.github.remember(GitHubInstallation(
        installation_id=7, account_login="ifekri", grant="g2.persisted.sig"))
    config.save()

    from comodor.config import load
    back = load(tmp_path)

    assert back.github.find_by_id(7).grant == "g2.persisted.sig"


# --------------------------------------------------------------------------- #
# helpers used by the vector above
# --------------------------------------------------------------------------- #


def _public_of(private: int) -> str:
    x, y = identity._multiply(private, (identity._GX, identity._GY))
    return identity._b64(b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big"))
