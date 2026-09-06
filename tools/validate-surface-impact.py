#!/usr/bin/env python3
"""Validate PR Surface Impact structure and reject known non-answers using only stdlib."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SURFACES = (
    "TUI",
    "Web UI",
    "CLI / Headless",
    "API / Protocols",
    "Desktop",
    "Channels / Integrations",
    "Docker / Packaged Runtime",
    "Persistence / Shared State",
    "Security / Authorization",
    "Tests / Documentation",
)
ALLOWED_STATUSES = {"REQUIRED", "UNCHANGED BUT VERIFIED", "NOT APPLICABLE"}
HEADER = ["Surface", "Status", "Evidence / Notes"]
HEADING = "## Surface Impact"
NON_ANSWERS = {
    "",
    "n/a",
    "na",
    "none",
    "no",
    "tbd",
    "todo",
    "pending",
    "unknown",
    "done",
    "not applicable",
    "not touched",
    "should work",
    "should still work",
    "unchanged",
    "not tested",
    "not run",
    "irrelevant",
    "probably unaffected",
    "tests pass",
    "tests passed",
    "existing test passed",
    "relevant call path inspected",
    "runtime smoke test performed",
    "protocol contract confirmed unchanged",
    "docker behavior verified",
    "no changes",
    "no changes needed",
    "no code changes needed",
}
PLACEHOLDER = re.compile(r"\breplace with (?:status|evidence)\b", re.IGNORECASE)
REFERENCE = re.compile(
    r"[\w.-]+[/\\][\w.-]+|\b[\w-]+\.(?:py|js|css|html|md|yml|yaml|toml)\b"
    r"|`[^`\n]+`|\b(?:pytest|ruff|python|git|docker)\s+\S+"
)


RAW_HTML_START = re.compile(r"^ {0,3}<(?:pre|script|style|textarea)(?=\s|>|$)", re.IGNORECASE)
RAW_HTML_END = re.compile(r"</(?:pre|script|style|textarea)>", re.IGNORECASE)
BLOCK_HTML_START = re.compile(
    r"^ {0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col"
    r"|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame"
    r"|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav"
    r"|noframes|ol|optgroup|option|p|param|section|source|summary|table|tbody|td|tfoot|th"
    r"|thead|title|tr|track|ul)(?=\s|/?>|$)",
    re.IGNORECASE,
)
COMPLETE_HTML_TAG = re.compile(
    r"^ {0,3}(?:</[a-z][a-z0-9-]* *>|<(?!(?:pre|script|style|textarea)(?=[ />]))"
    r"[a-z][a-z0-9-]*(?: +[a-z_:][a-z0-9_.:-]*"
    r"(?: *= *(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)* */?>) *$",
    re.IGNORECASE,
)
# GFM declarations require an initial uppercase ASCII letter, unlike CommonMark 0.31.
# GitHub's renderer also suppresses case variants of CDATA.
DELIMITED_HTML_START = re.compile(r"^ {0,3}(<!--|<\?|<![A-Z]|<!\[(?i:CDATA)\[)")
# A blank line ends the HTML *block*, but the element stays open: the heading and
# table after it are parsed as Markdown and then rendered folded away inside the
# disclosure widget. What the contract asks for is a section at the top level, so
# the state has to survive to the closing tag rather than to the first blank line.
COLLAPSED_START = re.compile(r"^ {0,3}<details(?=\s|/?>|$)", re.IGNORECASE)
# A closing tag takes no attributes and no slash: `</details foo>` is text GFM
# prints rather than a tag that ends anything.
CLOSING_TAG = re.compile(r"</([A-Za-z][A-Za-z0-9-]*)\s*>")
OPENING_TAG = re.compile(
    r"""<([A-Za-z][A-Za-z0-9-]*)(?:\s+[^\s"'=<>`/]+"""
    r"""(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*\s*/?>"""
)
TAG_NAME = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)")
# What a tag looks like when the line ends in the middle of it: whole attributes,
# then at most one being written. Anything else — a bare quote where an attribute
# name belongs — is not a tag the renderer will ever finish, so it is text.
PARTIAL_TAG = re.compile(
    r"""<[A-Za-z][A-Za-z0-9-]*(?:\s+[^\s"'=<>`/]+"""
    r"""(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*"""
    r"""(?:\s+[^\s"'=<>`/]*(?:\s*=\s*(?:"[^"]*|'[^']*|[^\s"'=<>`]*)?)?)?\s*/?$"""
)
PARTIAL_CLOSE = re.compile(r"</[A-Za-z][A-Za-z0-9-]*\s*$")
# What is left of a tag once the line it started on has been read: the attributes
# it still has to spell, and either the `>` that ends it or the end of the line.
ATTRS_END = re.compile(
    r"""(?:\s+[^\s"'=<>`/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*\s*/?>"""
)
ATTRS_PARTIAL = re.compile(
    r"""(?:\s+[^\s"'=<>`/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*"""
    r"""(?:\s+[^\s"'=<>`/]*(?:\s*=\s*(?:"[^"]*|'[^']*|[^\s"'=<>`]*)?)?)?\s*/?$"""
)
# An unfinished tag is inline HTML, and inline HTML belongs to one paragraph. A
# block that starts here ends that paragraph, and what was being read as a tag is
# printed as the text it turned out to be.
BLOCK_START = re.compile(r"^ {0,3}(?:>|#{1,6}(?:\s|$)|(?:[-*_] *){3,}$)")
# Inside a blockquote or a list item a block begins after the marker, so a fence,
# an indentation, a blank line or a comment opener is read from there rather than
# from the margin. A marker pads its content by one to four spaces; past that only
# one is padding and the rest is the indentation that begins an indented block.
MARKER = r"(?:> ?|(?:[-+*]|\d{1,9}[.)])(?: (?= {4,})| {1,4}))"
CONTAINER_PREFIX = re.compile(f"^ {{0,3}}{MARKER}+")
BLOCK_COMMENT = re.compile(f"^ {{0,3}}{MARKER}*<!--")


