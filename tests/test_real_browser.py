"""A real browser, driven with nothing but the standard library.

Two halves. The protocol — a hand-written WebSocket and the CDP framing over it
— is checked against a real socket, because the bugs in that layer are frame
lengths and masking and they do not appear against a mock. The judgement — what
of a page is worth sending to a model — is checked without a browser at all, so
it runs on a machine that has none.

The tests that need Chrome say so and skip. CI has no browser; the design has
to survive that, and so does the suite.
"""

from __future__ import annotations

import json
import socket
import threading

import pytest

from comodor.browser import BrowserError
from comodor.browser.cdp import WebSocket
from comodor.browser.launch import find
from comodor.browser.page import Element, Snapshot

try:
    find()
    HAVE_BROWSER = True
except BrowserError:
    HAVE_BROWSER = False

needs_browser = pytest.mark.skipif(
    not HAVE_BROWSER, reason="no Chrome, Chromium, Edge or Brave on this machine")


# --------------------------------------------------------------------------- #
# the socket, against a real one
# --------------------------------------------------------------------------- #


class Peer:
    """A server that completes the handshake and then speaks frames."""

    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.received: list[str] = []
        self.conn: socket.socket | None = None
        self.ready = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        self.conn, _ = self.listener.accept()
        header = b""
        while b"\r\n\r\n" not in header:
            header += self.conn.recv(1)
        assert b"Sec-WebSocket-Key" in header
        self.conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\n"
                          b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        self.ready.set()

    def read_one(self) -> str:
        """Decode one masked client frame."""
        assert self.conn is not None
        first, second = self.conn.recv(2)
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(self.conn.recv(2), "big")
        elif length == 127:
            length = int.from_bytes(self.conn.recv(8), "big")
        assert second & 0x80, "a client must mask its frames"
        mask = self.conn.recv(4)
        body = b""
        while len(body) < length:
            body += self.conn.recv(length - len(body))
        return bytes(b ^ mask[i % 4] for i, b in enumerate(body)).decode()

    def write(self, text: str, opcode: int = 0x1, final: bool = True) -> None:
        assert self.conn is not None
        payload = text.encode()
        frame = bytearray([(0x80 if final else 0) | opcode])
        if len(payload) < 126:
            frame.append(len(payload))
        elif len(payload) < 65536:
            frame.append(126)
            frame += len(payload).to_bytes(2, "big")
        else:
            frame.append(127)
            frame += len(payload).to_bytes(8, "big")
        self.conn.sendall(bytes(frame) + payload)

    def stop(self) -> None:
        for sock in (self.conn, self.listener):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass


@pytest.fixture
def peer():
    server = Peer()
    yield server
    server.stop()


def test_the_handshake_and_a_round_trip(peer):
    ws = WebSocket(f"ws://127.0.0.1:{peer.port}/devtools/page/x")
    peer.ready.wait(5)
    try:
        ws.send('{"id":1}')
        assert peer.read_one() == '{"id":1}'

        peer.write('{"result":"ok"}')
        assert ws.receive() == '{"result":"ok"}'
    finally:
        ws.close()


def test_a_long_message_uses_the_wider_length_field(peer):
    """A payload over 125 bytes changes the frame header, and over 65535 it
    changes again. An accessibility tree is well into the third case."""
    ws = WebSocket(f"ws://127.0.0.1:{peer.port}/devtools/page/x")
    peer.ready.wait(5)
    try:
        for size in (200, 70_000):
            ws.send("x" * size)
            assert len(peer.read_one()) == size
    finally:
        ws.close()


def test_a_message_split_across_frames_is_reassembled(peer):
    """Chrome fragments large replies, and a client that reads one frame and
    calls it the answer gets a JSON parse error on a big page."""
    ws = WebSocket(f"ws://127.0.0.1:{peer.port}/devtools/page/x")
    peer.ready.wait(5)
    try:
        peer.write('{"a":', opcode=0x1, final=False)
        peer.write('1}', opcode=0x0, final=True)
        assert ws.receive() == '{"a":1}'
    finally:
        ws.close()


def test_a_ping_is_answered_and_not_returned_as_a_message(peer):
    ws = WebSocket(f"ws://127.0.0.1:{peer.port}/devtools/page/x")
    peer.ready.wait(5)
    try:
        peer.write("hello", opcode=0x9)          # ping
        peer.write('{"real":1}')
        assert ws.receive() == '{"real":1}'      # the ping did not surface
        assert peer.read_one() == "hello"        # and it was ponged
    finally:
        ws.close()


