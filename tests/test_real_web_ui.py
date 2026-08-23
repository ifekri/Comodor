"""The browser interface, in a real browser.

`test_web.py` checks the server: who may reach it, what it says, what it
refuses. None of that touches the page, and the page is where this interface
mostly lives — direction, contrast, whether a phone can reach the sidebar,
whether every control has a name. Those are not properties of HTML source that
can be read off; they are properties of a rendered document, and reading the
source is how they get missed.

So this drives the real thing with Comodor's own browser support — the same
hand-rolled CDP client the `browse` tool uses. No new dependency, and the
tests skip on a machine with no browser, as the rest of the suite does.

The one that matters most is the direction check. A Persian sentence opening
with a package name and an English sentence quoting one Persian word are the
two cases every simple approach gets wrong, in opposite directions.
"""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import pytest

from comodor.browser import BrowserError
from comodor.browser.launch import find

try:
    find()
    HAVE_BROWSER = True
except BrowserError:
    HAVE_BROWSER = False

needs_browser = pytest.mark.skipif(
    not HAVE_BROWSER, reason="no Chrome, Chromium, Edge or Brave on this machine")


@pytest.fixture
def opened(config, tmp_path):
    """The server running, and a real browser looking at it."""
    from comodor.browser import Browser, Page
    from comodor.browser.cdp import close_tab, open_tab
    from comodor.web.server import Server, _handler_for

    server = Server(config, host="127.0.0.1", port=0)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(server))
    server.port = httpd.server_address[1]
    server._httpd = httpd
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()

    browser = Browser.start(tmp_path / "profile", headless=True)
    session = open_tab(browser.port)
    page = Page(session)
    try:
        page.goto(server.url)
        # The interface draws itself from `/api/state`, which is one more
        # round trip after the document has loaded.
        page.evaluate(
            "new Promise(r => { const go = () => document.getElementById('blank')"
            " || document.querySelector('.turn') ? r(1) : setTimeout(go, 50); go(); })",
            await_promise=True)
        yield page, server
    finally:
        try:
            page.close()
            close_tab(browser.port, session.target_id)
        except Exception:
            pass
        browser.stop()
        httpd.shutdown()
        httpd.server_close()
        server.session.close()


def direction_of(page, text: str) -> str:
    """What the page decides about a piece of text, using its own function."""
    quoted = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    return page.evaluate(f"directionOf(`{quoted}`)")


# --------------------------------------------------------------------------- #
# direction
# --------------------------------------------------------------------------- #


@needs_browser
def test_english_reads_left_to_right(opened):
    page, _ = opened

    assert direction_of(page, "rename the parser and run the tests") == "ltr"


@needs_browser
def test_persian_reads_right_to_left(opened):
    page, _ = opened

    assert direction_of(page, "تست‌ها را روی ویندوز اجرا کن") == "rtl"


@needs_browser
def test_a_persian_sentence_may_open_with_a_latin_word(opened):
    """The case `dir="auto"` gets wrong.

    It takes the first strong character, so this sentence is judged English
    and set inside out — the reader's eye starts at the wrong margin and the
    full stop lands on the wrong side.
    """
    page, _ = opened

    assert direction_of(page, "pytest را روی ویندوز اجرا کن") == "rtl"
    assert direction_of(page, "npm install را اول بزن، بعد تست") == "rtl"


@needs_browser
def test_an_english_sentence_may_quote_a_persian_word(opened):
    """The opposite mistake, and the one the old page made.

    It tested for the presence of any right-to-left character, so one Persian
    word turned an English paragraph around.
    """
    page, _ = opened

    assert direction_of(page, "the Persian word for parser is تجزیه‌گر") == "ltr"


@needs_browser
def test_code_and_paths_do_not_decide_the_direction(opened):
    """A Persian answer quoting three file paths is still a Persian answer.

    Code is always Latin and always incidental, so it is taken out before the
    counting. Left in, a short sentence with a fenced block outvoted itself.
    """
    page, _ = opened

    answer = ("این خط را عوض کردم:\n\n```python\n"
              "def tokenise(stream):\n    return [t for t in stream]\n```\n\n"
              "و در src/comodor/parse/tokenise.py ذخیره شد.")
    assert direction_of(page, answer) == "rtl"


@needs_browser
def test_nothing_at_all_is_left_to_right(opened):
    page, _ = opened

    assert direction_of(page, "") == "ltr"
    assert direction_of(page, "1234 :: -- ()") == "ltr"


@needs_browser
def test_a_persian_message_is_drawn_right_to_left(opened):
    """Not the function in isolation: the message as rendered."""
    page, server = opened
    from comodor.events import Kind

    server.session.bus.emit(Kind.USER_MESSAGE, text="حجم پوشهٔ build را کم کن")
    settled = page.evaluate(
        "new Promise(r => setTimeout(() => r(document.querySelector("
        "'.turn.user .text')?.getAttribute('dir')), 1200))", await_promise=True)

    assert settled == "rtl"


@needs_browser
def test_persian_is_set_in_vazirmatn_and_english_is_not(opened):
    """`unicode-range` doing the work no class could.

    One line of a mixed message gets the Persian face for the Persian and the
    interface face for the Latin, because the font is scoped to Arabic-script
    codepoints rather than switched on by a detector.
    """
    page, _ = opened

    loaded = page.evaluate(
        "document.fonts.ready.then(() => document.fonts.check('16px Vazirmatn', "
        "'سلام'))", await_promise=True)
    assert loaded is True

    latin = page.evaluate(
        "getComputedStyle(document.querySelector('#blank h1')).fontFamily")
    assert "Vazirmatn" not in latin.split(",")[0]


