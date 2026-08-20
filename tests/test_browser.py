"""Browsing across pages.

The thing that makes this a browser and not a second `web_fetch` is that the
links survive the reduction to text, so the next move is `follow 4` rather than
a guessed URL. So that is what most of this is about: which links come back,
in what order, and what happens when the model asks for one that is not there.

Nothing here touches the network. The HTTP session is replaced with one that
serves a small site out of a dictionary, which is also the only way to test a
redirect and a cookie without a server.
"""

from __future__ import annotations

import pytest

from comodor.tools.browser import Browser, extract_links

SITE = {
    "https://example.test/": """
        <html><head><title>Home</title></head><body>
          <nav><a href="/about">About us</a><a href="/contact">Contact</a></nav>
          <main>
            <h1>Widgets</h1>
            <p>The widget is a thing. Read the <a href="/guide">guide</a>.</p>
            <p>Or the <a href="https://elsewhere.test/spec">specification</a>.</p>
            <a href="javascript:void(0)">Not a link</a>
            <a href="mailto:x@example.test">Nor this</a>
            <a href="/guide">guide again</a>
          </main>
          <footer><a href="/legal">Legal</a></footer>
        </body></html>
    """,
    "https://example.test/guide": """
        <html><head><title>The guide</title></head><body>
          <p>Step one. Step two. The word cassowary appears here.</p>
          <a href="/">Home</a>
        </body></html>
    """,
    "https://example.test/app": """
        <html><head><title>App</title></head><body><div id="root"></div></body></html>
    """,
}