def test_a_refused_upgrade_is_a_clear_error():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def refuse():
        conn, _ = listener.accept()
        while b"\r\n\r\n" not in conn.recv(4096):
            pass
        conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        conn.close()

    threading.Thread(target=refuse, daemon=True).start()
    try:
        with pytest.raises(BrowserError) as raised:
            WebSocket(f"ws://127.0.0.1:{listener.getsockname()[1]}/x")
        assert "refused" in str(raised.value)
    finally:
        listener.close()


def test_a_browser_that_is_not_there_fails_rather_than_hangs():
    with pytest.raises(BrowserError):
        WebSocket("ws://127.0.0.1:1/devtools/page/x", timeout=2)


# --------------------------------------------------------------------------- #
# a reply and an event share the socket
# --------------------------------------------------------------------------- #


def test_events_arriving_before_a_reply_do_not_become_the_reply(peer):
    """A page fires events constantly. Reading the next frame and calling it
    the answer breaks the moment anything loads."""
    from comodor.browser.cdp import Session

    session = Session.__new__(Session)
    session._ws = WebSocket(f"ws://127.0.0.1:{peer.port}/devtools/page/x")
    session._id = 0
    session._lock = threading.Lock()
    session._events = []
    peer.ready.wait(5)
    try:
        def answer():
            peer.read_one()
            peer.write('{"method":"Page.loadEventFired","params":{}}')
            peer.write('{"method":"Network.requestWillBeSent","params":{}}')
            peer.write('{"id":1,"result":{"value":42}}')

        threading.Thread(target=answer, daemon=True).start()
        assert session.call("Runtime.evaluate", timeout=10)["value"] == 42

        # And the events that arrived first were kept, not thrown away.
        assert session.wait_for("Page.loadEventFired", timeout=1) == {}
    finally:
        session.close()


def test_a_protocol_error_is_raised_with_its_message(peer):
    from comodor.browser.cdp import Session

    session = Session.__new__(Session)
    session._ws = WebSocket(f"ws://127.0.0.1:{peer.port}/devtools/page/x")
    session._id = 0
    session._lock = threading.Lock()
    session._events = []
    peer.ready.wait(5)
    try:
        def answer():
            peer.read_one()
            peer.write(json.dumps({"id": 1, "error": {"message": "no such node"}}))

        threading.Thread(target=answer, daemon=True).start()
        with pytest.raises(BrowserError) as raised:
            session.call("DOM.focus", timeout=10)
        assert "no such node" in str(raised.value)
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# what of a page is worth sending
# --------------------------------------------------------------------------- #


def snapshot_of(count: int, **kwargs) -> Snapshot:
    return Snapshot(
        url="https://example.com", title="Example",
        elements=[Element(index=i, tag="a", kind="link", label=f"link {i}",
                          x=10, y=10 * i)
                  for i in range(1, count + 1)],
        **kwargs)


def test_controls_are_numbered_so_the_model_names_one_rather_than_a_pixel():
    """The whole reason this is text: a coordinate can miss by four pixels and
    nothing in the reply says what was meant."""
    rendered = snapshot_of(3).render(with_text=False)

    assert "  1." in rendered and "  3." in rendered
    assert "act on one by its number" in rendered


def test_a_field_is_marked_as_one_you_can_type_into():
    element = Element(index=1, tag="input", kind="search", label="Search",
                      x=0, y=0, typable=True)

    assert "type" in str(element)


def test_a_page_with_more_below_says_so():
    shot = snapshot_of(2, scroll=0, height=4000, viewport=800)

    rendered = shot.render(with_text=False)

    assert shot.more_below
    assert "scroll for the rest" in rendered


def test_a_page_that_fits_does_not_ask_to_be_scrolled():
    shot = snapshot_of(2, scroll=0, height=700, viewport=800)

    assert not shot.more_below
    assert "scroll" not in shot.render(with_text=False)


def test_a_page_with_nothing_to_click_says_that_rather_than_nothing():
    shot = Snapshot(url="https://example.com", title="Empty")

    assert "No controls are visible" in shot.render()


def test_the_text_can_be_left_out_when_only_the_controls_are_wanted():
    shot = snapshot_of(2)
    shot.text = "a great deal of prose"

    assert "prose" in shot.render()
    assert "prose" not in shot.render(with_text=False)


# --------------------------------------------------------------------------- #
# the tool
# --------------------------------------------------------------------------- #


