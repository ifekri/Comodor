"""Browsing, rather than fetching.

`web_fetch` downloads one page and strips it to text. That is the right tool
for "read this URL" and useless for anything past it, because stripping the
markup takes the links with it: the agent gets a wall of prose describing a
navigation it has no way to perform, and the only route onward is guessing a
URL. Which it does.

A browser is the same reduction plus the three things that make a page part of
a site:

* **The links come back.** Numbered, resolved to absolute URLs, de-duplicated,
  and cut off at a sensible count — so the next move is `follow 4` rather than
  a guess. Navigation bars repeat on every page of a documentation site, so
  they are ranked below links that appear inside the content.
* **It is a session.** One cookie jar and one connection pool for the whole
  visit, so a redirect chain, a consent banner or a login survives the hop to
  the next page. `web_fetch` starts from nothing every time.
* **It remembers where it has been.** `back` exists, and a page already visited
  comes out of the history rather than off the network.

Long pages are paged rather than truncated. `web_fetch` cuts at forty thousand
characters and says so, which for a specification is the interesting half
thrown away; here the page is kept whole in the session and handed over a
screenful at a time, with `find` to jump straight to the part that matters.

**What it is not.** There is no JavaScript engine here and there is not going
to be one — that means a real browser, which means a real dependency, and this
package has one. A page that renders itself in the client comes back as whatever
its HTML actually contains, and says so. For those, the Puppeteer server in the
MCP catalogue drives a real Chrome, and this tool tells the model to reach for
it rather than pretending.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..net import http
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult
from .web import USER_AGENT, html_to_text

#: Characters handed over per view. Roughly a long screenful.
PAGE_CHARS = 12_000
#: Links listed per page. Beyond this it is a sitemap, not a page.
MAX_LINKS = 40
#: Pages kept in the session. Each one is text, so this is cheap.
MAX_HISTORY = 20

_LINK = re.compile(
    r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#>]+)[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
#: Where a site's own furniture lives. Links inside these are ranked last.
_CHROME = re.compile(r"<(nav|header|footer|aside)\b.*?</\1>",
                     re.IGNORECASE | re.DOTALL)
#: A page that renders itself in the browser leaves almost nothing behind.
_THIN = 400


@dataclass
class Link:
    url: str
    text: str


@dataclass
class Page:
    url: str
    title: str
    text: str
    links: list[Link] = field(default_factory=list)
    #: Where the last view stopped, so `more` continues rather than repeats.
    cursor: int = 0

    @property
    def pages(self) -> int:
        return max(1, -(-len(self.text) // PAGE_CHARS))


@dataclass
class Visit:
    """One browsing session: cookies, history, and where we are."""

    session: Any = None
    history: list[Page] = field(default_factory=list)
    index: int = -1

    @property
    def current(self) -> Page | None:
        return self.history[self.index] if 0 <= self.index < len(self.history) else None

    def open(self) -> Any:
        if self.session is None:
            self.session = http.Session(
                headers={"User-Agent": USER_AGENT,
                         "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                         "Accept-Language": "en"},
                timeout=(10.0, 30.0),
            )
        return self.session

    def visited(self, url: str) -> Page | None:
        for page in self.history:
            if page.url == url:
                return page
        return None

    def push(self, page: Page) -> None:
        # Anything forward of here is a branch nobody took.
        del self.history[self.index + 1:]
        self.history.append(page)
        del self.history[:-MAX_HISTORY]
        self.index = len(self.history) - 1

    def close(self) -> None:
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
            self.session = None


def _clean(markup: str) -> str:
    return _SPACE.sub(" ", html_module.unescape(_TAG.sub(" ", markup))).strip()


def extract_links(markup: str, base: str) -> list[Link]:
    """Every link worth offering, in the order they are worth offering."""
    chrome_spans = [match.span() for match in _CHROME.finditer(markup)]

    def in_chrome(position: int) -> bool:
        return any(start <= position < end for start, end in chrome_spans)

    seen: set[str] = set()
    content: list[Link] = []
    furniture: list[Link] = []

    for match in _LINK.finditer(markup):
        href = html_module.unescape(match.group(1).strip())
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:",
                                                "data:")):
            continue
        url = urljoin(base, href)
        if urlsplit(url).scheme not in ("http", "https") or url in seen:
            continue
        text = _clean(match.group(2))
        if not text:
            continue
        seen.add(url)
        (furniture if in_chrome(match.start()) else content).append(
            Link(url, text[:90]))

    return (content + furniture)[:MAX_LINKS]


def render(page: Page, offset: int, note: str = "") -> str:
    """One view of a page: a slice of its text, then where it can go next."""
    body = page.text[offset:offset + PAGE_CHARS]
    end = offset + len(body)

    header = f"{page.title or page.url}\n{page.url}"
    if page.pages > 1:
        showing = offset // PAGE_CHARS + 1
        header += f"\n[part {showing} of {page.pages}]"

    parts = [header, "", body]
    if end < len(page.text):
        parts.append(f"\n[{len(page.text) - end:,} more characters — "
                     f"browser(action='more')]")

    if page.links:
        listed = "\n".join(f"  {index:>2}. {link.text}  →  {link.url}"
                           for index, link in enumerate(page.links, start=1))
        parts.append(f"\nLinks on this page:\n{listed}")
        parts.append("\nFollow one with browser(action='follow', link=<number>).")

    if note:
        parts.append(f"\n{note}")
    return "\n".join(parts)


class Browser(Tool):
    name = "browser"
    description = (
        "Browse the web across pages, not just one at a time. Actions: "
        "'open' a url · 'follow' a numbered link from the current page · "
        "'back' · 'more' of a long page · 'find' text within it · 'links' to "
        "list them again. Cookies and the connection are kept for the whole "
        "session, so redirects and consent pages work. Prefer this over "
        "web_fetch whenever the answer might be a page or two away."
    )
    risk = Risk.DANGEROUS          # it leaves the machine, so it asks first
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "follow", "back", "more", "find", "links"],
                "description": "What to do. Defaults to 'open' when a url is given.",
            },
            "url": {"type": "string", "description": "For 'open'."},
            "link": {"type": "integer",
                     "description": "For 'follow': the number beside the link."},
            "text": {"type": "string", "description": "For 'find'."},
        },
        "required": [],
    }

    def __init__(self) -> None:
        self.visit = Visit()

    def summary(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or ("open" if args.get("url") else "?"))
        if action == "open":
            return f"browse {args.get('url', '?')}"
        if action == "follow":
            return f"follow link {args.get('link', '?')}"
        if action == "find":
            return f"find {str(args.get('text', ''))[:40]!r} on the page"
        return f"browser: {action}"

    def permission_key(self, args: dict[str, Any]) -> str:
        """One approval per host, and none at all for moving within a page.

        `more`, `find`, `links` and `back` do not touch the network — they read
        what is already in the session. Asking for them trains people to
        approve without reading.
        """
        action = str(args.get("action") or ("open" if args.get("url") else ""))
        if action in ("more", "find", "links", "back"):
            return f"{self.name}:local"
        if action == "follow":
            page = self.visit.current
            number = _as_int(args.get("link"))
            if page and number and 1 <= number <= len(page.links):
                return f"{self.name}:{urlsplit(page.links[number - 1].url).hostname}"
            return f"{self.name}:?"
        host = urlsplit(str(args.get("url", ""))).hostname or "?"
        return f"{self.name}:{host}"

    # -- the actions ------------------------------------------------------- #

    def run(self, ctx: ToolContext, action: str = "", url: str = "",
            link: Any = None, text: str = "", **_: Any) -> ToolResult:
        action = (action or ("open" if url else "")).strip().lower()
        if not action:
            return ToolResult.failure(
                "say what to do: open a url, or follow / back / more / find / links")

        handler = {
            "open": lambda: self._open(url),
            "follow": lambda: self._follow(_as_int(link)),
            "back": self._back,
            "more": self._more,
            "find": lambda: self._find(text),
            "links": self._links,
        }.get(action)

        if handler is None:
            return ToolResult.failure(f"unknown action {action!r}")
        return handler()

    def _open(self, url: str) -> ToolResult:
        if not url:
            return ToolResult.failure("open needs a url")
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url

        seen = self.visit.visited(url)
        if seen is not None:
            self.visit.push(seen)
            seen.cursor = min(PAGE_CHARS, len(seen.text))
            return self._result(seen, 0, note="(already visited this session)")

        try:
            response = self.visit.open().get(url)
        except http.RequestError as exc:
            return ToolResult.failure(f"could not open {url}: {exc}")

        with response:
            if not response.ok:
                return ToolResult.failure(
                    f"{url} returned {response.status_code} {response.reason}")
            content_type = response.headers.get("Content-Type", "")
            landed = getattr(response, "url", url) or url
            body = response.text

        page = self._page(landed, body, content_type)
        self.visit.push(page)
        page.cursor = min(PAGE_CHARS, len(page.text))

        note = ""
        if landed != url:
            note = f"(redirected from {url})"
        if "html" in content_type.lower() and len(page.text) < _THIN:
            note = (note + " " if note else "") + (
                "This page carries almost no text, which usually means it draws "
                "itself with JavaScript. There is no JavaScript engine here — "
                "for a page like this, use the Puppeteer server from "
                "`comodor mcp catalogue`.")
        return self._result(page, 0, note=note.strip())

    def _follow(self, number: int | None) -> ToolResult:
        page = self.visit.current
        if page is None:
            return ToolResult.failure("nothing is open yet")
        if not number or not 1 <= number <= len(page.links):
            return ToolResult.failure(
                f"pick a link between 1 and {len(page.links)}")
        return self._open(page.links[number - 1].url)

    def _back(self) -> ToolResult:
        if self.visit.index <= 0:
            return ToolResult.failure("nothing to go back to")
        self.visit.index -= 1
        page = self.visit.current
        assert page is not None
        page.cursor = min(PAGE_CHARS, len(page.text))
        return self._result(page, 0)

    def _more(self) -> ToolResult:
        page = self.visit.current
        if page is None:
            return ToolResult.failure("nothing is open yet")
        if page.cursor >= len(page.text):
            return ToolResult.success(content=f"{page.url}: that was the end.")
        offset = page.cursor
        page.cursor = min(page.cursor + PAGE_CHARS, len(page.text))
        return self._result(page, offset)

    def _find(self, needle: str) -> ToolResult:
        page = self.visit.current
        if page is None:
            return ToolResult.failure("nothing is open yet")
        if not needle:
            return ToolResult.failure("find needs something to look for")

        position = page.text.lower().find(needle.lower())
        if position < 0:
            return ToolResult.failure(f"{needle!r} is not on this page")

        # Start a little before the match, so it arrives with its context.
        offset = max(0, position - 400)
        page.cursor = min(offset + PAGE_CHARS, len(page.text))
        return self._result(page, offset, note=f"(found {needle!r})")

    def _links(self) -> ToolResult:
        page = self.visit.current
        if page is None:
            return ToolResult.failure("nothing is open yet")
        if not page.links:
            return ToolResult.success(content=f"{page.url} has no links.")
        listed = "\n".join(f"  {index:>2}. {link.text}  →  {link.url}"
                           for index, link in enumerate(page.links, start=1))
        return ToolResult.success(
            content=f"Links on {page.url}:\n{listed}", display=listed, url=page.url)

    # -- helpers ------------------------------------------------------------ #

    def _page(self, url: str, body: str, content_type: str) -> Page:
        is_html = "html" in content_type.lower() or body.lstrip().startswith("<")
        if not is_html:
            return Page(url=url, title=url.rsplit("/", 1)[-1], text=body)

        match = _TITLE.search(body)
        return Page(
            url=url,
            title=_clean(match.group(1)) if match else "",
            text=html_to_text(body),
            links=extract_links(body, url),
        )

    def _result(self, page: Page, offset: int, note: str = "") -> ToolResult:
        content = render(page, offset, note)
        return ToolResult.success(
            content=content, display=content, url=page.url,
            title=page.title, links=len(page.links), parts=page.pages,
        )

    def close(self) -> None:
        self.visit.close()


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
