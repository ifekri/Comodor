"""GitHub as a provider: installations, tokens, and what may touch a repository.

Nothing here needs a GitHub account, a network, or a credential. The private
key does not exist on this side at all — it is a Cloudflare secret the Worker
holds — so the only thing to stand in for is HTTP, and these tests do that at
the one function that makes a request.

What is worth checking, in the order the risk runs:

* an installation id from a query string is never treated as verified;
* a token is short-lived, cached, refreshed, and never written to disk;
* a repository resolves to exactly one installation, and a missing permission
  is a sentence rather than a 403 four calls later;
* everything read out of GitHub is labelled as data, because an issue body is
  written by whoever could open one.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from comodor.config import Config, GitHubConfig, GitHubInstallation
from comodor.github import identity
from comodor.github.api import (
    GitHub,
    GitHubError,
    RateLimited,
    Refused,
    _next_page,
    _rate_limit_wait,
)
from comodor.github.connect import ConnectError, Connector, Pending
from comodor.github.repos import Repositories, branch_name, split
from comodor.github.tokens import InstallationToken, TokenError, Tokens, redact
from comodor.paths import resolve as resolve_paths

# --------------------------------------------------------------------------- #
# standing in for HTTP
# --------------------------------------------------------------------------- #


class Answer:
    """What the project's HTTP client returns, in the parts this reads."""

    def __init__(self, status: int = 200, body: Any = None,
                 headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.content = json.dumps(body if body is not None else {}).encode()
        self.headers = headers or {}


def a_token(seconds: float = 3600, installation: int = 1) -> InstallationToken:
    return InstallationToken(token="ghs_pretend",
                             expires_at=time.time() + seconds,
                             installation_id=installation)


def an_installation(**over: Any) -> GitHubInstallation:
    fields: dict[str, Any] = {
        "installation_id": 1, "account_id": 99, "account_login": "ifekri",
        "account_type": "User", "repository_selection": "selected",
        "permissions": {"metadata": "read", "contents": "write",
                        "pull_requests": "write", "issues": "write",
                        "checks": "read", "actions": "read"},
        "created_at": 1.0, "updated_at": 1.0,
    }
    fields.update(over)
    return GitHubInstallation(**fields)


# --------------------------------------------------------------------------- #
# the installation record
# --------------------------------------------------------------------------- #


def test_an_installation_survives_being_written_and_read(tmp_path, monkeypatch):
    """`list[GitHubInstallation]` is a shape nothing else in the config had.

    Loading gave back a list of dicts, and the first attribute access raised
    `AttributeError` from wherever it happened to be read — which is a long
    way from the line that caused it.
    """
    from comodor.config import Paths, load

    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    (work / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setenv("COMODOR_HOME", str(home))

    first = Config(paths=Paths(user=home, project=work))
    first.github.enabled = True
    first.github.remember(an_installation())
    first.save()

    back = load(cwd=work, use_environment=False)

    assert isinstance(back.github.installations[0], GitHubInstallation)
    assert back.github.find("ifekri").installation_id == 1


def test_more_than_one_installation_is_the_normal_case():
    """A personal account and two organisations is three, and a repository
    resolves to exactly one of them."""
    settings = GitHubConfig()
    settings.remember(an_installation(installation_id=1, account_login="ifekri"))
    settings.remember(an_installation(installation_id=2,
                                      account_login="comodor-ai",
                                      account_type="Organization"))

    assert len(settings.installations) == 2
    assert settings.find("comodor-ai").installation_id == 2
    assert settings.find("ifekri").installation_id == 1
    assert settings.find("nobody") is None


def test_reconnecting_replaces_rather_than_appends():
    """The same installation with wider permissions is the same installation.
    Appending would leave the narrower one to be found first."""
    settings = GitHubConfig()
    settings.remember(an_installation(permissions={"contents": "read"}))
    settings.remember(an_installation(permissions={"contents": "write"}))

    assert len(settings.installations) == 1
    assert settings.installations[0].permissions["contents"] == "write"


def test_reconnecting_keeps_when_it_was_first_connected():
    settings = GitHubConfig()
    settings.remember(an_installation(created_at=100.0))
    settings.remember(an_installation(created_at=200.0))

    assert settings.installations[0].created_at == 100.0


def test_an_account_is_found_however_it_is_capitalised():
    """GitHub logins are case-insensitive and people type them either way."""
    settings = GitHubConfig()
    settings.remember(an_installation(account_login="Ifekri"))

    assert settings.find("ifekri") is not None
    assert settings.find("IFEKRI") is not None


def test_forgetting_one_says_whether_it_was_there():
    settings = GitHubConfig()
    settings.remember(an_installation())

    assert settings.forget(1) is True
    assert settings.forget(1) is False
    assert settings.installations == []


def test_a_permission_is_read_from_the_installation_not_assumed():
    """An installation can be narrower than the app asked for, and often is."""
    one = an_installation(permissions={"contents": "read", "issues": "write"})

    assert one.may("contents", "read") is True
    assert one.may("contents", "write") is False, "read does not imply write"
    assert one.may("issues", "read") is True, "write implies read"
    assert one.may("issues", "write") is True
    assert one.may("administration") is False, "a grant not given is not held"


def test_no_token_is_stored_on_the_installation():
    """A token in a config file outlives the session that fetched it and is
    readable by anything that can read the file."""
    written = json.dumps(an_installation().to_json())

    assert "token" not in written
    assert "ghs_" not in written


# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #


def test_a_token_is_fetched_once_and_reused():
    tokens = Tokens(lambda ident: a_token())

    first = tokens.for_installation(1)
    second = tokens.for_installation(1)

    assert first is second
    assert tokens.mints == 1, "a turn touching six files should mint once"


def test_a_token_near_its_expiry_is_replaced_before_it_fails():
    """It is checked here and used a moment later, over a network. A token
    with four seconds left passes the check and fails the request."""
    minted = []

    def mint(ident):
        minted.append(ident)
        return a_token(seconds=30)          # inside the margin

    tokens = Tokens(mint)
    tokens.for_installation(1)
    tokens.for_installation(1)

    assert len(minted) == 2, "a token about to expire was handed out again"


def test_each_installation_has_its_own_token():
    tokens = Tokens(lambda ident: a_token(installation=ident))

    assert tokens.for_installation(1).installation_id == 1
    assert tokens.for_installation(2).installation_id == 2
    assert tokens.mints == 2


def test_forgetting_a_token_makes_the_next_call_ask_again():
    """Called when GitHub refuses one — a revoked installation, a narrowed
    permission — so a rejected token is not replayed until it expires."""
    tokens = Tokens(lambda ident: a_token())
    tokens.for_installation(1)
    tokens.forget(1)
    tokens.for_installation(1)

    assert tokens.mints == 2


def test_a_mint_that_returns_nothing_is_an_error_not_an_empty_token():
    tokens = Tokens(lambda ident: None)

    with pytest.raises(TokenError):
        tokens.for_installation(1)


def test_two_threads_wanting_the_same_token_mint_once():
    """Both would otherwise ask, and GitHub counts both against the limit for
    a token only one of them keeps."""
    import threading

    slow = threading.Event()

    def mint(ident):
        slow.wait(2.0)
        return a_token()

    tokens = Tokens(mint)
    threads = [threading.Thread(target=lambda: tokens.for_installation(1))
               for _ in range(4)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)
    slow.set()
    for thread in threads:
        thread.join(timeout=5)

    assert tokens.mints == 1


def test_a_token_is_not_in_its_own_repr():
    """A dataclass prints its fields by default, and a stack trace carrying an
    installation token is a credential in a log file."""
    shown = repr(a_token())

    assert "ghs_pretend" not in shown
    assert "expires_in" in shown


@pytest.mark.parametrize("secret", [
    "ghs_16C7e42F292c6912E7710c838347Ae178B4a",
    "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
    "github_pat_11ABCDEFG0abcdefghijkl",
    "gho_16C7e42F292c6912E7710c838347Ae178B4a",
])
def test_a_credential_never_reaches_a_message(secret):
    assert secret not in redact(f"failed with {secret} while reading")
    assert "<redacted>" in redact(f"failed with {secret} while reading")


def test_a_jwt_never_reaches_a_message():
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxMjMifQ.signature"
    assert "eyJhbGciOiJSUzI1NiJ9" not in redact(f"sent {jwt}")


# --------------------------------------------------------------------------- #
# resolving a repository
# --------------------------------------------------------------------------- #


def a_config(**over: Any) -> Config:
    config = Config()
    config.github.enabled = True
    config.github.remember(an_installation(**over))
    return config


def test_a_repository_resolves_to_the_installation_covering_its_owner():
    repos = Repositories(a_config(), lambda ident: a_token())
    target = repos.resolve("ifekri/Comodor")

    assert target.owner == "ifekri"
    assert target.name == "Comodor"
    assert target.installation.installation_id == 1


def test_an_owner_with_no_installation_says_what_is_connected():
    repos = Repositories(a_config(), lambda ident: a_token())

    with pytest.raises(GitHubError) as caught:
        repos.resolve("somebody-else/thing")

    assert "ifekri" in str(caught.value), "it should say what *is* connected"
    assert "github connect" in str(caught.value)


@pytest.mark.parametrize("bad", [
    "not-a-repository", "../../etc/passwd", "owner/name/extra",
    "/leading", "trailing/", "", "owner/",
])
def test_a_name_that_is_not_owner_slash_name_is_refused(bad):
    """This string becomes a URL path. One carrying `..` or an extra slash
    addresses a different repository than the one written down."""
    with pytest.raises(GitHubError):
        split(bad)


def test_a_missing_permission_is_refused_before_anything_is_attempted():
    """Otherwise it surfaces as a 403 after a branch has been created, and the
    message names an endpoint rather than the setting to change."""
    repos = Repositories(a_config(permissions={"metadata": "read"}),
                         lambda ident: a_token())
    target = repos.resolve("ifekri/Comodor")

    with pytest.raises(Refused) as caught:
        repos.check(target, "open_pull_request")

    assert "pull_requests" in str(caught.value)
    assert "github.com/settings/installations" in str(caught.value), \
        "it should say where to widen it"


def test_a_granted_permission_passes():
    repos = Repositories(a_config(), lambda ident: a_token())
    target = repos.resolve("ifekri/Comodor")

    for operation in ("read", "write", "issues", "comment", "pulls",
                      "open_pull_request", "checks", "actions"):
        repos.check(target, operation)


def test_a_branch_is_named_for_what_opened_it():
    made = branch_name("comodor/", "fix", "The off-by-one in pagination!")

    assert made.startswith("comodor/fix-")
    assert " " not in made and "!" not in made
    assert ".." not in made


def test_a_branch_name_survives_a_subject_git_would_refuse():
    for subject in ("", "   ", "!!!", "a" * 200, "../../escape"):
        made = branch_name("comodor/", "change", subject)
        assert " " not in made
        assert ".." not in made
        assert not made.endswith("/")
        assert len(made) < 80


# --------------------------------------------------------------------------- #
# the API client
# --------------------------------------------------------------------------- #


def a_client(answers: list[Answer], monkeypatch) -> GitHub:
    """A `GitHub` whose HTTP layer is a list of prepared answers."""
    queue = list(answers)
    seen: list[tuple[str, str, dict]] = []

    def request(method, url, **kwargs):
        seen.append((method, url, kwargs))
        return queue.pop(0) if queue else Answer(500, {"message": "no answer"})

    monkeypatch.setattr("comodor.net.http.request", request)
    client = GitHub(lambda: a_token())
    client.seen = seen                     # for the assertions
    return client


def test_the_default_branch_is_read_rather_than_assumed(monkeypatch):
    """`main` is a default for new repositories and nothing more. Assuming
    produces a pull request against a branch that does not exist."""
    client = a_client([Answer(200, {"default_branch": "trunk"})], monkeypatch)

    assert client.default_branch("ifekri", "Comodor") == "trunk"


def test_a_repository_with_no_default_branch_is_an_error(monkeypatch):
    client = a_client([Answer(200, {})], monkeypatch)

    with pytest.raises(GitHubError):
        client.default_branch("ifekri", "Comodor")


def test_a_refusal_names_the_likely_cause(monkeypatch):
    client = a_client([Answer(404, {"message": "Not Found"})], monkeypatch)

    with pytest.raises(Refused) as caught:
        client.repository("ifekri", "Comodor")

    assert "permission" in str(caught.value)


def test_an_error_never_carries_a_token(monkeypatch):
    """GitHub does not put one in a response body, and this is the boundary
    where that stops being true if it ever is."""
    client = a_client(
        [Answer(500, {"message": "failed with ghs_16C7e42F292c6912E7710c8"})],
        monkeypatch)

    with pytest.raises(GitHubError) as caught:
        client.repository("ifekri", "Comodor")

    assert "ghs_16C7" not in str(caught.value)


def test_every_page_is_followed(monkeypatch):
    """GitHub returns thirty of anything by default and says so only in a
    header. Reading page one is right for small repositories and silently
    wrong for the ones where it matters."""
    first = Answer(200, [{"number": n} for n in range(100)],
                   {"link": '<https://api.github.com/x?page=2>; rel="next"'})
    second = Answer(200, [{"number": n} for n in range(100, 130)])
    client = a_client([first, second], monkeypatch)

    found = list(client.paged("repos/ifekri/Comodor/issues"))

    assert len(found) == 130


def test_pagination_stops_when_there_is_no_next(monkeypatch):
    client = a_client([Answer(200, [{"number": 1}])], monkeypatch)

    assert len(list(client.paged("x"))) == 1


def test_a_wrapped_list_is_unwrapped(monkeypatch):
    """`/installation/repositories` answers an object; `/issues` answers an
    array. One method, told which."""
    client = a_client(
        [Answer(200, {"repositories": [{"full_name": "ifekri/Comodor"}]})],
        monkeypatch)

    found = list(client.paged("installation/repositories", key="repositories"))

    assert found[0]["full_name"] == "ifekri/Comodor"


def test_the_next_link_is_read_from_the_header_github_sends():
    header = ('<https://api.github.com/x?page=2>; rel="next", '
              '<https://api.github.com/x?page=9>; rel="last"')
    assert _next_page(Answer(200, {}, {"link": header})).endswith("page=2")
    assert _next_page(Answer(200, {}, {})) == ""
    assert _next_page(Answer(200, {}, {"link": '<x>; rel="last"'})) == ""


def test_a_rate_limit_is_a_wait_not_a_failure():
    resets = time.time() + 30
    wait = _rate_limit_wait(Answer(403, {}, {
        "x-ratelimit-remaining": "0", "x-ratelimit-reset": str(resets)}))

    assert 25 < wait <= 30


def test_retry_after_is_honoured_when_github_sends_it():
    assert _rate_limit_wait(Answer(429, {}, {"retry-after": "12"})) == 12.0


def test_a_403_that_is_not_a_rate_limit_reads_as_a_permission(monkeypatch):
    client = a_client([Answer(403, {"message": "Resource not accessible"})],
                      monkeypatch)

    with pytest.raises(Refused):
        client.repository("ifekri", "Comodor")


def test_a_rate_limit_further_away_than_we_wait_is_reported(monkeypatch):
    resets = time.time() + 4000
    client = a_client([Answer(403, {}, {
        "x-ratelimit-remaining": "0", "x-ratelimit-reset": str(resets)})],
        monkeypatch)

    with pytest.raises(RateLimited) as caught:
        client.repository("ifekri", "Comodor")

    assert caught.value.resets_in > 3000


def test_a_url_with_a_query_is_not_recorded_whole(monkeypatch):
    """A query can carry a token; a path cannot."""
    client = a_client([Answer(200, {})], monkeypatch)
    client.call("GET", "https://api.github.com/x?token=secret")

    assert all("secret" not in path for _, path in client.calls)


# --------------------------------------------------------------------------- #
# connecting
# --------------------------------------------------------------------------- #


def a_connector(answers: dict[str, Any], monkeypatch, tmp_path=None,
                connected: int | None = None) -> Connector:
    """A connector talking to a stand-in Worker.

    `connected` sets up what a finished `comodor github connect` leaves
    behind: a grant in the config and a private key on disk. Anything that
    reaches `token`, `verify` or `disconnect` needs both, because those
    requests are signed - a test that skipped them would be exercising a path
    the product does not have.
    """
    def post(url, **kwargs):
        leaf = url.rstrip("/").rsplit("/", 1)[-1]
        found = answers.get(leaf)
        if isinstance(found, Answer):
            return found
        return Answer(200, found if found is not None else {})

    monkeypatch.setattr("comodor.net.http.post", post)

    if connected is None:
        return Connector(Config())

    monkeypatch.setenv("COMODOR_HOME", str(tmp_path))
    config = Config(paths=resolve_paths(tmp_path))
    identity.save(config.paths.user, connected, identity.generate())
    config.github.remember(GitHubInstallation(
        installation_id=connected, account_login="ifekri",
        grant=f"g1.grant-for-{connected}.sig"))
    return Connector(config)


def test_a_flow_starts_with_a_state_and_a_url(monkeypatch):
    connector = a_connector({"install": {
        "state": "comodor.abc.def", "nonce": "the-nonce",
        "url": "https://github.com/apps/comodor/installations/new?state=x",
        "expires_in": 900}}, monkeypatch)

    pending = connector.begin()

    assert pending.nonce == "the-nonce"
    assert pending.url.startswith("https://github.com/apps/")
    assert not pending.expired


def test_a_non_https_url_is_refused(monkeypatch):
    """This URL is opened in the person's browser."""
    connector = a_connector({"install": {
        "state": "s", "nonce": "n", "url": "http://evil.example/x"}},
        monkeypatch)

    with pytest.raises(ConnectError) as caught:
        connector.begin()

    assert "HTTPS" in str(caught.value)


def test_a_receipt_from_another_attempt_is_refused(monkeypatch):
    """The Worker proves the receipt is one it issued. Matching the nonce
    proves it belongs to *this* attempt."""
    connector = a_connector({"claim": {
        "status": "connected", "nonce": "somebody-elses",
        "installation": {"installation_id": 5,
                         "account": {"id": 1, "login": "x", "type": "User"}}}},
        monkeypatch)

    pending = Pending(state="s", nonce="mine", url="https://x",
                      expires_at=time.time() + 900, key=identity.generate())

    with pytest.raises(ConnectError) as caught:
        connector.collect(pending, "a-receipt")

    assert "different connection attempt" in str(caught.value)


def test_a_matching_receipt_becomes_an_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path))
    connector = a_connector({"claim": {
        "status": "connected", "nonce": "mine", "grant": "g1.issued.sig",
        "installation": {
            "installation_id": 7,
            "account": {"id": 42, "login": "comodor-ai",
                        "type": "Organization"},
            "repository_selection": "all",
            "permissions": {"contents": "write"}}}}, monkeypatch)
    connector.config = Config(paths=resolve_paths(tmp_path))

    pending = Pending(state="s", nonce="mine", url="https://x",
                      expires_at=time.time() + 900, key=identity.generate())
    found = connector.collect(pending, "a-receipt")

    assert found.installation_id == 7
    assert found.account_login == "comodor-ai"
    assert found.account_type == "Organization"
    assert found.repository_selection == "all"
    assert found.permissions == {"contents": "write"}