def test_a_url_without_a_scheme_still_works(tool_context):
    from comodor.tools.browse import _absolute

    assert _absolute("example.com") == "https://example.com"
    assert _absolute("//example.com") == "https://example.com"
    assert _absolute("http://example.com") == "http://example.com"
    assert _absolute("  ") == ""


def test_acting_before_opening_anything_says_what_to_do(tool_context):
    from comodor.tools.browse import Browse

    result = Browse().run(tool_context, verb="click", target=1)

    assert not result.ok
    assert "open" in result.content


def test_an_unknown_verb_lists_the_real_ones(tool_context):
    from comodor.tools.browse import VERBS, Browse

    result = Browse().run(tool_context, verb="teleport")

    assert not result.ok
    for verb in VERBS:
        assert verb in result.content


def test_a_number_that_is_not_on_screen_explains_itself(tool_context):
    from comodor.tools.browse import Browse

    tool = Browse()
    tool._elements = [Element(index=1, tag="a", kind="link", label="one",
                              x=0, y=0)]
    message = tool._element(9)

    assert isinstance(message, str)
    assert "no control 9" in message
    assert "numbers go up to 1" in message


def test_the_numbers_are_only_good_for_the_listing_they_came_with(tool_context):
    """They are positions in a filtered list, so they change when the page
    does — and the model has to be told that, or it will reuse a stale one."""
    from comodor.tools.browse import Browse

    tool = Browse()
    tool._elements = [Element(index=1, tag="a", kind="link", label="one", x=0, y=0)]

    assert "the numbers change when it does" in str(tool._element(5))


def test_only_one_browser_tool_is_ever_offered():
    """Two tools that both look like "the browser" is a turn wasted choosing."""
    from comodor.tools import ToolRegistry

    names = {spec.name for spec in ToolRegistry().specs("act")}

    assert len({"browse", "browser"} & names) == 1


def test_the_text_browser_is_the_fallback_where_there_is_no_real_one(monkeypatch):
    from comodor.tools import registry as module

    monkeypatch.setattr(module, "_browser_tool",
                        lambda: module.Browser())
    names = {spec.name for spec in module.ToolRegistry().specs("act")}

    assert "browser" in names


# --------------------------------------------------------------------------- #
# with a browser, when there is one
# --------------------------------------------------------------------------- #


@needs_browser
def test_it_finds_a_browser_already_installed():
    """Nothing is downloaded. Playwright ships 170MB of Chromium; almost every
    machine already has one, and any of them speaks this protocol."""
    assert find()


@needs_browser
def test_a_named_browser_that_does_not_exist_is_an_error():
    with pytest.raises(BrowserError):
        find("/nowhere/no-such-browser")


@needs_browser
def test_it_reads_a_real_page_and_acts_on_it(tmp_path):
    from comodor.browser import Browser, Page
    from comodor.browser.cdp import close_tab, open_tab

    browser = Browser.start(tmp_path / "profile", headless=True)
    session = open_tab(browser.port)
    page = Page(session)
    try:
        page.goto("data:text/html,<h1>Hi</h1>"
                  "<button onclick=\"document.title='clicked'\">Press me</button>"
                  "<input placeholder='Your name'>")
        shot = page.snapshot()

        labels = [element.label for element in shot.elements]
        assert "Press me" in labels
        assert any(element.typable for element in shot.elements)

        button = next(e for e in shot.elements if e.label == "Press me")
        page.click(button)
        assert page.evaluate("document.title") == "clicked"

        field = next(e for e in shot.elements if e.typable)
        page.type_into(field, "Ada")
        assert page.evaluate("document.querySelector('input').value") == "Ada"
    finally:
        page.close()
        close_tab(browser.port, session.target_id)
        browser.stop()


@needs_browser
def test_what_is_off_screen_is_not_listed(tmp_path):
    """The filtering is the whole advantage over a screenshot, so it is the
    thing most worth asserting."""
    from comodor.browser import Browser, Page
    from comodor.browser.cdp import close_tab, open_tab

    browser = Browser.start(tmp_path / "profile", headless=True)
    session = open_tab(browser.port)
    page = Page(session)
    try:
        page.goto("data:text/html,"
                  "<button>On screen</button>"
                  "<div style='height:4000px'></div>"
                  "<button>Far below</button>"
                  "<button style='display:none'>Hidden</button>"
                  "<button disabled>Disabled</button>")
        labels = [element.label for element in page.snapshot().elements]

        assert "On screen" in labels
        assert "Far below" not in labels
        assert "Hidden" not in labels
        assert "Disabled" not in labels
    finally:
        page.close()
        close_tab(browser.port, session.target_id)
        browser.stop()


