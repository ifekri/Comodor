"""Connecting without anybody copying anything.

The normal path used to end with a person reading a signed line out of a
browser and typing it into a terminal. These tests are mostly about proving
that path is gone: nothing reads stdin, nothing asks for a receipt, and the
two-hundred-and-seventy-character URL is never printed where it can wrap.

Everything here is offline. The Worker is a stub that answers the way the real
one does, and time is injected — a test that slept for a fifteen-minute expiry
would be a test nobody runs.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from rich.console import Console

from comodor.config import Config
from comodor.github import commands, connect
from comodor.github.connect import (
    CLAIM_ACTION,
    FLOW_SCHEME,
    PROTOCOL,
    PROTOCOL_RECEIPT,
    ConnectError,
    Connector,
    Pending,
)
from comodor.terminal import theme as theme_module

URL = ("https://github.com/apps/comodor-agent/installations/new"
       "?state=comodor." + "x" * 240 + ".yyyy")


# --------------------------------------------------------------------------- #
# a Worker that answers the way the real one does
# --------------------------------------------------------------------------- #


class Worker:
    """The endpoint, offline. Records what it was asked."""

    def __init__(self, *, protocol: int = PROTOCOL,
                 answers: list[dict[str, Any]] | None = None) -> None:
        self.protocol = protocol
        self.answers = list(answers or [])
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.asked.append((path, body))
        if path == "install":
            return {"state": "comodor.a-state", "nonce": "a-nonce",
                    "url": URL, "expires_in": 900, "protocol": self.protocol}
        if path == "claim":
            return self.answers.pop(0) if self.answers else {"status": "pending"}
        raise AssertionError(f"unexpected call to {path}")


def connector(config: Config, worker: Worker) -> Connector:
    made = Connector(config)
    made._post = worker            # type: ignore[method-assign]
    return made


def connected(installation_id: int = 42) -> dict[str, Any]:
    return {
        "status": "connected",
        "nonce": "a-nonce",
        "grant": "g1.a-grant",
        "installation": {
            "installation_id": installation_id,
            "account": {"login": "ifekri", "id": 1, "type": "User"},
            "repository_selection": "selected",
            "permissions": {"contents": "read"},
        },
    }


@pytest.fixture
def worker() -> Worker:
    return Worker()


# --------------------------------------------------------------------------- #
# the flow
# --------------------------------------------------------------------------- #


def test_the_agent_asks_for_the_automatic_protocol(config, worker):
    connector(config, worker).begin()

    _, body = worker.asked[0]
    assert body["protocol"] == PROTOCOL
    assert body["public_key"], "the flow is bound to a key from the start"


def test_it_takes_the_protocol_the_worker_agreed_to(config):
    """Which may be less than was asked for. An older deployment cannot hold a
    result, and polling one that never will is a terminal that hangs."""
    older = Worker(protocol=PROTOCOL_RECEIPT)

    pending = connector(config, older).begin()

    assert pending.protocol == PROTOCOL_RECEIPT
    assert not pending.automatic


def test_a_flow_the_terminal_can_finish_says_so(config, worker):
    assert connector(config, worker).begin().automatic


def test_it_polls_until_the_browser_finishes(config):
    """Three passes: waiting, waiting, connected. The person does nothing."""
    worker = Worker(answers=[{"status": "pending"}, {"status": "pending"},
                             connected()])
    slept: list[float] = []
    made = connector(config, worker)
    pending = made.begin()

    installation = made.wait_for(pending, sleep=slept.append)

    assert installation.account_login == "ifekri"
    assert installation.grant == "g1.a-grant"
    assert len(slept) == 2, "it slept between polls rather than spinning"


def test_every_poll_is_signed_by_the_key_that_started_the_flow(config):
    """A state travels in a URL and its nonce is readable inside it, so
    knowing the flow must not be enough to collect its grant."""
    worker = Worker(answers=[connected()])
    made = connector(config, worker)
    pending = made.begin()

    made.wait_for(pending, sleep=lambda _: None)

    _, poll = worker.asked[-1]
    assert poll["state"] == pending.state
    assert poll["signature"], "an unsigned poll is a state anybody can present"
    assert poll["timestamp"] and poll["nonce"]
    assert "receipt" not in poll


def test_what_the_poll_signs_covers_everything_that_could_change_the_answer(config):
    """Verified against the key itself, the way the Worker verifies it."""
    worker = Worker(answers=[connected()])
    made = connector(config, worker)
    pending = made.begin()
    made.wait_for(pending, sleep=lambda _: None)

    _, poll = worker.asked[-1]
    message = "\n".join((FLOW_SCHEME, CLAIM_ACTION, poll["state"],
                         str(poll["timestamp"]), poll["nonce"]))

    # Signing the same bytes again reproduces the signature, because the
    # scheme is deterministic (RFC 6979). Different bytes do not — which is
    # what proves the poll covers those fields rather than merely carrying
    # them alongside a signature over something else.
    assert pending.key.sign(message.encode()) == poll["signature"]
    assert pending.key.sign(b"something else") != poll["signature"]


def test_two_polls_are_not_the_same_request(config):
    """A per-request nonce, so a captured poll is one request rather than a
    template."""
    worker = Worker(answers=[{"status": "pending"}, connected()])
    made = connector(config, worker)
    pending = made.begin()
    made.wait_for(pending, sleep=lambda _: None)

    polls = [body for path, body in worker.asked if path == "claim"]
    assert polls[0]["nonce"] != polls[1]["nonce"]
    assert polls[0]["signature"] != polls[1]["signature"]


# --------------------------------------------------------------------------- #
# what the Worker can say
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status,said", [
    ("cancelled", "cancelled"),
    ("expired", "expired"),
    # The message says what happened rather than repeating the wire status:
    # "the endpoint said failed" is a word from a protocol, not an answer.
    ("failed", "not completed"),
    ("not_permitted", "yours to connect"),
])
def test_a_flow_that_did_not_connect_says_which(config, status, said):
    worker = Worker(answers=[{"status": status}])
    made = connector(config, worker)
    pending = made.begin()

    with pytest.raises(ConnectError, match=said):
        made.wait_for(pending, sleep=lambda _: None)


def test_a_result_from_another_flow_is_refused(config):
    """The Worker proves the answer is one it issued; the nonce proves it
    belongs to this attempt."""
    stray = connected()
    stray["nonce"] = "somebody-elses-nonce"
    worker = Worker(answers=[stray])
    made = connector(config, worker)
    pending = made.begin()

    with pytest.raises(ConnectError, match="different connection attempt"):
        made.wait_for(pending, sleep=lambda _: None)


def test_a_connection_with_no_grant_is_refused(config):
    """Without one this machine cannot prove the connection is its own, and a
    connection it cannot prove is one it must not record."""
    ungranted = connected()
    ungranted["grant"] = ""
    worker = Worker(answers=[ungranted])
    made = connector(config, worker)
    pending = made.begin()

    with pytest.raises(ConnectError, match="no grant"):
        made.wait_for(pending, sleep=lambda _: None)


def test_nothing_is_written_until_a_result_checks_out(config):
    """An abandoned flow leaves no key on disk."""
    worker = Worker(answers=[{"status": "cancelled"}])
    made = connector(config, worker)
    pending = made.begin()

    with pytest.raises(ConnectError):
        made.wait_for(pending, sleep=lambda _: None)

    keys = list((config.paths.user / "github").glob("*")) \
        if (config.paths.user / "github").exists() else []
    assert not keys, f"an unfinished flow left {keys}"


# --------------------------------------------------------------------------- #
# giving up, without sleeping through it
# --------------------------------------------------------------------------- #


def test_it_stops_at_the_deadline_the_worker_gave(config):
    """The clock is injected. A test that waited out a fifteen-minute expiry
    is a test that gets marked slow and then skipped."""
    worker = Worker()                      # always pending
    made = connector(config, worker)
    pending = made.begin()

    ticks = iter([0.0, 300.0, 600.0, 901.0, 902.0, 903.0])
    with pytest.raises(ConnectError, match="in time"):
        made.wait_for(pending, sleep=lambda _: None, now=lambda: next(ticks))


def test_the_deadline_is_the_servers_and_not_a_second_copy(config):
    """A lifetime written on this side too would drift the moment the
    server's changed."""
    worker = Worker()
    worker_pending = connector(config, worker).begin()

    assert 890 < worker_pending.seconds_left <= 900


