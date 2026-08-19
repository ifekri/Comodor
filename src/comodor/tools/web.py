"""Reaching the internet: fetch a page, or search for one.

Both tools run through the project's own HTTP client, so they inherit its
timeouts, redirect handling and TLS defaults. HTML is reduced to readable text
before it reaches the model — raw markup is mostly tags, and tags are tokens
nobody is getting value from.

Search has no API key: it scrapes DuckDuckGo's HTML endpoint. That is a
deliberate trade — zero setup for the user, at the cost of a parser that may
need updating if the page changes. When parsing yields nothing the tool says so
plainly instead of inventing results.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

from ..net import http
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

USER_AGENT = ("Mozilla/5.0 (compatible; ComodorAgent/0.1; +https://github.com/ifekri/comodor)")
MAX_PAGE_CHARS = 40_000

_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>",
                           re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")
_BLOCK_END = re.compile(r"</(p|div|section|article|li|h[1-6]|tr|br)\s*>",
                        re.IGNORECASE)


def html_to_text(markup: str) -> str:
    """Strip markup down to something worth spending tokens on."""
    text = _SCRIPT_STYLE.sub(" ", markup)
    text = _BLOCK_END.sub("\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(line for line in lines if line))


class WebFetch(Tool):
    name = "web_fetch"
    description = (
        "Download a URL and return its readable text content. "
        "Use it to read documentation, issues, or any page the task refers to."
    )
    risk = Risk.DANGEROUS          # it leaves the machine, so it asks first
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer", "description": "Truncate the text at this length."},
        },
        "required": ["url"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"fetch {args.get('url', '?')}"

    def permission_key(self, args: dict[str, Any]) -> str:
        host = urlsplit(str(args.get("url", ""))).hostname or "?"
        return f"{self.name}:{host}"

    def run(self, ctx: ToolContext, url: str, max_chars: int = MAX_PAGE_CHARS,
            **_: Any) -> ToolResult:
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        try:
            response = http.get(url, headers={"User-Agent": USER_AGENT},
                                timeout=(10.0, 30.0))
        except http.RequestError as exc:
            return ToolResult.failure(f"could not fetch {url}: {exc}")

        with response:
            if not response.ok:
                return ToolResult.failure(f"{url} returned {response.status_code} "
                                          f"{response.reason}")
            content_type = response.headers.get("Content-Type", "")
            body = response.text

        if "html" in content_type.lower() or body.lstrip().startswith("<"):
            text = html_to_text(body)
        else:
            text = body

        limit = max(1000, int(max_chars))
        truncated = len(text) > limit
        text = text[:limit]
        note = f"\n\n[truncated at {limit:,} characters]" if truncated else ""

        return ToolResult.success(
            content=f"{url} ({content_type or 'unknown type'}):\n\n{text}{note}",
            display=text, url=url, truncated=truncated,
        )


class WebSearch(Tool):
    name = "web_search"
    description = (
        "Search the web and return the top results with titles, URLs and snippets. "
        "Follow up with web_fetch to read a result in full."
    )
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "description": "How many results (default 6)."},
        },
        "required": ["query"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"search: {args.get('query', '')[:80]}"

    def permission_key(self, args: dict[str, Any]) -> str:
        return self.name

    def run(self, ctx: ToolContext, query: str, limit: int = 6, **_: Any) -> ToolResult:
        endpoint = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            response = http.get(endpoint, headers={"User-Agent": USER_AGENT},
                                timeout=(10.0, 25.0))
        except http.RequestError as exc:
            return ToolResult.failure(f"search failed: {exc}")

        with response:
            if not response.ok:
                return ToolResult.failure(
                    f"search returned {response.status_code} {response.reason}")
            markup = response.text

        results = _parse_ddg(markup, max(1, int(limit)))
        if not results:
            return ToolResult.failure(
                "no results could be parsed from the search page — "
                "try web_fetch with a direct URL instead")

        lines = []
        for index, (title, link, snippet) in enumerate(results, start=1):
            lines.append(f"{index}. {title}\n   {link}\n   {snippet}")
        body = "\n\n".join(lines)
        return ToolResult.success(content=f"Results for {query!r}:\n\n{body}",
                                  display=body, count=len(results))


_RESULT = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?(?:class="result__snippet"[^>]*>(?P<snippet>.*?)</a>)?',
    re.IGNORECASE | re.DOTALL,
)


def _parse_ddg(markup: str, limit: int) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for match in _RESULT.finditer(markup):
        href = html.unescape(match.group("href") or "")
        # DuckDuckGo wraps outbound links in a redirector.
        if "uddg=" in href:
            query = parse_qs(urlsplit(href).query)
            href = (query.get("uddg") or [href])[0]
        title = html_to_text(match.group("title") or "").strip()
        snippet = html_to_text(match.group("snippet") or "").strip()
        if title and href:
            results.append((title, href, snippet[:300] or "(no snippet)"))
        if len(results) >= limit:
            break
    return results
