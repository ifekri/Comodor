"""The model writes Markdown. None of these three chat apps reads Markdown.

Every one of them was being handed the model's answer as-is, so a reply that
said

    Use **`Path.resolve()`** — see [the docs](https://docs.python.org/3/).

arrived on somebody's phone as exactly that, asterisks and brackets and all.
A person reading that does not think "the renderer is wrong"; they think the
tool is sloppy, and a code fence full of backticks is worse — it is the part of
an answer that most needs to be set apart, and it was the part that looked most
broken.

So the answer is converted, once, into whatever the destination actually
speaks. Three targets and no two of them agree:

    Telegram    HTML: <b>, <i>, <code>, <pre>, <a href>, <blockquote>
    Slack       mrkdwn: *bold*, _italic_, `code`, <url|text>
    WhatsApp    *bold*, _italic_, ```mono```, and no link markup at all

**Order is the whole of the correctness here.** Code comes out first and is
replaced by a sentinel, so that an asterisk inside a shell command is never
mistaken for emphasis and a `<` inside a code block is escaped as text rather
than parsed as a tag. Everything else is done on what is left, and the code is
put back last.

Two traps this is deliberately careful about, because both produce output that
looks *almost* right:

*Underscores in identifiers.* `some_var_name` is not italics. An underscore
only opens emphasis at a word boundary, which is why `_italic_` works and
`snake_case_name` survives.

*Unmatched markers.* A lone `**` from a truncated stream is left as text rather
than swallowing the rest of the message into bold.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

#: The one character that may not appear in model output, used to seal a
#: rendered piece so no later pass can read it as markup.
NUL = chr(0)

#: Sentinels for the parts that must not be touched by anything else. Control
#: characters, because no model output contains them and no regex below can
#: match one by accident.
CODE_MARK = "\x00c{}\x00"
BLOCK_MARK = "\x00b{}\x00"

FENCE = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.S)
#: A fence with nothing after it — a stream that stopped mid-block.
OPEN_FENCE = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*)\Z", re.S)
INLINE_CODE = re.compile(r"`([^`\n]+)`")

LINK = re.compile(r"\[([^\]\n]+)\]\(\s*<?([^)\s>]+)>?\s*\)")
BOLD = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", re.S)
BOLD_ALT = re.compile(r"(?<![\w*])__(?!\s)(.+?)(?<!\s)__(?![\w*])", re.S)
ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
ITALIC_ALT = re.compile(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")
STRIKE = re.compile(r"~~(?!\s)(.+?)(?<!\s)~~", re.S)

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
NUMBERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
RULE = re.compile(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$")

#: What a horizontal rule becomes. A row of box drawing rather than three
#: hyphens, which every one of these apps renders as three hyphens.
RULE_LINE = "─" * 24


@dataclass(frozen=True)
class Flavour:
    """One destination's idea of markup."""

    name: str
    bold: tuple[str, str]
    italic: tuple[str, str]
    strike: tuple[str, str]
    code: tuple[str, str]
    #: Given (language, body) return the whole block.
    block: object
    #: Given (text, href) return the link.
    link: object
    #: Given the line's text return a quoted line.
    quote: object
    #: How to make text safe in this flavour.
    escape: object
    bullet: str = "• "
    #: Whether emphasis may wrap a code span. WhatsApp's only
    #: monospace is a triple backtick, and `*```x```*` renders
    #: as neither bold nor code.
    nest_code: bool = True


def _html_escape(text: str) -> str:
    return html.escape(text or "", quote=False)


def _slack_escape(text: str) -> str:
    """Only the three Slack reads as markup in ordinary text.

    Not the asterisks and underscores: those are what this module is putting
    in, deliberately.
    """
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


def _plain(text: str) -> str:
    return text or ""