def test_a_flow_the_terminal_cannot_finish_refuses_to_be_waited_on(config):
    made = connector(config, Worker(protocol=PROTOCOL_RECEIPT))
    pending = made.begin()

    with pytest.raises(ConnectError, match="not one the terminal can finish"):
        made.wait_for(pending, sleep=lambda _: None)


# --------------------------------------------------------------------------- #
# what the terminal shows
# --------------------------------------------------------------------------- #


def drawn(width: int = 100, *, opened: bool = True, clipboard_works: bool = True,
          clipboard_raises: bool = False, monkeypatch=None) -> str:
    from comodor.terminal import clipboard as clip

    # The product's own theme, because the panel asks for styles by name and a
    # bare console does not have them.
    console = Console(width=width, force_terminal=True, color_system="truecolor",
                      legacy_windows=False,
                      theme=theme_module.load("cyan").rich_theme())

    def copy(text: str) -> str:
        if clipboard_raises:
            raise OSError("no clipboard here")
        return "the terminal (OSC 52)" if clipboard_works else ""

    monkeypatch.setattr(clip, "available", lambda: clipboard_works)
    monkeypatch.setattr(clip, "copy", copy)

    with console.capture() as caught:
        commands._offer_the_link(console, URL, opened)
    return caught.get()


#: An OSC 8 hyperlink: `ESC ] 8 ; params ; URI ST`, once to open the link and
#: once with an empty URI to close it.
OSC = re.compile(r"\x1b\]8;[^;]*;[^\x1b\x07]*(?:\x1b\\|\x07)")
CSI = re.compile(r"\x1b\[[0-9;:?]*[a-zA-Z]")


