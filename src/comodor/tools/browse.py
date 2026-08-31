"""A real browser, as one tool.

One tool with a verb rather than eight tools, for a reason that is about the
cached prefix: every tool schema is sent on every request, and eight of them
describing one browser is eight times the description of a browser. It is also
easier to use — the model picks a verb it can see the whole list of, instead of
choosing between `browser_click` and `browser_click_element`.

The browser is started on the first use and kept until the session ends,
because starting Chrome takes half a second and a task that opens six pages
should pay that once. Nothing is downloaded: it drives a browser the machine
already has, in a profile of its own that is signed into nothing.

What comes back is what a person would use to decide the next move — the title,
the readable text, and a numbered list of the controls actually on screen. Not
a screenshot, unless the question is visual, because a picture of a page costs
the same every time and cannot be trimmed. `look` is the verb for when it is.
"""

from __future__ import annotations

import base64
import threading
from typing import Any

from ..browser import Browser, BrowserError, Element, Page
from ..browser.cdp import close_tab, open_tab
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

VERBS = ("open", "click", "type", "scroll", "back", "look", "read", "script")


class Browse(Tool):
    """Drive a real browser: navigate, act, and look when looking is the point."""

    name = "browse"
    description = (
        "Use a real browser — one that runs JavaScript, keeps cookies, and can "
        "log in. Verbs: open (go to a url), click (a control, by its number), "
        "type (into a field, by its number), scroll, back, read (the page "
        "again), look (a screenshot, when the question is about how something "
        "*looks* — layout, styling, a chart), script (run JavaScript and get "
        "its value). Every reply lists the controls on screen with numbers; "
        "act on one by giving its number. Prefer this over web_fetch when a "
        "page needs JavaScript, a login, or clicking."
    )
    # A browser reaches the network and can act on what it finds, so it
    # asks, exactly as fetching a page and running a command both do.
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "verb": {"type": "string", "enum": list(VERBS),
                     "description": "What to do."},
            "url": {"type": "string", "description": "For open."},
            "target": {"type": "integer",
                       "description": "The number of a control, for click and type."},
            "text": {"type": "string", "description": "What to type."},
            "submit": {"type": "boolean",
                       "description": "Press Enter after typing (default false)."},
            "amount": {"type": "integer",
                       "description": "Pixels to scroll; omit for one screen."},
            "code": {"type": "string", "description": "JavaScript, for script."},
            "full_page": {"type": "boolean",
                          "description": "For look: the whole page, not the screen."},
        },
        "required": ["verb"],
    }

    def __init__(self) -> None:
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._elements: list[Element] = []
        self._lock = threading.Lock()

    def summary(self, args: dict[str, Any]) -> str:
        verb = str(args.get("verb", "?"))
        if verb == "open":
            return f"browse {args.get('url', '')}"
        if verb in ("click", "type"):
            return f"browse {verb} {args.get('target', '?')}"
        return f"browse {verb}"

    # -- the tool ---------------------------------------------------------- #

    def run(self, ctx: ToolContext, verb: str = "", **args: Any) -> ToolResult:
        verb = (verb or "").strip().lower()
        if verb not in VERBS:
            return ToolResult.failure(
                f"unknown verb {verb!r}. One of: {', '.join(VERBS)}")

        with self._lock:
            try:
                return self._act(ctx, verb, args)
            except BrowserError as error:
                return ToolResult.failure(str(error))

    def _act(self, ctx: ToolContext, verb: str, args: dict[str, Any]) -> ToolResult:
        if verb == "open":
            url = _absolute(str(args.get("url") or ""))
            if not url:
                return ToolResult.failure("open needs a url")
            from .web import check_url

            refused = check_url(ctx, url)
            if refused:
                return ToolResult.failure(refused)
            page = self._open(ctx)
            page.goto(url)
            return self._describe(page)

        page = self._page
        if page is None:
            return ToolResult.failure(
                "no page is open — use verb 'open' with a url first")

        if verb == "read":
            return self._describe(page)

        if verb == "back":
            page.back()
            return self._describe(page)

        if verb == "scroll":
            page.scroll(int(args.get("amount") or 0))
            return self._describe(page)

        if verb == "look":
            return self._look(page, bool(args.get("full_page")))

        if verb == "script":
            code = str(args.get("code") or "").strip()
            if not code:
                return ToolResult.failure("script needs code")
            value = page.evaluate(code)
            return ToolResult.success(content=_readable(value), display=_readable(value))

        element = self._element(args.get("target"))
        if isinstance(element, str):
            return ToolResult.failure(element)

        if verb == "click":
            page.click(element)
            return self._describe(page, did=f"clicked {element.label!r}")

        text = str(args.get("text") or "")
        if not text:
            return ToolResult.failure("type needs text")
        page.type_into(element, text, submit=bool(args.get("submit")))
        return self._describe(page, did=f"typed into {element.label!r}")

    # -- pieces ------------------------------------------------------------- #

    def _open(self, ctx: ToolContext) -> Page:
        """Start the browser on first use, and keep it for the session."""
        if self._page is not None:
            return self._page
        settings = getattr(ctx.config, "browser", None)
        profile = ctx.config.paths.user / "browser"
        port = int(getattr(settings, "port", 0) or 0)

        if port:
            # A browser the user already started, which is how you use one you
            # are logged into without handing us your everyday profile.
            self._browser = Browser.attach(port)
        else:
            self._browser = Browser.start(
                profile,
                executable=str(getattr(settings, "executable", "") or ""),
                headless=bool(getattr(settings, "headless", True)),
                window=(int(getattr(settings, "width", 1280) or 1280),
                        int(getattr(settings, "height", 800) or 800)),
            )
        self._page = Page(open_tab(self._browser.port))
        return self._page

    def _element(self, target: Any) -> Element | str:
        try:
            number = int(target)
        except (TypeError, ValueError):
            return "give the number of a control from the last listing"
        found = next((item for item in self._elements if item.index == number), None)
        if found is None:
            highest = len(self._elements)
            return (f"there is no control {number} on screen"
                    + (f" — the numbers go up to {highest}" if highest else "")
                    + ". Read the page again; the numbers change when it does.")
        return found

    def _describe(self, page: Page, did: str = "") -> ToolResult:
        snapshot = page.snapshot()
        # The numbers are only valid for the listing they came with: the page
        # has just changed, so anything the model remembered is stale.
        self._elements = snapshot.elements
        body = snapshot.render()
        if did:
            body = f"({did})\n\n{body}"
        return ToolResult.success(
            content=body, display=body,
            url=snapshot.url, title=snapshot.title,
            controls=len(snapshot.elements),
        )

    def _look(self, page: Page, full_page: bool) -> ToolResult:
        image = page.screenshot(full_page=full_page)
        encoded = base64.b64encode(image).decode()
        snapshot = page.snapshot()
        self._elements = snapshot.elements
        return ToolResult.success(
            content=(f"A screenshot of {snapshot.url} "
                     f"({len(image):,} bytes) is attached."),
            display=f"screenshot of {snapshot.url}",
            # The loop turns this into an image block for models with eyes.
            image=encoded, url=snapshot.url,
        )

    def close(self) -> None:
        with self._lock:
            if self._page is not None:
                target = self._page.session.target_id
                self._page.close()
                if self._browser is not None:
                    close_tab(self._browser.port, target)
                self._page = None
            if self._browser is not None:
                self._browser.stop()
                self._browser = None
            self._elements = []


def _absolute(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if "://" in url:
        return url
    if url.startswith("//"):
        return "https:" + url
    return "https://" + url


def _readable(value: Any) -> str:
    import json

    if value is None:
        return "(no value)"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