TELEGRAM = Flavour(
    name="telegram",
    bold=("<b>", "</b>"),
    italic=("<i>", "</i>"),
    strike=("<s>", "</s>"),
    code=("<code>", "</code>"),
    block=lambda language, body: (
        f'<pre><code class="language-{language}">{body}</code></pre>'
        if language else f"<pre>{body}</pre>"),
    link=lambda text, href: f'<a href="{href}">{text}</a>',
    quote=lambda text: f"<blockquote>{text}</blockquote>",
    escape=_html_escape,
)

SLACK = Flavour(
    name="slack",
    bold=("*", "*"),
    italic=("_", "_"),
    strike=("~", "~"),
    code=("`", "`"),
    block=lambda language, body: f"```\n{body}\n```",
    link=lambda text, href: f"<{href}|{text}>",
    # A raw `>`: `&gt;` renders as the character and makes no
    # blockquote, which is the whole point of the line.
    quote=lambda text: f"> {text}",
    escape=_slack_escape,
)

WHATSAPP = Flavour(
    name="whatsapp",
    bold=("*", "*"),
    italic=("_", "_"),
    strike=("~", "~"),
    # WhatsApp has no single-backtick span. Three is what it understands, and
    # it renders inline as monospace, which is what was wanted.
    code=("```", "```"),
    block=lambda language, body: f"```\n{body}\n```",
    # No link markup at all: WhatsApp finds URLs on its own. So the label is
    # kept and the address follows it, rather than one of them being lost.
    link=lambda text, href: (href if text.strip() == href.strip()
                             else f"{text} ({href})"),
    quote=lambda text: f"> {text}",
    escape=_plain,
    nest_code=False,
)

DISCORD = Flavour(
    name="discord",
    bold=("**", "**"),
    italic=("*", "*"),
    strike=("~~", "~~"),
    code=("`", "`"),
    block=lambda language, body: (
        f"```{language}\n{body}\n```" if language else f"```\n{body}\n```"),
    # Markdown links, with the label kept for the few places a bare URL
    # renders better than nothing.
    link=lambda text, href: (href if text.strip() == href.strip()
                             else f"[{text}]({href})"),
    quote=lambda text: f"> {text}",
    # Discord renders `&lt;` as `<`, so the Slack escape is the right one:
    # escape only what would start an element, and let the emphasis through,
    # because this module is what puts it there.
    escape=_slack_escape,
)

FLAVOURS = {f.name: f for f in (TELEGRAM, SLACK, WHATSAPP, DISCORD)}


def render(text: str, flavour: Flavour) -> str:
    """The model's Markdown, in the markup this destination understands."""
    if not text:
        return ""

    blocks: list[str] = []
    text = _lift_blocks(text, blocks, flavour)

    lines = [_line(line, flavour) for line in text.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines)

    # The code goes back last, so nothing above could have touched it.
    for index, body in enumerate(blocks):
        out = out.replace(BLOCK_MARK.format(index), body)
    return out


def _lift_blocks(text: str, blocks: list[str], flavour: Flavour) -> str:
    """Pull fenced code out and leave a sentinel where each was."""

    def take(match: re.Match) -> str:
        language = (match.group(1) or "").strip()
        body = match.group(2)
        if body.endswith("\n"):
            body = body[:-1]
        blocks.append(flavour.block(language, flavour.escape(body)))
        return BLOCK_MARK.format(len(blocks) - 1)

    text = FENCE.sub(take, text)
    # A stream cut off mid-block still has to render as code rather than as a
    # row of backticks followed by the rest of the answer in italics.
    return OPEN_FENCE.sub(take, text)