def plain(text: str) -> str:
    """What the terminal shows, in cells.

    Stripping only CSI would leave the hyperlink escapes in — and the URL is
    inside one of those, so a row measured that way comes out four hundred
    cells wide and every width assertion fails on a panel that is perfectly
    fine. That is the mistake this function exists in order not to make.
    """
    return CSI.sub("", OSC.sub("", text))


def test_the_normal_path_never_prints_the_long_url(monkeypatch):
    """It is two hundred and seventy characters of signed state. Printed, it
    wraps across four lines of an eighty-column terminal and cannot be clicked
    anyway."""
    out = plain(drawn(monkeypatch=monkeypatch))

    assert out.count(URL) == 0
    assert "Open GitHub installation page" in out


def test_the_short_label_is_really_the_link(monkeypatch):
    """Not a visible string that looks like one. OSC 8 is what makes a word
    clickable, and a test that only checked the words would pass on a panel
    that had lost the hyperlink."""
    raw = drawn(monkeypatch=monkeypatch)

    assert "\x1b]8;;" in raw, "no OSC 8 hyperlink was emitted"
    assert URL in raw, "the escape must carry the real URL"
    assert plain(raw).count(URL) == 0, "and only inside the escape"


def test_the_link_style_carries_the_url():
    """At the Text level, so a change to the panel cannot quietly drop it."""
    text = commands._link(URL, "Open GitHub installation page")

    assert str(text) == "Open GitHub installation page"
    assert f"link {URL}" in str(text.style)


def test_the_url_is_copied_when_the_clipboard_works(monkeypatch):
    out = plain(drawn(monkeypatch=monkeypatch))

    assert "copied to clipboard" in out
    assert out.count(URL) == 0, "copying it is not a reason to print it too"


def unfolded(panel: str) -> str:
    """The panel's text with its borders and its line breaks taken out.

    A URL long enough to need this fallback is also long enough to fold across
    four rows, so it is not a contiguous string in the output. Counting it
    without rejoining the rows gives zero and reads like the URL is missing —
    which is a test measuring the box rather than the content.
    """
    body = []
    for row in panel.splitlines():
        body.append(row.strip("│╭╮╰╯─ "))
    return "".join(body)


def test_the_url_is_shown_once_when_nothing_else_can_reach_it(monkeypatch):
    """No browser and no clipboard. The full URL appears — exactly once."""
    out = plain(drawn(opened=False, clipboard_works=False,
                      monkeypatch=monkeypatch))

    assert unfolded(out).count(URL) == 1
    assert "Copy this into a browser" in out
    # Folded rather than cropped: every character has to be readable, which is
    # the whole reason this block exists.
    assert "…" not in out and "..." not in out