@needs_browser
def test_a_screenshot_is_a_real_png(tmp_path):
    from comodor.browser import Browser, Page
    from comodor.browser.cdp import close_tab, open_tab

    browser = Browser.start(tmp_path / "profile", headless=True)
    session = open_tab(browser.port)
    page = Page(session)
    try:
        page.goto("data:text/html,<h1 style='color:red'>Look</h1>")
        image = page.screenshot()

        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(image) > 500
    finally:
        page.close()
        close_tab(browser.port, session.target_id)
        browser.stop()


# --------------------------------------------------------------------------- #
# where the browser cannot have its own sandbox
# --------------------------------------------------------------------------- #


def test_only_a_missing_sandbox_causes_a_retry():
    """Restarting a browser that failed for some other reason — with a weaker
    configuration, silently — would be a bad way to hide a real problem."""
    from comodor.browser.launch import _looks_like_a_sandbox_problem

    assert _looks_like_a_sandbox_problem(
        "No usable sandbox! If this is a Debian system...")
    assert _looks_like_a_sandbox_problem(
        "Failed to move to new namespace: Operation not permitted")
    assert not _looks_like_a_sandbox_problem("could not start: file not found")
    assert not _looks_like_a_sandbox_problem("the browser did not open a port")


def test_the_useful_line_is_not_always_the_first_one():
    """Chromium under compose says the setuid helper failed, and only mentions
    the namespace four lines later. Matching the first line alone made the same
    bug appear or not depending on how the container was started."""
    from comodor.browser.launch import _first_line, _looks_like_a_sandbox_problem

    printed = "\n".join([
        "The setuid sandbox is not running as root. Common causes:",
        "  * An unprivileged process using ptrace on it, like a debugger.",
        "  * A parent process set prctl(PR_SET_NO_NEW_PRIVS, ...)",
        "Failed to move to new namespace: ... errno = Operation not permitted",
    ])

    assert _looks_like_a_sandbox_problem(printed)
    # And what a person is shown stays one line.
    assert "\n" not in _first_line(printed)
    assert "setuid sandbox is not running as root" in _first_line(printed)


def test_a_browser_that_fails_for_another_reason_is_not_restarted(tmp_path,
                                                                  monkeypatch):
    from comodor.browser import BrowserError
    from comodor.browser.launch import Browser

    attempts = []

    def refuse(cls, binary, profile, port, headless, window, sandboxed):
        attempts.append(sandboxed)
        raise BrowserError("the browser did not open a debugging port")

    monkeypatch.setattr(Browser, "_spawn", classmethod(refuse))
    monkeypatch.setattr("comodor.browser.launch.find", lambda hint="": "/bin/true")

    with pytest.raises(BrowserError):
        Browser.start(tmp_path / "profile")

    assert attempts == [True], "it should not have tried again"


def test_a_missing_sandbox_is_retried_once_without_one(tmp_path, monkeypatch):
    from comodor.browser.launch import Browser

    attempts = []

    def once(cls, binary, profile, port, headless, window, sandboxed):
        from comodor.browser.launch import SandboxUnavailable

        attempts.append(sandboxed)
        if sandboxed:
            raise SandboxUnavailable("it exited. It said: No usable sandbox!")
        return Browser("/bin/true", profile, port, sandboxed=False)

    monkeypatch.setattr(Browser, "_spawn", classmethod(once))
    monkeypatch.setattr("comodor.browser.launch.find", lambda hint="": "/bin/true")

    browser = Browser.start(tmp_path / "profile")

    assert attempts == [True, False]
    assert browser.sandboxed is False
    assert "without its own renderer sandbox" in browser.note


def test_a_browser_that_kept_its_sandbox_says_nothing_about_it(tmp_path):
    from comodor.browser.launch import Browser

    assert Browser("/bin/true", tmp_path, 9222).note == ""


@needs_browser
def test_on_a_real_machine_the_sandbox_is_kept(tmp_path):
    """The retry must not fire where the sandbox works — that would give up a
    real protection on every laptop to make one container convenient."""
    from comodor.browser import Browser

    browser = Browser.start(tmp_path / "profile", headless=True)
    try:
        assert browser.sandboxed is True
        assert browser.note == ""
    finally:
        browser.stop()