def _inside(line: str) -> str:
    """The line as its container sees it, with the markers that opened one gone."""
    prefix = CONTAINER_PREFIX.match(line)
    return line[prefix.end() :] if prefix else line


def _tag_end(text: str, at: int, quote: str = "") -> tuple[int | None, str]:
    """Where a tag finishes, or None and the quote still open at the end of the line.

    A `>` inside a quoted attribute value is part of the value, not the end of the
    tag that carries it, and the value may have been opened on an earlier line.
    """
    while at < len(text):
        character = text[at]
        if quote:
            quote = "" if character == quote else quote
        elif character in "\"'":
            quote = character
        elif character == ">":
            return at + 1, ""
        at += 1
    return None, quote


def _folded(text: str, pending: tuple[int, str] | None) -> tuple[int, tuple[int, str] | None]:
    """How far a line moves the disclosure depth, and what an unfinished tag owes.

    Only whole tags count. A tag carries its quoted attributes with it and may run
    past the end of a line, so what it encloses is attribute text the renderer
    escapes — a closer written in there ends nothing. `pending` is what the tag
    still being read will do to the depth once it finishes, and the quote it is in.
    """
    depth = 0
    at = 0
    while at < len(text):
        if pending is not None:
            owed, quote = pending
            resume = at
            if quote:
                closed = text.find(quote, at)
                if closed < 0:
                    return depth, (owed, quote)
                resume = closed + 1
            # The line break the tag was carried over is itself the whitespace
            # that separates what came before from the attribute written here.
            rest = " " + text[resume:]
            finished = ATTRS_END.match(rest)
            if finished:
                depth += owed
                at, pending = resume + finished.end() - 1, None
                continue
            if ATTRS_PARTIAL.match(rest):
                return depth, (owed, _tag_end(text, resume)[1])
            # What it went on to spell is not a tag, so none of it ever was one:
            # the renderer prints it, and the line is read as the text it is.
            pending = None
            continue
        start = text.find("<", at)
        if start < 0:
            break
        tag = CLOSING_TAG.match(text, start) or OPENING_TAG.match(text, start)
        if tag:
            if tag[1].lower() == "details":
                depth += -1 if text[start + 1] == "/" else 1
            at = tag.end()
            continue
        started = TAG_NAME.match(text, start)
        if started:
            end, quote = _tag_end(text, start)
            partial = PARTIAL_CLOSE if started[1] else PARTIAL_TAG
            if end is None and partial.match(text, start):
                # An opening tag still owes its depth when it finishes. A closer
                # split across lines owes nothing: the renderer prints it and the
                # element it names stays open.
                opens = not started[1] and started[2].lower() == "details"
                return depth, (int(opens), quote)
        at = start + 1
    return depth, pending


TAG_TOKEN = re.compile(
    r"\\[\\`<]|(?<!`)(?P<span>`+)(?!`).*?(?<!`)(?P=span)(?!`)|(?<!`)(?P<open>`+)(?!`)|<!--"
)