def test_a_clipboard_that_fails_does_not_take_the_command_with_it(monkeypatch):
    out = plain(drawn(opened=False, clipboard_raises=True,
                      monkeypatch=monkeypatch))

    assert "Open GitHub installation page" in out


@pytest.mark.parametrize("width", [160, 120, 100, 80, 60])
def test_the_panel_fits_every_terminal(width, monkeypatch):
    """The URL is what used to make this impossible: at sixty columns it is
    five wrapped lines and the panel is a wall."""
    out = drawn(width, monkeypatch=monkeypatch)
    rows = plain(out).splitlines()

    assert rows
    for row in rows:
        assert len(row.rstrip()) <= width, f"{len(row)} cells in {width}"


@pytest.mark.parametrize("width", [160, 120, 100, 80, 60])
def test_the_fallback_fits_too(width, monkeypatch):
    """It prints the URL, so it is the case that has to fold rather than
    overflow."""
    out = drawn(width, opened=False, clipboard_works=False,
                monkeypatch=monkeypatch)

    for row in plain(out).splitlines():
        assert len(row.rstrip()) <= width, f"{len(row)} cells in {width}"


# --------------------------------------------------------------------------- #
# nobody is asked to paste anything
# --------------------------------------------------------------------------- #


def test_the_successful_path_never_reads_from_the_terminal(config, monkeypatch):
    """The whole point. `input()` is replaced by something that fails the test
    if it is reached."""
    import builtins

    monkeypatch.setattr(builtins, "input", lambda *a, **k: pytest.fail(
        "the normal path asked somebody to type something"))

    worker = Worker(answers=[connected()])
    made = connector(config, worker)
    monkeypatch.setattr(Connector, "open", lambda self, pending: True)
    monkeypatch.setattr(connect, "Connector", lambda cfg: made)

    console = Console(width=100, force_terminal=False,
                      theme=theme_module.load("cyan").rich_theme())
    code = commands._connect(console, config)

    assert code == 0
    assert config.github.enabled
    assert not any("receipt" in body for _, body in worker.asked)


def test_the_older_flow_still_asks_when_the_worker_cannot_hold_a_result(
        config, monkeypatch):
    """A deployment can be behind this client. Being handed a receipt with
    nowhere to put it is worse than being asked for one."""
    import builtins

    worker = Worker(protocol=PROTOCOL_RECEIPT, answers=[connected()])
    made = connector(config, worker)
    monkeypatch.setattr(Connector, "open", lambda self, pending: True)
    monkeypatch.setattr(connect, "Connector", lambda cfg: made)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "a-receipt")

    console = Console(width=100, force_terminal=False,
                      theme=theme_module.load("cyan").rich_theme())
    code = commands._connect(console, config)

    assert code == 0
    assert any(body.get("receipt") == "a-receipt"
               for path, body in worker.asked if path == "claim")


def test_ctrl_c_connects_nothing_and_says_so(config, monkeypatch, capsys):
    worker = Worker()
    made = connector(config, worker)
    monkeypatch.setattr(Connector, "open", lambda self, pending: True)
    monkeypatch.setattr(connect, "Connector", lambda cfg: made)
    monkeypatch.setattr(
        Connector, "wait_for",
        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))

    console = Console(width=100, force_terminal=False,
                      theme=theme_module.load("cyan").rich_theme())
    code = commands._connect(console, config)

    assert code == 1
    assert not config.github.enabled
    assert "Nothing was connected" in capsys.readouterr().out


def test_the_success_message_does_not_claim_more_than_was_granted(
        config, monkeypatch, capsys):
    worker = Worker(answers=[connected()])
    made = connector(config, worker)
    monkeypatch.setattr(Connector, "open", lambda self, pending: True)
    monkeypatch.setattr(connect, "Connector", lambda cfg: made)

    console = Console(width=100, force_terminal=False,
                      theme=theme_module.load("cyan").rich_theme())
    commands._connect(console, config)
    out = capsys.readouterr().out

    assert "ifekri" in out
    assert "selected" in out.lower(), "it said which repositories"
    # The receipt, the grant and the state are not for reading.
    assert "g1.a-grant" not in out
    assert "comodor.a-state" not in out


def test_a_pending_flow_knows_whether_it_has_expired():
    """Nothing here sleeps; the deadline is a number."""
    import time

    assert Pending(state="s", nonce="n", url=URL,
                   expires_at=time.time() - 1).expired
    assert not Pending(state="s", nonce="n", url=URL,
                       expires_at=time.time() + 60).expired