def _line(line: str, flavour: Flavour) -> str:
    """One line, as whatever kind of line it is."""
    if BLOCK_MARK.format(0)[0] in line and line.strip().startswith("\x00"):
        return line                                   # a lifted code block
    if not line.strip():
        return ""

    if RULE.match(line):
        return RULE_LINE

    heading = HEADING.match(line)
    if heading:
        # None of the three has headings. Bold is what a heading is for.
        return _apply(flavour.bold, _inline(heading.group(2), flavour))

    quoted = QUOTE.match(line)
    if quoted:
        return flavour.quote(_inline(quoted.group(1), flavour))

    bullet = BULLET.match(line)
    if bullet:
        indent = " " * len(bullet.group(1))
        return f"{indent}{flavour.bullet}{_inline(bullet.group(2), flavour)}"

    numbered = NUMBERED.match(line)
    if numbered:
        indent = " " * len(numbered.group(1))
        return (f"{indent}{numbered.group(2)}. "
                f"{_inline(numbered.group(3), flavour)}")

    return _inline(line, flavour)


def _apply(pair: tuple[str, str], text: str) -> str:
    return f"{pair[0]}{text}{pair[1]}"


def _inline(text: str, flavour: Flavour) -> str:
    """Everything that happens inside one line.

    Every replacement is sealed behind a sentinel as it is made, and they are
    all put back at the end. Without that, the later passes read the earlier
    ones: on Slack and WhatsApp bold emits `*`, so running italic afterwards
    matched every bold word and turned it italic instead.
    """
    spans: list[str] = []

    def seal(rendered: str) -> str:
        spans.append(rendered)
        return CODE_MARK.format(len(spans) - 1)

    text = INLINE_CODE.sub(
        lambda m: seal(_apply(flavour.code, flavour.escape(m.group(1)))), text)
    text = flavour.escape(text)

    # Links before emphasis: a URL can hold underscores and a title can hold
    # asterisks, and neither of those is markup.
    text = LINK.sub(
        lambda m: seal(flavour.link(_open(m.group(1), spans), m.group(2))),
        text)

    text = BOLD.sub(lambda m: seal(_emphasis(flavour, "bold", m.group(1),
                                             spans)), text)
    text = BOLD_ALT.sub(lambda m: seal(_emphasis(flavour, "bold", m.group(1),
                                                 spans)), text)
    text = STRIKE.sub(lambda m: seal(_apply(flavour.strike, m.group(1))), text)
    text = ITALIC.sub(lambda m: seal(_emphasis(flavour, "italic", m.group(1),
                                               spans)), text)
    text = ITALIC_ALT.sub(lambda m: seal(_emphasis(flavour, "italic",
                                                   m.group(1), spans)), text)

    return _unseal(text, spans)


def _emphasis(flavour: Flavour, kind: str, inner: str,
              spans: list[str]) -> str:
    """Emphasis around some text, or around a code span.

    A flavour that cannot nest the two gets the code alone: on WhatsApp the
    only monospace is a triple backtick, and `*```x```*` renders as neither
    bold nor code.
    """
    if not flavour.nest_code and _is_only_code(inner, spans, flavour):
        return inner
    pair = flavour.bold if kind == "bold" else flavour.italic
    return _apply(pair, inner)


def _is_only_code(inner: str, spans: list[str], flavour: Flavour) -> bool:
    match = re.fullmatch(NUL + r"c(\d+)" + NUL, inner)
    if not match:
        return False
    span = spans[int(match.group(1))]
    return span.startswith(flavour.code[0])


def _open(text: str, spans: list[str]) -> str:
    """A link's own label, with any sentinels inside it restored."""
    return _unseal(text, spans)


def _unseal(text: str, spans: list[str]) -> str:
    """Put every sealed piece back, including ones nested inside others."""
    for _ in range(6):
        if NUL not in text:
            break
        for index in range(len(spans) - 1, -1, -1):
            text = text.replace(CODE_MARK.format(index), spans[index])
    return text


def to_telegram(text: str) -> str:
    return render(text, TELEGRAM)


def to_slack(text: str) -> str:
    return render(text, SLACK)


def to_whatsapp(text: str) -> str:
    return render(text, WHATSAPP)

def to_discord(text: str) -> str:
    return render(text, DISCORD)