def _tag_text(line: str, comment: bool, code: str = "") -> tuple[str, bool, str]:
    """The part of a line a tag could be written in, and the state after it.

    Comment bodies are dropped and inline code is blanked, because a closing tag
    quoted as code or commented out is text GFM renders rather than the tag it
    names — and counting it would end a container the document leaves open. A
    code span runs to its matching delimiter, which may be on a later line.
    """
    text = ""
    while line:
        if comment:
            _, delimiter, rest = line.partition("-->")
            if not delimiter:
                # Kept rather than dropped: if the opener turns out to be inline
                # and its paragraph ends, none of this was ever commented out.
                return text, comment, code, line
            comment, line = False, rest
            continue
        if code:
            closer = re.search(f"(?<!`){code}(?!`)", line)
            if closer is None:
                return text, comment, code, line
            line = line[closer.end() :]
            code = ""
            continue
        token = TAG_TOKEN.search(line)
        if token is None:
            return text + line, comment, code, ""
        text += line[: token.start()]
        if token["open"]:
            return text, comment, token["open"], line[token.end() :]
        comment = token[0] == "<!--"
        line = line[token.end() :]
    return text, comment, code, ""


def _literal(text: str) -> str:
    """The tag text of a paragraph whose delimiter turned out never to close.

    A delimiter with no match is printed, so what followed it was never code and
    has to be read again. The buffer holds whole lines, and a span inside it can
    close on a later one, so it is read line by line — and whatever a delimiter
    that never closes seemed to hide is read again in its turn.
    """
    kept = ""
    comment = False
    code = ""
    skipped = ""
    for line in text.split("\n"):
        part, comment, code, deferred = _tag_text(line, comment, code)
        kept += part + " "
        skipped = f"{skipped}\n{deferred}" if code or comment else ""
    return kept + _literal(skipped) if skipped else kept