# --------------------------------------------------------------------------- #
# the rest of the rendered document
# --------------------------------------------------------------------------- #


@needs_browser
def test_every_control_on_screen_has_a_name(opened):
    """An icon with no accessible name is a button nobody can describe, to a
    screen reader or to the person being asked what they clicked."""
    page, _ = opened

    unnamed = page.evaluate("""
      [...document.querySelectorAll('button, a[href], select, input, [role=button]')]
        .filter((el) => el.offsetParent !== null)
        .filter((el) => !((el.getAttribute('aria-label') || el.textContent || '')
                          .trim() || el.getAttribute('title')))
        .map((el) => el.id || el.className || el.tagName)
    """)
    assert unnamed == []


@needs_browser
def test_readable_text_clears_the_contrast_floor(opened):
    """4.5:1, measured against the surface each piece of text is actually on.

    Not against the page: the rail, the footer and the composer are their own
    shades, and most of the small text in this interface sits on one of them.
    Checking against the page background passed a rail that failed.
    """
    page, _ = opened

    failures = page.evaluate("""
      (() => {
        const lum = (c) => {
          const [r, g, b] = c.match(/\\d+(\\.\\d+)?/g).slice(0, 3).map(Number)
            .map((v) => { v /= 255; return v <= .03928 ? v / 12.92
                                  : Math.pow((v + .055) / 1.055, 2.4); });
          return .2126 * r + .7152 * g + .0722 * b;
        };
        const behind = (el) => {
          for (let n = el; n; n = n.parentElement) {
            const c = getComputedStyle(n).backgroundColor;
            if (c && !c.startsWith('rgba(0, 0, 0, 0)')) return lum(c);
          }
          return lum(getComputedStyle(document.body).backgroundColor);
        };
        const bad = [];
        document.querySelectorAll(
          '#blank h1, #blank p, .starter, .hint, #mode-note, .group-label, '
          + '.empty-note, #status .bit, #whoami .model, .brand .tag'
        ).forEach((el) => {
          if (!el.offsetParent || !el.textContent.trim()) return;
          const f = lum(getComputedStyle(el).color), b = behind(el);
          const ratio = (Math.max(f, b) + .05) / (Math.min(f, b) + .05);
          if (ratio < 4.5) bad.push([el.id || el.className, ratio.toFixed(2)]);
        });
        return bad;
      })()
    """)
    assert failures == []


@needs_browser
def test_nothing_pushes_the_page_sideways(opened):
    """At every width, including the narrowest phone still sold.

    A horizontal scrollbar on the body means something is wider than the
    screen, and on a touch device it means the whole interface slides under
    the thumb while you are trying to read it.
    """
    page, _ = opened

    for width in (1440, 1024, 900, 768, 430, 390, 320):
        page.session.call("Emulation.setDeviceMetricsOverride", width=width,
                          height=800, deviceScaleFactor=1, mobile=width < 900)
        over = page.evaluate("document.documentElement.scrollWidth "
                             "- document.documentElement.clientWidth")
        assert over <= 0, f"{over}px of overflow at {width}px wide"
    page.session.call("Emulation.clearDeviceMetricsOverride")


@needs_browser
def test_the_sidebar_becomes_a_drawer_with_a_way_out(opened):
    """On a phone the rail cannot take 292 of 390 pixels, and the control that
    opened it is behind it — so the sheet carries its own."""
    page, _ = opened

    page.session.call("Emulation.setDeviceMetricsOverride", width=390, height=844,
                      deviceScaleFactor=1, mobile=True)
    state = page.evaluate("""
      (() => {
        setRail(true);
        const rail = document.getElementById('rail');
        return {
          over: getComputedStyle(rail).position === 'fixed',
          scrim: getComputedStyle(document.getElementById('scrim')).display
                 !== 'none',
          close: document.getElementById('rail-close').offsetParent !== null,
        };
      })()
    """)
    page.session.call("Emulation.clearDeviceMetricsOverride")

    assert state == {"over": True, "scrim": True, "close": True}


@needs_browser
def test_the_model_never_gets_to_write_markup(opened):
    """The agent reads files, and a file can contain a script tag.

    Every message is built from text nodes, so this is a rendering of the
    characters rather than a document containing them. If it ever becomes
    `innerHTML`, this fails on the first run.
    """
    page, server = opened
    from comodor.events import Kind

    server.session.bus.emit(
        Kind.ASSISTANT_DELTA,
        text="<img src=x onerror=\"window.__got_in = 1\"><b>bold?</b>")

    result = page.evaluate(
        "new Promise(r => setTimeout(() => r({"
        " ran: !!window.__got_in,"
        " tags: document.querySelectorAll('.turn.agent img, .turn.agent b').length,"
        " shown: (document.querySelector('.turn.agent .text')||{}).textContent || ''"
        "}), 1200))", await_promise=True)

    assert result["ran"] is False
    assert result["tags"] == 0
    assert "<b>bold?</b>" in result["shown"]


@needs_browser
def test_the_theme_survives_being_chosen(opened):
    """Light, dark, and what the machine asked for — and the choice is kept."""
    page, _ = opened

    dark = page.evaluate("(applyTheme('dark'), getComputedStyle(document.body)"
                         ".backgroundColor)")
    light = page.evaluate("(applyTheme('light'), getComputedStyle(document.body)"
                          ".backgroundColor)")
    assert dark != light

    page.evaluate("localStorage.setItem('comodor-theme', 'light')")
    assert page.evaluate("readTheme()") == "light"
