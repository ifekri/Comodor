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
COLLAPSED_OPEN = re.compile(r"<details(?=\s|/?>|$)", re.IGNORECASE)
COLLAPSED_END = re.compile(r"</details\s*>", re.IGNORECASE)


def _visible_lines(body: str) -> list[str]:
    lines = []
    fence = ""
    comment = False
    raw_html = ""
    collapsed = 0
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
        if collapsed:
            collapsed = max(collapsed + len(COLLAPSED_OPEN.findall(line))
                            - len(COLLAPSED_END.findall(line)), 0)
            lines.append("")
            blank = not line.strip()
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
                continue
            if line.startswith("    "):
                lines.append("")
                continue
            if COLLAPSED_START.match(line):
                if line.index("<") < list_indent:
                    list_indent = 0
                collapsed = max(len(COLLAPSED_OPEN.findall(line))
                                - len(COLLAPSED_END.findall(line)), 0)
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