def _visible_lines(body: str) -> list[str]:
    lines = []
    fence = ""
    comment = False
    raw_html = ""
    collapsed = 0
    folded_fence = ""
    folded_tag = None
    folded_code = ""
    folded_span = ""
    folded_inline_comment = False
    folded_indent = False
    list_indent = 0
    blank = True
    paragraph = False
    for line in body.splitlines():
        line = line.expandtabs(4)
        if (raw_html or fence or collapsed) and list_indent and line.strip() \
                and not line.startswith(" " * list_indent):
            # Outside the container, a closer is escaped text, not a raw HTML terminator.
            # An unclosed element is closed with the list item it was opened in, so what
            # follows at the top level is rendered there rather than folded into it.
            raw_html = "unclosed-comment" if raw_html == "-->" else ""
            fence = ""
            collapsed = 0
            folded_fence = ""
            folded_tag = None
            folded_code = ""
            folded_span = ""
            folded_inline_comment = False
            folded_indent = False
            list_indent = 0
        if raw_html:
            if (raw_html == "blank" and not line.strip()) or (
                raw_html == "closing-tag" and RAW_HTML_END.search(line)
            ) or (raw_html in {"-->", "?>", ">", "]]>"} and raw_html in line):
                # A second raw comment on the closing line can hide the rendered Markdown.
                raw_html = (
                    "-->" if raw_html == "-->" and line.rfind("<!--") > line.rfind("-->") else ""
                )
            lines.append("")
            blank = not line.strip()
            continue
        if collapsed or (folded_tag is not None and folded_tag[0]):
            # Read as the container reads it: a fence, an indentation or a blank
            # line inside a blockquote or a list item begins after its marker.
            content = _inside(line)
            inner = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", content)
            if folded_fence:
                if (
                    inner
                    and inner[1][0] == folded_fence[0]
                    and len(inner[1]) >= len(folded_fence)
                    and not inner[2].strip()
                ):
                    folded_fence = ""
            elif inner and (inner[1][0] == "~" or "`" not in inner[2]):
                folded_fence = inner[1]
            elif content.startswith("    ") and (blank or folded_indent) and not comment:
                # Indented code, where the tag written here is printed rather
                # than acted on. Only where a block may begin: indentation does
                # not interrupt a paragraph, it goes on writing one. Once one
                # has begun it runs on, line after line, until something else
                # starts.
                folded_indent = True
            else:
                folded_indent = folded_indent and not content.strip()
                block_comment = comment and not folded_inline_comment
                if (not content.strip() or BLOCK_START.match(line)) and not block_comment:
                    # An inline comment opener with no `-->` is printed once the
                    # paragraph holding it ends, and so is everything it looked
                    # like it was hiding. One that begins its own block is a
                    # comment until `-->`, blank lines and all, and is left alone.
                    folded_tag, comment, folded_inline_comment = None, False, False
                    depth, folded_tag = _folded(_literal(folded_span), folded_tag)
                    collapsed = max(collapsed + depth, 0)
                    folded_code, folded_span = "", ""
                opened = not comment
                text, comment, folded_code, deferred = _tag_text(line, comment, folded_code)
                folded_inline_comment = (
                    not BLOCK_COMMENT.match(line) if comment and opened
                    else folded_inline_comment and comment
                )
                folded_span = f"{folded_span}\n{deferred}" if folded_code or comment else ""
                depth, folded_tag = _folded(text, folded_tag)
                collapsed = max(collapsed + depth, 0)
                folded_fence = folded_fence if collapsed else ""
            lines.append("")
            blank = not content.strip()
            paragraph = False
            continue
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if comment and (not line.strip() or re.match(r"^ {0,3}#{1,6}(?: |$)", line)):
            comment = False
        if fence:
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= len(fence)
                and not marker[2].strip()
            ):
                fence = ""
            lines.append("")
            continue
        if not comment:
            if marker and (marker[1][0] == "~" or "`" not in marker[2]):
                if marker.start(1) < list_indent:
                    list_indent = 0
                fence = marker[1]
                paragraph = False
                lines.append("")
                continue
            if not line.strip():
                lines.append("")
                blank = True
                paragraph = False
                folded_tag = None
                depth, folded_tag = _folded(_literal(folded_span), folded_tag)
                collapsed = max(collapsed + depth, 0)
                folded_code, folded_span = "", ""
                continue
            if line.startswith("    "):
                lines.append("")
                continue
            if COLLAPSED_START.match(line):
                if line.index("<") < list_indent:
                    list_indent = 0
                depth, folded_tag = _folded(line, None)
                collapsed = max(depth, 0)
                lines.append("")
                blank = False
                paragraph = False
                continue
            html_start = RAW_HTML_START.match(line)
            delimited_html_start = DELIMITED_HTML_START.match(line)
            blank_html_start = BLOCK_HTML_START.match(line) or (
                not paragraph and COMPLETE_HTML_TAG.fullmatch(line)
            )
            if html_start or blank_html_start or delimited_html_start:
                if line.index("<") < list_indent:
                    list_indent = 0
                raw_html = "blank" if blank_html_start else "closing-tag"
                if delimited_html_start:
                    opener = delimited_html_start[1].upper()
                    raw_html = {"<!--": "-->", "<?": "?>", "<![CDATA[": "]]>"}.get(opener, ">")
                    if raw_html in line:
                        raw_html = (
                            "-->"
                            if raw_html == "-->" and line.rfind("<!--") > line.rfind("-->")
                            else ""
                        )
                if html_start and RAW_HTML_END.search(line):
                    raw_html = ""
                lines.append("")
                blank = False
                paragraph = False
                continue
        visible = ""
        while line:
            if comment:
                _, delimiter, line = line.partition("-->")
                comment = not delimiter
            else:
                token = re.search(r"\\[\\`<]|(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)|<!--", line)
                if token is None:
                    visible += line
                    break
                visible += line[: token.start()]
                comment = token[0] == "<!--"
                if not comment:
                    visible += token[0]
                line = line[token.end() :]
        indent = len(visible) - len(visible.lstrip(" "))
        item = re.match(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])( +|$)", visible)
        block = re.match(r"^ {0,3}(?:#{1,6}\s|>|(?:\* *){3,}$|(?:- *){3,}$|(?:_ *){3,}$)", visible)
        setext = paragraph and re.fullmatch(r" {0,3}(?:=+|-+) *", visible)
        if setext:
            item = None
        if visible.strip() and indent < list_indent and (blank or block or item):
            list_indent = 0
        if item and not block and not list_indent:
            padding = len(item[1]) if visible[item.end() :] and len(item[1]) <= 4 else 1
            list_indent = item.start(1) + padding
        nested = list_indent and indent >= list_indent
        lines.append("" if item or nested else visible.strip())
        blank = not visible.strip()
        paragraph = not blank and not block and not item and not setext
        # A disclosure opens from ordinary prose as readily as from a line of its
        # own, and folds everything after it just the same.
        if BLOCK_START.match(line):
            folded_tag = None
            depth, folded_tag = _folded(_literal(folded_span), folded_tag)
            collapsed = max(collapsed + depth, 0)
            folded_code, folded_span = "", ""
        bare, _, folded_code, deferred = _tag_text(visible, False, folded_code)
        folded_span = f"{folded_span}\n{deferred}" if folded_code else ""
        depth, folded_tag = _folded(bare, folded_tag)
        collapsed = max(collapsed + depth, 0)
    return lines