class FakeResponse:
    def __init__(self, url: str, body: str, status: int = 200) -> None:
        self.url = url
        self.text = body
        self.status_code = status
        self.reason = "OK" if status == 200 else "Not Found"
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """A site in a dictionary, and a record of what was asked for."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = dict(pages if pages is not None else SITE)
        self.requested: list[str] = []
        self.closed = False

    def get(self, url: str, **_: object) -> FakeResponse:
        self.requested.append(url)
        if url in self.pages:
            return FakeResponse(url, self.pages[url])
        return FakeResponse(url, "<html><body>gone</body></html>", status=404)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def browser(tool_context) -> Browser:
    tool = Browser()
    tool.visit.session = FakeSession()
    tool._ctx = tool_context          # what `run` below passes back in
    return tool


def run(tool: Browser, **args):
    return tool.run(tool._ctx, **args)


# --------------------------------------------------------------------------- #
# the links
# --------------------------------------------------------------------------- #


def test_the_links_survive_the_reduction_to_text():
    """Which is the entire difference between this and web_fetch."""
    links = extract_links(SITE["https://example.test/"], "https://example.test/")
    urls = [link.url for link in links]

    assert "https://example.test/guide" in urls
    assert "https://elsewhere.test/spec" in urls


def test_relative_links_come_back_absolute():
    links = extract_links(SITE["https://example.test/"], "https://example.test/")

    assert all(link.url.startswith("http") for link in links)


def test_content_links_are_offered_before_the_furniture():
    """A documentation site repeats its navigation on every single page."""
    links = extract_links(SITE["https://example.test/"], "https://example.test/")
    urls = [link.url for link in links]

    assert urls.index("https://example.test/guide") < urls.index(
        "https://example.test/about")
    assert urls.index("https://example.test/guide") < urls.index(
        "https://example.test/legal")


def test_the_same_link_twice_is_offered_once():
    links = extract_links(SITE["https://example.test/"], "https://example.test/")
    urls = [link.url for link in links]

    assert urls.count("https://example.test/guide") == 1


@pytest.mark.parametrize("scheme", ["javascript:", "mailto:", "tel:", "data:"])
def test_things_that_are_not_pages_are_not_offered(scheme):
    markup = f'<a href="{scheme}whatever">click</a><a href="/real">real</a>'
    links = extract_links(markup, "https://example.test/")

    assert [link.url for link in links] == ["https://example.test/real"]


def test_a_link_with_no_text_is_no_use_to_anybody():
    markup = '<a href="/a"><img src="x.png"></a><a href="/b">B</a>'

    assert [link.text for link in extract_links(markup, "https://x.test/")] == ["B"]


# --------------------------------------------------------------------------- #
# moving
# --------------------------------------------------------------------------- #


def test_opening_a_page_returns_its_text_and_its_links(browser):
    result = run(browser, action="open", url="https://example.test/")

    assert result.ok
    assert "The widget is a thing" in result.content
    assert "Follow one with" in result.content
    assert "/guide" in result.content


def test_following_a_numbered_link_goes_there(browser):
    run(browser, action="open", url="https://example.test/")
    page = browser.visit.current
    number = next(index for index, link in enumerate(page.links, start=1)
                  if link.url.endswith("/guide"))

    result = run(browser, action="follow", link=number)

    assert result.ok
    assert "The guide" in result.content
    assert browser.visit.current.url == "https://example.test/guide"


def test_a_link_number_that_does_not_exist_says_the_range(browser):
    run(browser, action="open", url="https://example.test/")

    result = run(browser, action="follow", link=999)

    assert not result.ok
    assert "between 1 and" in result.content


def test_back_goes_back(browser):
    run(browser, action="open", url="https://example.test/")
    run(browser, action="open", url="https://example.test/guide")

    result = run(browser, action="back")

    assert result.ok
    assert browser.visit.current.url == "https://example.test/"


def test_back_from_the_first_page_is_refused_rather_than_wrapped(browser):
    run(browser, action="open", url="https://example.test/")

    assert not run(browser, action="back").ok


def test_a_page_already_visited_is_not_fetched_again(browser):
    run(browser, action="open", url="https://example.test/guide")
    run(browser, action="open", url="https://example.test/")
    run(browser, action="open", url="https://example.test/guide")

    assert browser.visit.session.requested.count("https://example.test/guide") == 1


def test_nothing_works_before_something_is_open(browser):
    for action in ("back", "more", "links"):
        assert not run(browser, action=action).ok
    assert not run(browser, action="find", text="x").ok


# --------------------------------------------------------------------------- #
# long pages
# --------------------------------------------------------------------------- #


def long_page() -> dict[str, str]:
    filler = " ".join(f"sentence-{i}." for i in range(6000))
    return {"https://long.test/": f"<html><title>Long</title><body><p>{filler}"
                                  f"</p><p>needle in here</p></body></html>"}


def test_a_long_page_is_paged_rather_than_truncated(browser):
    browser.visit.session = FakeSession(long_page())
    first = run(browser, action="open", url="https://long.test/")

    assert "part 1 of" in first.content
    assert "more characters" in first.content

    second = run(browser, action="more")

    assert second.ok
    # The second view continues rather than repeating the first.
    assert second.content[:200] != first.content[:200]


def test_more_at_the_end_says_so_instead_of_repeating(browser):
    run(browser, action="open", url="https://example.test/guide")

    result = run(browser, action="more")

    assert result.ok
    assert "the end" in result.content


def test_find_jumps_to_the_text_with_its_context(browser):
    browser.visit.session = FakeSession(long_page())
    run(browser, action="open", url="https://long.test/")

    result = run(browser, action="find", text="needle")

    assert result.ok
    assert "needle in here" in result.content


def test_find_says_so_when_it_is_not_there(browser):
    run(browser, action="open", url="https://example.test/guide")

    result = run(browser, action="find", text="platypus")

    assert not result.ok
    assert "platypus" in result.content


# --------------------------------------------------------------------------- #
# what it cannot do
# --------------------------------------------------------------------------- #


def test_a_page_that_draws_itself_says_so_and_names_the_way_round_it(browser):
    """Silence here sends the model round the same empty page twice."""
    result = run(browser, action="open", url="https://example.test/app")

    assert result.ok
    assert "JavaScript" in result.content
    assert "Puppeteer" in result.content


def test_a_page_that_is_not_there_is_reported(browser):
    result = run(browser, action="open", url="https://example.test/missing")

    assert not result.ok
    assert "404" in result.content


# --------------------------------------------------------------------------- #
# permission
# --------------------------------------------------------------------------- #


def test_approval_is_per_host(browser):
    assert browser.permission_key({"url": "https://example.test/a"}) \
        == browser.permission_key({"url": "https://example.test/b"})
    assert browser.permission_key({"url": "https://example.test/a"}) \
        != browser.permission_key({"url": "https://other.test/a"})


def test_moving_around_a_page_already_fetched_does_not_ask_again(browser):
    """`more` and `find` read what is in memory. Asking trains people to click yes."""
    for action in ("more", "find", "links", "back"):
        assert browser.permission_key({"action": action}) == "browser:local"


def test_following_a_link_asks_about_the_host_it_leads_to(browser):
    run(browser, action="open", url="https://example.test/")
    page = browser.visit.current
    number = next(index for index, link in enumerate(page.links, start=1)
                  if "elsewhere" in link.url)

    key = browser.permission_key({"action": "follow", "link": number})

    assert key == "browser:elsewhere.test"


def test_the_session_is_closed_with_the_tool(browser):
    session = browser.visit.session
    browser.close()

    assert session.closed