def test_the_flow_scheme_is_not_the_grant_scheme():
    """Two signing schemes that share a prefix are two schemes one of which
    can be presented as the other."""
    assert FLOW_SCHEME != "comodor-github-v1"
    assert not FLOW_SCHEME.startswith("comodor-github-v1\n")
    assert connect.SEPARATOR == "\n"


# --------------------------------------------------------------------------- #
# a flow is not thrown away by one bad request
# --------------------------------------------------------------------------- #


class Flaky:
    """A Worker that fails a few times and then answers."""

    def __init__(self, failures: list[Exception], then: dict[str, Any]) -> None:
        self.failures = list(failures)
        self.then = then
        self.polls = 0

    def __call__(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path == "install":
            return {"state": "comodor.a-state", "nonce": "a-nonce",
                    "url": URL, "expires_in": 900, "protocol": PROTOCOL}
        self.polls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.then


@pytest.mark.parametrize("problem", [
    ConnectError("could not reach comodor.ai: timed out"),          # no answer
    ConnectError("comodor.ai refused: 502", status=502),
    ConnectError("comodor.ai refused: 429", status=429),
    ConnectError("comodor.ai refused: 503", status=503),
])
def test_a_transient_failure_does_not_throw_the_flow_away(config, problem):
    """Hundreds of polls over fifteen minutes; one dropped connection or one
    edge returning 502 must not discard an authorisation the browser may
    already have completed."""
    worker = Flaky([problem], connected())
    made = Connector(config)
    made._post = worker            # type: ignore[method-assign]
    pending = made.begin()

    installation = made.wait_for(pending, sleep=lambda _: None)

    assert installation.account_login == "ifekri"
    assert worker.polls == 2, "it tried again"


@pytest.mark.parametrize("status", [400, 401, 403, 409])
def test_a_refusal_stops_rather_than_being_retried(config, status):
    """Asking again would be refused again."""
    worker = Flaky([ConnectError(f"refused: {status}", status=status)],
                   connected())
    made = Connector(config)
    made._post = worker            # type: ignore[method-assign]
    pending = made.begin()

    with pytest.raises(ConnectError, match="refused"):
        made.wait_for(pending, sleep=lambda _: None)

    assert worker.polls == 1, "a refusal must not be retried"


def test_giving_up_after_repeated_trouble_says_what_the_trouble_was(config):
    """Rather than reporting a timeout when every attempt was refused by the
    network."""
    worker = Flaky([ConnectError("could not reach comodor.ai: timed out")] * 10,
                   connected())
    made = Connector(config)
    made._post = worker            # type: ignore[method-assign]
    pending = made.begin()

    ticks = iter([0.0, 100.0, 500.0, 901.0, 902.0, 903.0])
    with pytest.raises(ConnectError, match="gave up waiting.*timed out"):
        made.wait_for(pending, sleep=lambda _: None, now=lambda: next(ticks))


def test_an_error_knows_whether_asking_again_could_help():
    assert ConnectError("no answer").transient
    assert ConnectError("busy", status=429).transient
    assert ConnectError("bad gateway", status=502).transient
    assert not ConnectError("nope", status=401).transient
    assert not ConnectError("gone", status=404).transient


# --------------------------------------------------------------------------- #
# a browser that ends without connecting ends the wait
# --------------------------------------------------------------------------- #


def test_a_refusal_in_the_browser_stops_the_terminal_waiting(config):
    """It used to hear `pending` until the state expired, fifteen minutes
    after the browser had definitively finished."""
    worker = Worker(answers=[{"status": "not_permitted",
                              "reason": "not entitled to connect this installation"}])
    made = connector(config, worker)
    pending = made.begin()

    with pytest.raises(ConnectError, match="not yours to connect|not entitled"):
        made.wait_for(pending, sleep=lambda _: None)


def test_an_abandoned_authorisation_stops_the_terminal_waiting(config):
    worker = Worker(answers=[{"status": "failed",
                              "reason": "authorisation was not completed"}])
    made = connector(config, worker)
    pending = made.begin()

    with pytest.raises(ConnectError, match="not completed"):
        made.wait_for(pending, sleep=lambda _: None)