def _split_row(line: str) -> list[str]:
    cells = []
    current = []
    escaped = False
    for character in line[1:-1]:
        if character == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        escaped = character == "\\" and not escaped
    cells.append("".join(current).strip())
    return cells


def parse_surface_rows(body: str) -> tuple[dict[str, list[str]], list[str]]:
    lines = _visible_lines(body)
    headings = [index for index, line in enumerate(lines) if line == HEADING]
    if not headings:
        return {}, [f"Missing required '{HEADING}' section."]
    if len(headings) != 1:
        return {}, [f"Expected exactly one '{HEADING}' section."]
    start = headings[0] + 1
    end = next(
        (i for i in range(start, len(lines)) if re.match(r"^#{1,2}\s", lines[i])), len(lines)
    )
    table = []
    ended = False
    for line in lines[start:end]:
        if line.startswith("|"):
            if ended:
                return {}, ["Surface Impact must contain one contiguous table."]
            if not line.endswith("|"):
                return {}, ["Surface Impact table rows must start and end with '|'."]
            table.append(_split_row(line))
        elif table:
            ended = True
    if len(table) < 2 or table[0] != HEADER:
        return {}, ["Expected table header: | Surface | Status | Evidence / Notes |"]
    if len(table[1]) != 3 or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in table[1]):
        return {}, ["Expected a three-column Markdown separator below the table header."]

    errors = []
    rows = {}
    names = []
    for cells in table[2:]:
        if len(cells) != 3:
            errors.append(
                f"{cells[0]}: expected exactly three columns; escape literal pipes as \\|."
            )
            continue
        surface = cells[0]
        names.append(surface)
        if surface not in SURFACES:
            errors.append(f"Unexpected Surface Impact row: {surface}")
        elif surface in rows:
            errors.append(f"Duplicate Surface Impact row: {surface}")
        else:
            rows[surface] = cells
    for surface in SURFACES:
        if surface not in rows:
            errors.append(f"Missing Surface Impact row: {surface}")
    if names != list(SURFACES):
        errors.append("Surface Impact rows must use the canonical names and order in the template.")
    return rows, errors


def _has_explanation(evidence: str) -> bool:
    normalized = " ".join(re.sub(r"[`*_]", "", evidence).casefold().split()).strip(" .!?-:;")
    tokens = re.findall(r"`[^`\n]+`|\b[\w/\\:.-]+\b", evidence)
    reference_with_outcome = (
        len(tokens) == 2
        and REFERENCE.search(tokens[0]) is not None
        and tokens[1].casefold().rstrip(".") in {"passed", "failed"}
    )
    return (
        normalized not in NON_ANSWERS
        and not PLACEHOLDER.search(evidence)
        and (len(tokens) >= 3 or reference_with_outcome)
    )


def validate_body(body: str) -> list[str]:
    rows, errors = parse_surface_rows(body)
    for surface, (_, status, evidence) in rows.items():
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"{surface}: invalid status; use REQUIRED, UNCHANGED BUT VERIFIED, "
                "or NOT APPLICABLE."
            )
            continue
        if not _has_explanation(evidence):
            errors.append(
                f"{surface}: {status} needs evidence or a technical reason, not a non-answer."
            )
        elif status != "NOT APPLICABLE" and not REFERENCE.search(evidence):
            errors.append(
                f"{surface}: {status} needs a concrete path, command, or backticked identifier "
                "with implementation or verification details."
            )
    return errors


def _body_from_event(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("pull_request"), dict):
        raise ValueError("GitHub event must contain a pull_request object.")
    body = data["pull_request"].get("body")
    if body is None:
        return ""
    if not isinstance(body, str):
        raise ValueError("pull_request.body must be a string or null.")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--event-file", type=Path, help="GitHub event JSON containing pull_request.body"
    )
    source.add_argument(
        "--body-file", type=Path, help="UTF-8 Markdown PR body; otherwise read stdin"
    )
    args = parser.parse_args(argv)
    try:
        if args.event_file is not None:
            body = _body_from_event(args.event_file)
        elif args.body_file is not None:
            body = args.body_file.read_text(encoding="utf-8")
        else:
            body = sys.stdin.read()
    except (OSError, ValueError) as exc:
        print(f"surface-contract: unable to read input ({type(exc).__name__}).", file=sys.stderr)
        return 2
    errors = validate_body(body)
    if errors:
        print("Surface Impact contract failed.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print("See docs/surface-parity.md and .github/PULL_REQUEST_TEMPLATE.md.", file=sys.stderr)
        return 1
    print(f"Surface Impact contract passed: {len(SURFACES)} mandatory surfaces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
