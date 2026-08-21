"""What the agent is shown of a page, and how it acts on it.

The obvious design for a visual browser is to send a screenshot every step and
ask the model to click a coordinate. It is obvious, it is what most do, and it
is wrong twice.

It is wrong on precision. A model reading pixels has to judge where a control
is, and it is judging against a resized image, so it misses — by a few pixels
at first and then by a whole button on a dense page. There is no recovery path
because nothing in the reply says which control was meant.

And it is wrong on cost, which is measurable, so it was measured. A
screen-sized capture is about 1,365 tokens every single time. The page's own
accessibility tree, sent whole, is worse: 8,760 tokens on Hacker News, 18,681
on a GitHub repository, 32,342 on a Wikipedia article — most of it hidden menus,
skip links, and the same navigation repeated in a header and a footer.

The thing that actually works is the third option, and it is available only
because this is text and not pixels: **filter it**. Half a screenshot answers
nothing, but a list of controls can be cut down to the ones a person could
actually see and click — on screen, visible, not disabled, named, deduplicated.
Measured on the same pages, as this module actually renders them:

                       whole tree    just the controls    a screenshot
    Hacker News            8,760                  933           1,365
    GitHub                18,681                  778           1,365
    Wikipedia             32,342                  414           1,365

So the controls alone are cheaper than a picture *and* unambiguous: the model
answers with a number, not a coordinate, and cannot miss by four pixels.

Adding the page's readable text brings it to about 1,900–2,300, which is more
than an image costs — and worth it, because that is the text itself rather than
a picture of it. Body copy read off a resized screenshot is a guess, and the
guess is silent.

Screenshots are still here, and still necessary, for the questions that are
actually about appearance: *does this look right, is the layout broken, what is
in this chart.* They are taken when the question is visual, not on every step,
which is the whole difference between a browser an agent can afford and one it
cannot.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from .cdp import NAVIGATE_TIMEOUT, BrowserError, Session

#: How many controls are worth listing. Past this the page is a directory and
#: the agent should search it, not read it.
MAX_ELEMENTS = 120
#: Longest label kept. A whole paragraph inside a link is not a label.
MAX_LABEL = 80
#: Page text handed back with the controls, before the overflow budget applies.
MAX_TEXT = 6_000

#: Collected in one round trip, filtered in the page, because every one of
#: these is a judgement a person makes without noticing they made it.
COLLECT = r"""
(() => {
  const out = [];
  const seen = new Set();
  const W = innerWidth, H = innerHeight;
  const WANTED = 'a[href],button,input,select,textarea,summary,' +
    '[role=button],[role=link],[role=tab],[role=checkbox],[role=radio],' +
    '[role=menuitem],[role=switch],[contenteditable=true],[onclick]';

  for (const el of document.querySelectorAll(WANTED)) {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    if (r.bottom < 0 || r.top > H || r.right < 0 || r.left > W) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') continue;
    if (parseFloat(s.opacity) < 0.05) continue;
    if (el.disabled) continue;

    let label = (el.getAttribute('aria-label') || el.innerText || el.value ||
                 el.getAttribute('title') || el.getAttribute('placeholder') ||
                 el.getAttribute('alt') || '')
      .replace(/\s+/g, ' ').trim().slice(0, __MAX_LABEL__);
    const tag = el.tagName.toLowerCase();
    if (!label && (tag === 'input' || tag === 'textarea'))
      label = '(' + (el.type || 'text') + ' field)';
    if (!label) continue;

    // The same link in a header and a footer is one thing to a reader.
    const key = tag + '|' + label;
    if (seen.has(key)) continue;
    seen.add(key);

    out.push({
      tag: tag,
      label: label,
      kind: el.getAttribute('role') ||
            (tag === 'a' ? 'link' : tag === 'input' ? (el.type || 'text') : tag),
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top + r.height / 2),
      typable: tag === 'input' || tag === 'textarea' ||
               el.getAttribute('contenteditable') === 'true',
    });
    if (out.length >= __MAX_ELEMENTS__) break;
  }

  const body = document.body;
  return {
    url: location.href,
    title: document.title,
    text: (body ? body.innerText : '').replace(/\n{3,}/g, '\n\n')
            .trim().slice(0, __MAX_TEXT__),
    scroll: Math.round(scrollY),
    height: Math.round(document.documentElement.scrollHeight),
    viewport: H,
    elements: out,
  };
})()
"""


@dataclass
class Element:
    """One control, as the model will refer to it."""

    index: int
    tag: str
    kind: str
    label: str
    x: int
    y: int
    typable: bool = False

    def __str__(self) -> str:
        # ASCII: this goes through whatever console the user has, and a
        # mangled glyph in front of every control is noise in the transcript.
        mark = "type" if self.typable else "    "
        return f"{self.index:>3}. {mark} {self.kind:<9} {self.label}"


@dataclass
class Snapshot:
    """What the page looks like right now, in words."""

    url: str = ""
    title: str = ""
    text: str = ""
    scroll: int = 0
    height: int = 0
    viewport: int = 0
    elements: list[Element] = field(default_factory=list)

    @property
    def more_below(self) -> bool:
        return self.scroll + self.viewport < self.height - 8

    def render(self, with_text: bool = True) -> str:
        lines = [f"{self.title or '(untitled)'}", self.url, ""]
        if self.elements:
            lines.append(f"Controls on screen ({len(self.elements)}) — "
                         f"act on one by its number:")
            lines += [str(element) for element in self.elements]
        else:
            lines.append("No controls are visible on this part of the page.")
        if with_text and self.text:
            lines += ["", "Text on screen:", self.text]
        if self.more_below:
            seen = min(100, int(100 * (self.scroll + self.viewport) /
                                max(1, self.height)))
            lines += ["", f"[{seen}% of the page; scroll for the rest]"]
        return "\n".join(lines)


class Page:
    """One tab, and the small set of things an agent does to a tab."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._ready = False

    def _prepare(self) -> None:
        if self._ready:
            return
        self.session.call("Page.enable")
        self.session.call("Runtime.enable")
        self.session.call("DOM.enable")
        self._ready = True

    # -- going places ------------------------------------------------------- #

    def goto(self, url: str, timeout: float = NAVIGATE_TIMEOUT) -> None:
        self._prepare()
        self.session.drain()
        result = self.session.call("Page.navigate", url=url, timeout=timeout)
        if result.get("errorText"):
            raise BrowserError(f"{url}: {result['errorText']}")
        self._settle(timeout)

    def _settle(self, timeout: float = NAVIGATE_TIMEOUT) -> None:
        """Wait for the load event, then for the page to stop moving.

        The load event is not the same as ready — a single-page app fires it
        before it has drawn anything — so it is followed by a short wait for
        the DOM to stop changing, which is what a person waits for.
        """
        try:
            self.session.wait_for("Page.loadEventFired", timeout=timeout)
        except BrowserError:
            pass                     # a page that never finishes is still a page
        self.evaluate(_QUIET, timeout=min(timeout, 12.0), await_promise=True)

    def back(self) -> None:
        self._prepare()
        history = self.session.call("Page.getNavigationHistory")
        index = history.get("currentIndex", 0)
        entries = history.get("entries") or []
        if index <= 0 or not entries:
            raise BrowserError("there is nothing to go back to")
        self.session.drain()
        self.session.call("Page.navigateToHistoryEntry",
                          entryId=entries[index - 1]["id"])
        self._settle()

    # -- looking ------------------------------------------------------------ #

    def snapshot(self) -> Snapshot:
        """The page as a list of things that can be done to it."""
        self._prepare()
        script = (COLLECT
                  .replace("__MAX_LABEL__", str(MAX_LABEL))
                  .replace("__MAX_ELEMENTS__", str(MAX_ELEMENTS))
                  .replace("__MAX_TEXT__", str(MAX_TEXT)))
        raw = self.evaluate(script)
        if not isinstance(raw, dict):
            raise BrowserError("the page could not be read")
        return Snapshot(
            url=str(raw.get("url") or ""),
            title=str(raw.get("title") or ""),
            text=str(raw.get("text") or ""),
            scroll=int(raw.get("scroll") or 0),
            height=int(raw.get("height") or 0),
            viewport=int(raw.get("viewport") or 0),
            elements=[
                Element(index=position, tag=str(item.get("tag") or ""),
                        kind=str(item.get("kind") or ""),
                        label=str(item.get("label") or ""),
                        x=int(item.get("x") or 0), y=int(item.get("y") or 0),
                        typable=bool(item.get("typable")))
                for position, item in enumerate(raw.get("elements") or [], start=1)
            ],
        )

    def screenshot(self, full_page: bool = False) -> bytes:
        """A picture, for the questions that are actually about appearance."""
        self._prepare()
        params: dict[str, Any] = {"format": "png"}
        if full_page:
            params["captureBeyondViewport"] = True
        result = self.session.call("Page.captureScreenshot", timeout=60.0, **params)
        data = result.get("data")
        if not data:
            raise BrowserError("the browser returned no image")
        return base64.b64decode(data)

    def evaluate(self, expression: str, timeout: float = 20.0,
                 await_promise: bool = False) -> Any:
        self._prepare()
        result = self.session.call(
            "Runtime.evaluate", timeout=timeout, expression=expression,
            returnByValue=True, awaitPromise=await_promise)
        thrown = result.get("exceptionDetails")
        if thrown:
            message = (thrown.get("exception") or {}).get("description") \
                or thrown.get("text") or "the script failed"
            raise BrowserError(str(message).splitlines()[0])
        return (result.get("result") or {}).get("value")

    # -- doing --------------------------------------------------------------- #

    def click(self, element: Element) -> None:
        """Click where the control is, as a mouse would.

        Dispatched as real input events rather than `el.click()`, because a
        synthetic click skips the hover, focus and pointer handling that a
        surprising number of interfaces are built on.
        """
        self._prepare()
        self.session.drain()
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            params: dict[str, Any] = {
                "type": kind, "x": element.x, "y": element.y, "button": "left",
            }
            if kind != "mouseMoved":
                params["clickCount"] = 1
            self.session.call("Input.dispatchMouseEvent", **params)
        self._after_action()

    def type_into(self, element: Element, text: str, submit: bool = False) -> None:
        self._prepare()
        self.click(element)
        # Replace rather than append: a field with something already in it is
        # the common case, and appending silently produces nonsense.
        self.session.call("Input.dispatchKeyEvent", type="keyDown",
                          key="a", code="KeyA", modifiers=2)
        self.session.call("Input.dispatchKeyEvent", type="keyUp",
                          key="a", code="KeyA", modifiers=2)
        self.session.call("Input.insertText", text=text)
        if submit:
            self.session.drain()
            for kind in ("keyDown", "keyUp"):
                self.session.call("Input.dispatchKeyEvent", type=kind,
                                  key="Enter", code="Enter", windowsVirtualKeyCode=13,
                                  nativeVirtualKeyCode=13, text="\r")
            self._after_action()

    def scroll(self, amount: int = 0) -> None:
        """Down by a screen, or by a given number of pixels."""
        self._prepare()
        step = amount or "innerHeight * 0.85"
        self.evaluate(f"scrollBy(0, {step}); 1")
        self.evaluate(_QUIET, timeout=6.0, await_promise=True)

    def _after_action(self) -> None:
        """Let a click finish, whether it navigated or only changed the page."""
        try:
            self.session.wait_for("Page.frameNavigated", timeout=2.5)
            self._settle(timeout=NAVIGATE_TIMEOUT)
            return
        except BrowserError:
            pass
        self.evaluate(_QUIET, timeout=8.0, await_promise=True)

    def close(self) -> None:
        self.session.close()


#: Resolves once the page has stopped changing, or after a short ceiling.
#: A load event is not readiness — a single-page app fires it before it has
#: drawn — and a fixed sleep is either too long or too short on every page.
_QUIET = """
new Promise(resolve => {
  let timer = null;
  const done = () => { try { observer.disconnect(); } catch (e) {} resolve(1); };
  const bump = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(done, 350);
  };
  const observer = new MutationObserver(bump);
  try {
    observer.observe(document, { childList: true, subtree: true,
                                 attributes: true, characterData: true });
  } catch (e) { resolve(1); return; }
  bump();
  setTimeout(done, 5000);
})
"""