def test_a_cancelled_installation_is_not_an_installation(monkeypatch):
    connector = a_connector({"claim": {"status": "cancelled"}}, monkeypatch)
    pending = Pending(state="s", nonce="mine", url="https://x",
                      expires_at=time.time() + 900)

    with pytest.raises(ConnectError) as caught:
        connector.collect(pending, "a-receipt")

    assert "cancelled" in str(caught.value)


def test_an_installation_with_no_id_is_refused(monkeypatch):
    connector = a_connector({"claim": {
        "status": "connected", "nonce": "mine", "installation": {}}},
        monkeypatch)
    pending = Pending(state="s", nonce="mine", url="https://x",
                      expires_at=time.time() + 900)

    with pytest.raises(ConnectError):
        connector.collect(pending, "a-receipt")


def test_a_revoked_installation_comes_back_as_gone(tmp_path, monkeypatch):
    connector = a_connector({"verify": {"status": "gone"}}, monkeypatch,
                            tmp_path, connected=1)

    assert connector.verify(1) is None


def test_a_verified_installation_carries_its_current_permissions(tmp_path,
                                                                monkeypatch):
    connector = a_connector({"verify": {
        "status": "ok",
        "installation": {
            "installation_id": 1,
            "account": {"id": 1, "login": "ifekri", "type": "User"},
            "permissions": {"contents": "read"}}}}, monkeypatch,
        tmp_path, connected=1)

    found = connector.verify(1)

    assert found.permissions == {"contents": "read"}
    assert found.updated_at > 0


def test_a_refusal_from_the_endpoint_is_readable(tmp_path, monkeypatch):
    connector = a_connector(
        {"token": Answer(502, {"error": "GitHub answered 404"})}, monkeypatch,
        tmp_path, connected=1)

    with pytest.raises(ConnectError) as caught:
        connector.mint(1)

    assert "404" in str(caught.value)


def test_a_disconnect_that_cannot_reach_the_server_is_not_an_error(monkeypatch):
    """Somebody disconnecting because they no longer trust something should
    not be told the server is down."""
    def post(url, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr("comodor.net.http.post", post)
    Connector(Config()).disconnect(1)          # must not raise
