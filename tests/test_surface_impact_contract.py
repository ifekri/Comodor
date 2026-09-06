from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "validate-surface-impact.py"
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
STATUSES = {"REQUIRED", "UNCHANGED BUT VERIFIED", "NOT APPLICABLE"}
HEADER = "| Surface | Status | Evidence / Notes |"
EVIDENCE = "Inspected `tests/test_web.py`; the server contract assertions cover this path."
VALID_BODY = (
    "## Summary\n\nAn illustrative contract fixture, not a report of executed tests.\n\n"
    "## Surface Impact\n\n"
    + HEADER
    + "\n| --- | --- | --- |\n"
    + "\n".join(f"| {surface} | REQUIRED | {EVIDENCE} |" for surface in SURFACES)
    + "\n"
)


@pytest.fixture(scope="module")
def validator():
    spec = importlib.util.spec_from_file_location("surface_impact", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def with_cell(*, surface="TUI", status="REQUIRED", evidence=EVIDENCE):
    return VALID_BODY.replace(
        f"| {surface} | REQUIRED | {EVIDENCE} |",
        f"| {surface} | {status} | {evidence} |",
    )


def run_cli(*args, body="", cwd=None, env=None):
    return subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), *map(str, args)],
        input=body,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=env,
        timeout=15,
    )


def test_canonical_contract(validator):
    assert validator.SURFACES == SURFACES
    assert validator.ALLOWED_STATUSES == STATUSES
    assert validator.HEADER == ["Surface", "Status", "Evidence / Notes"]
    rows, errors = validator.parse_surface_rows(VALID_BODY)
    assert errors == []
    assert tuple(rows) == SURFACES
    assert all(len(cells) == 3 for cells in rows.values())
    assert validator.validate_body(VALID_BODY) == []


@pytest.mark.parametrize("status", sorted(STATUSES))
def test_allowed_statuses(validator, status):
    assert validator.validate_body(with_cell(status=status)) == []


@pytest.mark.parametrize("surface", SURFACES)
def test_missing_and_duplicate_rows_fail(validator, surface):
    row = f"| {surface} | REQUIRED | {EVIDENCE} |\n"
    assert f"Missing Surface Impact row: {surface}" in validator.validate_body(
        VALID_BODY.replace(row, "")
    )
    assert f"Duplicate Surface Impact row: {surface}" in validator.validate_body(
        VALID_BODY.replace(row, row + row)
    )


@pytest.mark.parametrize(
    "name",
    [
        "Core / Application",
        "Docker / Packaging",
        "Documentation",
        "Tests",
        "Other",
        "web ui",
        "**Web UI**",
        "`Web UI`",
    ],
)
def test_unexpected_names_fail(validator, name):
    errors = validator.validate_body(VALID_BODY.replace("| Web UI |", f"| {name} |"))
    assert f"Unexpected Surface Impact row: {name}" in errors
    assert "Missing Surface Impact row: Web UI" in errors


def test_order_is_enforced(validator):
    body = VALID_BODY.replace("| TUI |", "| temporary |")
    body = body.replace("| Web UI |", "| TUI |").replace("| temporary |", "| Web UI |")
    assert any("canonical names and order" in error for error in validator.validate_body(body))


@pytest.mark.parametrize(
    "status",
    [
        "",
        "MAYBE",
        "REPLACE WITH STATUS",
        "required",
        "**REQUIRED**",
        "`REQUIRED`",
        "REQUIRED / NOT APPLICABLE",
    ],
)
def test_invalid_statuses_fail(validator, status):
    assert any(
        "TUI: invalid status" in error
        for error in validator.validate_body(with_cell(status=status))
    )


@pytest.mark.parametrize("status", sorted(STATUSES))
@pytest.mark.parametrize(
    "evidence",
    [
        "",
        "-",
        "N/A",
        "NA",
        "none",
        "tbd",
        "todo",
        "not touched",
        "should work",
        "unknown",
        "tests pass",
        "**No changes needed.**",
        "`No code changes needed`",
        "protocol contract confirmed unchanged",
        "runtime smoke test performed",
        "REPLACE WITH evidence or technical reason",
        "tests/test_web.py",
        "/workspace/src/comodor/web/ui.js",
        r"E:\AiTools\Comodo-Agent\src\comodor\web\ui.js",
        r"src\comodor\web\ui.js",
        r"\\server\share\src\comodor\web\ui.js",
        r"`E:\Workspace With Spaces\src\comodor\web\ui.js`",
        "<!-- Explain the actual outcome here -->",
    ],
)
def test_non_answers_fail(validator, status, evidence):
    assert any(
        "TUI:" in error
        for error in validator.validate_body(with_cell(status=status, evidence=evidence))
    )


@pytest.mark.parametrize("status", ["REQUIRED", "UNCHANGED BUT VERIFIED"])
def test_implementation_and_verification_need_references(validator, status):
    errors = validator.validate_body(
        with_cell(status=status, evidence="Inspected the current path")
    )
    assert any("concrete path, command" in error for error in errors)


def test_not_applicable_needs_reason_but_not_reference(validator):
    assert (
        validator.validate_body(
            with_cell(
                status="NOT APPLICABLE",
                evidence=(
                    "Only terminal escape decoding changes; browser events bypass that decoder."
                ),
            )
        )
        == []
    )


@pytest.mark.parametrize(
    "evidence",
    [
        "Updated src/comodor/web/session.py to preserve the existing response shape.",
        "Ran pytest tests/test_web.py; all server contract assertions passed.",
        "`pytest -n 0 -q tests/test_web.py` passed.",
        "`pytest -n 0 -q tests/test_web.py` failed.",
        "Inspected `Session.refresh`; reconnect still reconstructs state from the shared service.",
        "Replace duplicated formatting in `src/comodor/web/ui.js` with the shared view helper.",
        r"Checked `tests/test_web.py`; escaped a literal pipe as a\|b in the fixture.",
    ],
)
def test_specific_evidence_passes(validator, evidence):
    assert validator.validate_body(with_cell(evidence=evidence)) == []


@pytest.mark.parametrize(
    "heading", ["", "# Surface Impact", "### Surface Impact", "## surface impact"]
)
def test_heading_is_required_and_exact(validator, heading):
    assert any(
        "Missing required" in error
        for error in validator.validate_body(VALID_BODY.replace("## Surface Impact", heading))
    )


def test_duplicate_section_fails(validator):
    assert any("exactly one" in error for error in validator.validate_body(VALID_BODY * 2))


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("<!--\n", "\n-->"),
        ("```markdown\n", "\n```"),
        ("~~~\n", "\n~~~"),
        ("````\n```\n", "\n````"),
        ("```\n", ""),
    ],
)
def test_hidden_contract_cannot_pass(validator, prefix, suffix):
    assert validator.validate_body(prefix + VALID_BODY + suffix)


@pytest.mark.parametrize("indent", ["    ", "\t", "> "])
def test_nested_or_quoted_contract_cannot_pass(validator, indent):
    body = "\n".join(indent + line for line in VALID_BODY.splitlines())
    assert validator.validate_body(body)


@pytest.mark.parametrize("marker", ["- ", "+ ", "* ", "1. ", "2) ", "  - "])
@pytest.mark.parametrize("continuation", ["", "\n", "continued paragraph\n"])
def test_contract_inside_list_item_fails(validator, marker, continuation):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    nested = "\n".join(" " * len(marker) + line for line in contract.splitlines())
    assert validator.validate_body(marker + "assessment:\n" + continuation + nested)


@pytest.mark.parametrize("marker", ["-", "+", "*", "1.", "2)", "  -"])
@pytest.mark.parametrize("padding", ["     ", "      ", "         ", "\t\t"])
def test_wide_list_padding_still_nests_contract(validator, marker, padding):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    nested = "\n".join(" " * (len(marker) + 1) + line for line in contract.splitlines())
    assert validator.validate_body(marker + padding + "assessment:\n\n" + nested)


@pytest.mark.parametrize("marker", ["-", "-   ", "1.", "1.      "])
def test_empty_list_marker_still_nests_contract(validator, marker):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    nested = "\n".join(" " * (len(marker.rstrip()) + 1) + line for line in contract.splitlines())
    assert validator.validate_body(marker + "\n" + nested)


@pytest.mark.parametrize("tag", ["pre", "script", "style", "textarea", "PRE"])
@pytest.mark.parametrize("closed", [True, False])
def test_raw_html_contract_cannot_pass(validator, tag, closed):
    body = f"<{tag}>\n" + VALID_BODY + (f"\n</{tag}>" if closed else "")
    assert validator.validate_body(body)


@pytest.mark.parametrize("tag", ["pre", "script", "style", "textarea"])
def test_closed_raw_html_does_not_hide_visible_contract(validator, tag):
    raw = f"<{tag}>\n```\n<!--\n{VALID_BODY}\n</{tag}>\n\n"
    assert validator.validate_body(raw + VALID_BODY) == []
    assert validator.validate_body(f"<{tag}>example</{tag}>\n\n" + VALID_BODY) == []
    assert validator.validate_body("````html\n" + raw + "````\n\n" + VALID_BODY) == []


@pytest.mark.parametrize("opener,closer", [("pre", "script"), ("style", "PRE")])
def test_type_one_closer_need_not_match_opener(validator, opener, closer):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    assert validator.validate_body(f"<{opener}>\n</{closer}>\n" + contract) == []


@pytest.mark.parametrize(
    "opener,closer",
    [("<?xml", "?>"), ("<!DOCTYPE html", ">"), ("<!Doctype html", ">"),
     ("<!D", ">"), ("<![CDATA[", "]]>"), ("<![cdata[", "]]>"),
     ("<![CdAtA[", "]]>"), ("<!--", "-->")],
)
def test_delimited_html_hides_contract_and_entire_closing_line(validator, opener, closer):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    assert validator.validate_body(opener + "\n" + contract)
    assert validator.validate_body(opener + "\n" + contract + closer)
    assert validator.validate_body(opener + "\n" + closer + contract)
    assert validator.validate_body(opener + " example " + closer + contract)


@pytest.mark.parametrize(
    "opener,closer",
    [("<?xml", "?>"), ("<!DOCTYPE html", ">"), ("<![CDATA[", "]]>"),
     ("<![cdata[", "]]>"), ("<!--", "-->")],
)
def test_delimited_html_keeps_following_contract_visible(validator, opener, closer):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    prefix = opener + "\n```\n<!--\n\n" + closer
    assert validator.validate_body(prefix + "\n" + contract) == []
    assert validator.validate_body(prefix + " ordinary text\n" + contract) == []
    assert validator.validate_body(opener + " example " + closer + "\n" + contract) == []
    assert validator.validate_body("````html\n" + prefix + "\n````\n" + contract) == []
    assert validator.validate_body("<pre>\n" + prefix + "\n</pre>\n" + contract) == []


@pytest.mark.parametrize("opener", ["<!doctype html", "<!d", "<! DOCTYPE html", "<!1"])
def test_gfm_declaration_requires_initial_uppercase_ascii_letter(validator, opener):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    assert validator.validate_body(opener + "\n" + contract + ">\n") == []


def test_comment_block_respects_closed_list_boundaries(validator):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    nested = "\n".join("  " + line for line in contract.splitlines())
    assert validator.validate_body("- earlier\n\n  <!--\n  -->\n\n" + nested)
    assert validator.validate_body("- earlier\n\n<!--\n-->\n\n" + nested) == []
    assert validator.validate_body("- earlier\n\n  <!--\n-->\n\n" + nested)


def test_closed_inline_comment_preserves_ordinary_prose(validator):
    assert validator._visible_lines("Ordinary <!-- hidden --> prose") == ["Ordinary  prose"]
    assert validator.validate_body("Ordinary <!-- hidden --> prose\n" + VALID_BODY) == []


@pytest.mark.parametrize("tag", ["pre", "script", "style", "textarea"])
@pytest.mark.parametrize("outdent", ["</{tag}>\n\n", "outside paragraph\n\n", ""])
def test_leaving_raw_html_list_allows_top_level_contract(validator, tag, outdent):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    prefix = f"- earlier\n\n  <{tag}>\n  example\n"
    indent = "  " if outdent else ""
    body = (
        prefix
        + outdent.format(tag=tag)
        + "\n".join(indent + line for line in contract.splitlines())
    )
    assert validator.validate_body(body) == []


@pytest.mark.parametrize("tag", ["pre", "script", "style", "textarea"])
def test_raw_html_closed_inside_list_keeps_contract_nested(validator, tag):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    nested = "\n".join("  " + line for line in contract.splitlines())
    assert validator.validate_body(f"- earlier\n\n  <{tag}>\n  example\n  </{tag}>\n\n" + nested)
    assert validator.validate_body(f"- earlier\n\n<{tag}>example</{tag}>\n\n" + nested) == []


@pytest.mark.parametrize(
    "opener",
    [
        "<table>",
        "</table>",
        "<div class='note'>",
        "<TABLE\tclass=x>",
        "<table",
        "<table/>",
        '<custom-box key="x">',
        "</custom-box>",
        "<span hidden />",
    ],
)
def test_blank_terminated_html_hides_contract_table(validator, opener):
    assert validator.validate_body(VALID_BODY.replace(HEADER, opener + "\n" + HEADER))
    assert validator.validate_body(VALID_BODY.replace(HEADER, opener + "\n\n" + HEADER)) == []


@pytest.mark.parametrize("opener", ["<table>", "<custom-box>"])
def test_blank_terminated_html_ignores_inner_markers(validator, opener):
    prefix = opener + "\n```\n<!--\n"
    assert validator.validate_body(prefix + "\n" + VALID_BODY) == []
    assert validator.validate_body("````html\n" + prefix + "````\n\n" + VALID_BODY) == []
    assert validator.validate_body("<!--\n" + opener + "\n-->\n" + VALID_BODY) == []


@pytest.mark.parametrize("opener", ["<table>", "<custom-box>"])
def test_blank_terminated_html_respects_list_boundaries(validator, opener):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    nested = "\n".join("  " + line for line in contract.splitlines())
    assert validator.validate_body("- earlier\n\n  " + opener + "\n\n" + nested)
    assert validator.validate_body("- earlier\n\n  " + opener + "\n" + contract) == []


def test_complete_custom_tag_does_not_interrupt_paragraph(validator):
    body = VALID_BODY.replace(HEADER, "A paragraph\n<custom-box>\n" + HEADER)
    assert validator.validate_body(body) == []
    assert validator.validate_body(VALID_BODY.replace(HEADER, "A paragraph\n<table>\n" + HEADER))
    assert validator.validate_body(
        VALID_BODY.replace("## Surface Impact\n\n", "## Surface Impact\n<custom-box>\n")
    )


@pytest.mark.parametrize("ending", ["    ", "\t", "=", "===", "-", "--", "---"])
def test_paragraph_ending_allows_custom_html_block(validator, ending):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    prefix = "Earlier paragraph\n" + ending + "\n<custom-box>\n"
    assert validator.validate_body(prefix + contract)
    assert validator.validate_body(prefix + "\n" + contract) == []


def test_equals_without_paragraph_is_not_setext_heading(validator):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    assert validator.validate_body("===\n<custom-box>\n" + contract) == []


@pytest.mark.parametrize(
    "text", ["<custom-box", "<custom-box> inline", "<custom-box bad= >", "<custom-box bad=`x`>"]
)
def test_incomplete_or_inline_custom_tag_keeps_markdown_table(validator, text):
    assert validator.validate_body(VALID_BODY.replace(HEADER, text + "\n" + HEADER)) == []


@pytest.mark.parametrize("marker", ["```", "````", "  ```"])
@pytest.mark.parametrize("info", [" `example`", "code`", " `"])
def test_backtick_in_fence_info_keeps_visible_contract(validator, marker, info):
    assert validator.validate_body(marker + info + "\n" + VALID_BODY) == []


def test_tilde_fence_accepts_backtick_info(validator):
    assert validator.validate_body("~~~ `example`\n" + VALID_BODY)
    assert validator.validate_body("~~~ `example`\nexample\n~~~\n" + VALID_BODY) == []


@pytest.mark.parametrize("count", [1, 3, 5])
@pytest.mark.parametrize("prefix", ["", "Ordinary prose "])
def test_escaped_comment_opener_keeps_visible_contract(validator, count, prefix):
    assert validator.validate_body(prefix + "\\" * count + "<!--\n" + VALID_BODY) == []


@pytest.mark.parametrize("count", [2, 4])
def test_even_backslashes_do_not_escape_inline_comment(validator, count):
    hidden = "Ordinary prose " + "\\" * count + "<!-- hidden -->"
    assert validator._visible_lines(hidden) == ["Ordinary prose " + "\\" * count]


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("<details>\n\n", "\n</details>"),
        ("<details>\n<summary>Assessment</summary>\n\n", "\n</details>"),
        ("<details open>\n\n", "\n</details>"),
        # The opening tag finishes on a later line and still opens the widget.
        ("<details\n open>\n\n", "\n</details>"),
        ("<details\n open>\n\n", ""),
        ("<details>\n\n", ""),
        ("<details>\n<details>\n\n", "\n</details>\n</details>"),
        # Opened from the middle of a sentence, which folds what follows just
        # as readily as an opener on a line of its own.
        ("text <details>\n\n", "\n</details>"),
        ("text <details>\n\n", ""),
        # Escaped backticks are printed, not delimiters, so the tag between them
        # is a real opener.
        ("text \\`<details>\\`\n\n", "\n</details>"),
        # A delimiter with no match anywhere in the paragraph is printed too, so
        # what follows it was never code.
        ("text ` <details>\n\n", "\n</details>"),
        ("text `\nmore <details>\n\n", "\n</details>"),
        # An opener at the start of a line is a block, which ends the paragraph
        # before it rather than continuing a span opened there.
        ("text ` ``\n<details> ``\n\n", "\n</details>"),
    ],
)
def test_collapsed_container_hides_contract(validator, prefix, suffix):
    """A blank line ends the HTML block but not the element: GitHub folds the
    heading and table into the disclosure widget, where the contract is not the
    top-level section it is required to be."""
    assert validator.validate_body(prefix + VALID_BODY + suffix)


@pytest.mark.parametrize(
    "example",
    [
        "<details>\n<summary>Logs</summary>\n\nhidden\n</details>\n\n",
        "<details>example</details>\n\n",
        "<details>\n<summary>Logs</summary>\n\nhidden\n</details>\n<details>\nmore\n</details>\n\n",
        "```html\n<details>\n```\n\n",
        "~~~html\n<details>\n~~~\n\n",
        "Mentioned `<details>` in prose.\n\n",
        "<detailsish>\n\n",
        # Left open inside a list item, and closed with it: what follows at the
        # top level is rendered there rather than folded into the widget.
        "- assessment:\n\n  <details>\n\n",
        "- text <details>\n\n",
        "text <details>x</details>\n\n",
        "text <details>\n\nnote\n</details>\n\n",
        "Documented the `<details>` wrapper in the template.\n\n",
        # An escaped angle bracket is printed rather than opening anything.
        "text \\<details>\n\n",
        # The opener is inside a code span that closes on the next line.
        "text `\ncontinued <details>`\n\n",
        # An unmatched delimiter before a real closer leaves it a real closer.
        "<details>\n\ntext ` </details>\n\n",
        # So does an inline comment opener the end of the paragraph turns to text.
        "<details>\n\ntext <!--\n\n</details>\n\n",
        # A tag that goes on to spell something that is not a tag never was one.
        '<details>\n\n<span title="\n" ! </details>\n\n',
        # The closer is on the same line as the opener the paragraph turns to text.
        "<details>\n\ntext <!-- </details>\n\n",
        # One that does finish is a tag, and takes its attribute text with it.
        '<details>\n\n<span title="\n" id="x"> </details>\n\n',
    ],
)
def test_closed_or_quoted_details_keeps_visible_contract(validator, example):
    assert validator.validate_body(example + VALID_BODY) == []


@pytest.mark.parametrize(
    "quoted",
    [
        "`</details>`",
        "<!-- </details> -->",
        "<!--\n</details>\n-->",
        "```\n</details>\n```",
        "~~~\n</details>\n~~~",
        '<span title="</details>">',
        "<span title='</details>'></span>",
        # A closing tag takes no attributes and no slash, so neither is one.
        "A literal </details foo> marker.",
        "A literal </details/> marker.",
        # The tag runs past the end of the line, and what it encloses is
        # attribute text rather than a tag of its own.
        '<span\ntitle="</details>">',
        # The `>` that would finish the tag early is inside the quoted value.
        '<span\n title="> </details>">',
        # The value opens on one line and the misleading `>` is on the next.
        '<span title="\nx> </details>">',
        # Split across lines, a closer is printed rather than acted on.
        "text </details\n> more",
        # One code span, opened on one line and closed on the next.
        "text `\ncontinued </details>`",
        # A matched span before the tag hides nothing after itself.
        "text `x` <details>",
    ],
)
def test_a_quoted_closing_tag_does_not_reopen_the_document(validator, quoted):
    """GFM renders a closer written as code or inside a comment; it does not end
    the element, so the section after it is still folded away."""
    assert validator.validate_body("<details>\n\n" + quoted + "\n\n" + VALID_BODY)


@pytest.mark.parametrize(
    "body",
    [
        "<details>\n</details>\n\n",
        "<details>\n\nnote\n</details>\n\n",
        "<details>\n\n```\nx\n```\n</details>\n\n",
        # Quotes around it are prose, not an attribute: the renderer passes the
        # tag through and the widget ends there.
        '<details>\n\nHe wrote "</details>" here.\n\n',
        "<details>\n\ntext </details > more\n\n",
        '<details>\n\n<span\ntitle="x">\n</details>\n\n',
        # An unfinished tag is inline HTML, and a block ends the paragraph that
        # holds it: what follows is text, and the closer in it is a real one.
        '<details>\n\n<span title="\n> </details>">\n\n',
        '<details>\n\n<span title="\n\n</details>\n\n',
        '<details>\n\n<span title="\n# note\n</details>\n\n',
        # A bare quote where an attribute name belongs is not a tag the renderer
        # will ever finish, so it is text and the closer after it is real.
        '<details>\n\n<span "\nx > </details>">\n\n',
        "<details>\n\n</details foo\n> </details>\n\n",
    ],
)
def test_a_real_closing_tag_ends_the_collapsed_state(validator, body):
    assert validator.validate_body(body + VALID_BODY) == []


@pytest.mark.parametrize(
    "marker", ["", "  ", "> ", "> > ", "- ", "1. ", "-    ", "-     "]
)
def test_a_block_comment_inside_a_disclosure_keeps_hiding(validator, marker):
    """A comment that begins its own block runs to `-->` through blank lines, so
    the closer and the section inside it are commented out rather than rendered.
    Inside a blockquote or a list item the block begins after the marker, and a
    marker may be followed by more padding than a block may be indented by."""
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact"):]
    inside = "\n".join(marker + line for line in ["<!--", "</details>", "-->"])
    assert validator.validate_body("<details>\n\n" + inside + "\n" + contract)


@pytest.mark.parametrize(
    "hidden",
    [
        # The text an unmatched opener seemed to hide is read again, line by
        # line, so a span across the break inside it is still a span.
        "text <!-- `\ncontinued </details>`",
        # And a comment inside it is still a comment until `-->`.
        "text ` <!--\ncontinued </details> -->",
    ],
)
def test_replayed_text_keeps_what_it_hides(validator, hidden):
    assert validator.validate_body("<details>\n\n" + hidden + "\n\n" + VALID_BODY)


@pytest.mark.parametrize(
    "opener", ["    <!--", "-      <!--"]
)
def test_an_indented_comment_opener_is_code_not_a_block(validator, opener):
    """Four spaces make an indented code block, where the opener is printed, so
    the closing tag after it still ends the disclosure. A list marker may pad its
    content by four, and past that the content is code again."""
    assert validator.validate_body(
        "<details>\n\n" + opener + "\n\n</details>\n-->\n\n" + VALID_BODY) == []


@pytest.mark.parametrize(
    "code",
    [
        "    </details>",
        # The block runs on, so a closer on its second line is printed too.
        "    code\n    </details>",
        "    code\n\n    </details>",
        # Inside a container the block begins after the marker, so indentation,
        # a blank line and a fence are all read from there.
        ">     </details>",
        "-     </details>",
        "> \n>     </details>",
        "> ```\n> </details>\n> ```",
    ],
)
def test_an_indented_closing_tag_is_code_not_a_closer(validator, code):
    """Indented four spaces where a block may begin it is printed, so it ends
    nothing and what follows is still folded away."""
    assert validator.validate_body("<details>\n\n" + code + "\n\n" + VALID_BODY)


@pytest.mark.parametrize("closer", ["</details>", "> </details>"])
def test_a_closing_tag_after_indented_code_still_ends_it(validator, closer):
    assert validator.validate_body(
        "<details>\n\n    code\n\n" + closer + "\n\n" + VALID_BODY) == []


@pytest.mark.parametrize(
    "inside",
    [
        # Four spaces is two inside the item, which is prose, not code.
        "- item\n\n    </details>",
        # And the same after a fenced block that has closed.
        "- item\n\n    ~~~\n    x\n    ~~~\n    </details>",
        # Nested, the indentation of each item adds to the one holding it.
        "- outer\n  - inner\n\n      </details>",
        "- one\n- two\n\n    </details>",
    ],
)
def test_a_closing_tag_inside_a_list_item_still_ends_the_disclosure(validator, inside):
    """A list item carries its content indentation down the lines that follow it,
    so what looks indented from the margin is at the item's own margin."""
    assert validator.validate_body("<details>\n\n" + inside + "\n\n" + VALID_BODY) == []


@pytest.mark.parametrize(
    "inside",
    [
        "- item\n\n    ~~~\n    </details>\n    ~~~",
        # Four spaces past the inner item's own margin is code again.
        "- outer\n  - inner\n\n        </details>",
    ],
)
def test_code_inside_a_list_item_still_hides_its_closer(validator, inside):
    assert validator.validate_body("<details>\n\n" + inside + "\n\n" + VALID_BODY)


@pytest.mark.parametrize("tag", ["script", "style", "textarea", "pre"])
def test_a_closer_beside_a_stripped_raw_tag_still_ends_the_disclosure(validator, tag):
    """GitHub escapes these tags rather than passing their bodies through, so a
    closing tag written between them is a tag and the contract is visible."""
    raw = f"<{tag}>\n</details>\n</{tag}>"
    assert validator.validate_body("<details>\n\n" + raw + "\n\n" + VALID_BODY) == []


@pytest.mark.parametrize(
    "prose",
    [
        # Indentation does not interrupt a paragraph, so the tag is still a tag.
        "text\n    </details>",
        # A list marker needs whitespace after it, so this is ordinary text and
        # the opener it carries is inline.
        "-<!--\n\n</details>",
        "1.<!--\n\n</details>",
    ],
)
def test_a_tag_in_continuing_prose_still_ends_the_disclosure(validator, prose):
    assert validator.validate_body("<details>\n\n" + prose + "\n\n" + VALID_BODY) == []


def test_a_contract_nested_under_an_open_details_stays_hidden(validator):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact"):]
    nested = "\n".join("  " + line for line in contract.splitlines())
    assert validator.validate_body("- assessment:\n\n  <details>\n\n" + nested)


def test_details_after_the_contract_does_not_hide_it(validator):
    assert validator.validate_body(
        VALID_BODY + "\n<details>\n<summary>Logs</summary>\n\nhidden\n</details>\n") == []


def test_inline_raw_html_tag_does_not_start_block(validator):
    assert validator.validate_body("Mentioned `<pre>` in prose.\n\n" + VALID_BODY) == []
    assert validator.validate_body("<!-- <pre> -->\n\n" + VALID_BODY) == []
    assert validator.validate_body("<prefix>\n\n" + VALID_BODY) == []


@pytest.mark.parametrize(
    "prefix",
    [
        "- earlier\n\nA separate paragraph.\n\n",
        "- earlier\n\n---\n",
        "- earlier\n\n# New section\n",
        "- earlier\n\n```text\nexample\n```\n\n",
        "- earlier\n\n~~~text\nexample\n~~~\n\n",
        "* * *\n\n",
        "- - -\n\n",
        "- earlier\n\n* * *\n\n",
        "- earlier\n\n- - -\n\n",
    ],
)
def test_indented_top_level_contract_after_list_ends_passes(validator, prefix):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    assert (
        validator.validate_body(prefix + "\n".join("  " + line for line in contract.splitlines()))
        == []
    )


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_nested_fence_keeps_list_context(validator, fence):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    nested = "\n".join("  " + line for line in contract.splitlines())
    assert validator.validate_body(f"- assessment:\n\n  {fence}\n  example\n  {fence}\n\n" + nested)


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_leaving_list_ends_nested_fence(validator, fence):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    assert validator.validate_body(f"- earlier\n\n  {fence}\n  example\n\n" + contract) == []


@pytest.mark.parametrize("separator", ["\n", "\n\n"])
def test_top_level_heading_ends_prior_list_or_paragraph(validator, separator):
    contract = VALID_BODY[VALID_BODY.index("## Surface Impact") :]
    assert validator.validate_body("- preceding list item" + separator + contract) == []
    assert validator.validate_body("Example `" + separator + contract + "\n`") == []


@pytest.mark.parametrize(
    "example",
    [
        "```html\n<!--\n```\n\n",
        "~~~html\n<!--\n~~~\n\n",
        "    <!--\n\n",
        "\t<!--\n\n",
        "<!--\n```\n-->\n\n",
        "Updated the `<!--` marker in the template.\n\n",
        "Updated the ``a ` <!--`` marker in the template.\n\n",
        "Used `<!--` here. <!-- hidden text -->\n\n",
    ],
)
def test_comment_and_code_states_do_not_hide_later_contract(validator, example):
    assert validator.validate_body(example + VALID_BODY) == []


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("<!--\n```\n", "\n```\n-->"),
        ("<!-- ` --> <!--\n", "\n` -->"),
        ("<!-- hidden text --> Used `<!--` here.\n\n", ""),
    ],
)
def test_code_markers_do_not_expose_hidden_comments(validator, prefix, suffix):
    assert validator.validate_body(prefix + VALID_BODY + suffix)


@pytest.mark.parametrize(
    "prefix",
    ["Ordinary prose <!--\n", "Ordinary prose <!--\n\n",
     "An unmatched ` then <!--\n", r"An escaped \` then <!--" + "\n"],
)
def test_inline_comment_cannot_hide_later_heading_or_duplicate(validator, prefix):
    assert validator.validate_body(prefix + VALID_BODY + "\n-->") == []
    assert any("exactly one" in error for error in validator.validate_body(
        VALID_BODY + prefix + VALID_BODY + "\n-->"
    ))


def test_inline_comment_marker_is_preserved_in_evidence(validator):
    evidence = "Updated `<!--` handling in `tools/validate-surface-impact.py`; regression passed."
    assert validator.validate_body(with_cell(evidence=evidence)) == []


def test_hidden_duplicate_does_not_override_visible_contract(validator):
    assert validator.validate_body("```\n" + VALID_BODY + "\n```\n" + VALID_BODY) == []
    assert validator.validate_body("<!--\n" + VALID_BODY + "\n-->\n" + VALID_BODY) == []


@pytest.mark.parametrize("heading", ["# Other", "## Other"])
def test_other_sections_do_not_supply_rows(validator, heading):
    row = f"| TUI | REQUIRED | {EVIDENCE} |\n"
    outside = f"\n{heading}\n\n{HEADER}\n| --- | --- | --- |\n{row}"
    assert validator.validate_body(outside + VALID_BODY + outside) == []
    assert "Missing Surface Impact row: TUI" in validator.validate_body(
        VALID_BODY.replace(row, "") + outside
    )


@pytest.mark.parametrize(
    "old,new",
    [
        (HEADER, "| Surface | Status | Reason | Evidence |"),
        ("| --- | --- | --- |", "| -- | --- | --- |"),
        ("| --- | --- | --- |", "| --- | --- |"),
        ("| TUI | REQUIRED |", "| TUI | REQUIRED | Extra |"),
        ("| TUI | REQUIRED |", "TUI | REQUIRED |"),
        (f"{EVIDENCE} |\n| Web UI", f"{EVIDENCE}\n| Web UI"),
        ("| Web UI |", "\n| Web UI |"),
        ("| Web UI |", "Interruption\n| Web UI |"),
        ("| Web UI |", "|\n| Web UI |"),
    ],
)
def test_malformed_table_fails(validator, old, new):
    assert validator.validate_body(VALID_BODY.replace(old, new))


def test_alignment_colons_and_outer_whitespace_pass(validator):
    body = VALID_BODY.replace("| --- | --- | --- |", "| :--- | ---: | :---: |")
    assert validator.validate_body("\n".join("  " + line for line in body.splitlines())) == []


def test_literal_pipes_must_be_escaped_even_in_backticks(validator):
    assert validator.validate_body(with_cell(evidence="Checked `a|b`; the branch passes tests."))
    assert validator._split_row(r"| TUI | REQUIRED | a\|b |") == ["TUI", "REQUIRED", r"a\|b"]
    assert len(validator._split_row(r"| TUI | REQUIRED | a\\|b |")) == 4


@pytest.mark.parametrize("mode", ["stdin", "--body-file", "--event-file"])
@pytest.mark.parametrize("valid", [True, False])
def test_cli_modes_without_project_or_site_packages(tmp_path, mode, valid):
    body = VALID_BODY if valid else "## Summary\nIncomplete PR.\n"
    if mode == "stdin":
        result = run_cli(body=body, cwd=tmp_path)
    else:
        source = tmp_path / "input.txt"
        source.write_text(
            json.dumps({"pull_request": {"body": body}}) if mode == "--event-file" else body,
            encoding="utf-8",
        )
        result = run_cli(mode, source, cwd=tmp_path)
    assert result.returncode == (0 if valid else 1), result.stderr
    assert ("contract passed" in result.stdout) == valid
    assert ("contract failed" in result.stderr) == (not valid)


@pytest.mark.parametrize(
    "event",
    [
        "{ invalid JSON",
        "null",
        "[]",
        '"text"',
        "{}",
        '{"pull_request": []}',
        '{"pull_request": null}',
        '{"pull_request": {"body": 5}}',
        '{"pull_request": {"body": false}}',
        '{"pull_request": {"body": {}}}',
    ],
)
def test_invalid_event_returns_input_error(tmp_path, event):
    source = tmp_path / "event.json"
    source.write_text(event, encoding="utf-8")
    result = run_cli("--event-file", source)
    assert result.returncode == 2
    assert "unable to read input" in result.stderr
    assert "Traceback" not in result.stderr
    assert event not in result.stderr


@pytest.mark.parametrize("pr", [{}, {"body": None}, {"body": ""}])
def test_empty_event_body_is_contract_error(tmp_path, pr):
    source = tmp_path / "event.json"
    source.write_text(json.dumps({"pull_request": pr}), encoding="utf-8")
    assert run_cli("--event-file", source).returncode == 1


@pytest.mark.parametrize("mode", ["--body-file", "--event-file"])
def test_unreadable_inputs(tmp_path, mode):
    assert run_cli(mode, tmp_path / "missing").returncode == 2
    assert run_cli(mode, tmp_path).returncode == 2
    source = tmp_path / "invalid-utf8"
    source.write_bytes(b"\xff")
    assert run_cli(mode, source).returncode == 2


def test_cli_flags_are_mutually_exclusive():
    assert run_cli("--body-file", "x", "--event-file", "y").returncode == 2


def test_stdin_is_not_overridden_by_github_environment():
    env = dict(os.environ, GITHUB_EVENT_PATH="missing-event.json")
    assert run_cli(body=VALID_BODY, env=env).returncode == 0


def test_input_text_is_not_executed(tmp_path):
    target = tmp_path / "should-not-exist"
    body = VALID_BODY + f'\n## Notes\n$(touch "{target}")\n'
    assert run_cli(body=body, cwd=tmp_path).returncode == 0
    assert not target.exists()


def test_template_structure_is_valid_but_completion_is_required(validator):
    template = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    rows, errors = validator.parse_surface_rows(template)
    assert errors == []
    assert tuple(rows) == SURFACES
    assert all(cells[1] == "REPLACE WITH STATUS" for cells in rows.values())
    assert len(validator.validate_body(template)) == len(SURFACES)
    completed = template.replace("REPLACE WITH STATUS", "REQUIRED").replace(
        "REPLACE WITH evidence or technical reason", EVIDENCE
    )
    assert validator.validate_body(completed) == []
    assert set(re.findall(r"^- `([^`]+)`:", template, re.MULTILINE)) == STATUSES


def test_normative_document_matches_canonical_contract():
    document = (ROOT / "docs/surface-parity.md").read_text(encoding="utf-8")
    rows = [line.split("|")[1].strip() for line in document.splitlines() if line.startswith("| ")][
        2:
    ]
    assert tuple(rows) == SURFACES
    statuses = document.split("## Allowed statuses\n", 1)[1].split("Illustrative evidence", 1)[0]
    assert set(re.findall(r"^- `([^`]+)`:", statuses, re.MULTILINE)) == STATUSES
    assert HEADER in document


@pytest.mark.parametrize("name", ["docs/architecture.md", "docs/surface-parity.md"])
def test_documentation_distinguishes_browser_automation_and_web_ui(name):
    document = (ROOT / name).read_text(encoding="utf-8")
    assert "src/comodor/browser/" in document
    assert "src/comodor/web/" in document


@pytest.mark.parametrize("name", [".github/PULL_REQUEST_TEMPLATE.md", "docs/surface-parity.md"])
def test_merge_requires_separate_authorization(name):
    document = (ROOT / name).read_text(encoding="utf-8")
    assert "Creating or updating this PR does not authorize merge." in document
    assert (
        "Agents must not merge or enable auto-merge unless the user separately and explicitly "
        "authorizes this exact PR."
    ) in document


def test_workflow_uses_unprivileged_event_and_separate_jobs():
    text = (ROOT / ".github/workflows/surface-contract.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"pull_request"}
    assert set(triggers["pull_request"]["types"]) >= {
        "opened",
        "edited",
        "synchronize",
        "reopened",
        "ready_for_review",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in text
    assert "${{ github.event.pull_request.body" not in text
    jobs = workflow["jobs"]
    assert set(jobs) == {"surface-impact", "capability-map"}
    for job in jobs.values():
        assert "permissions" not in job
        assert "environment" not in job
        assert job["timeout-minutes"] <= 10
        checkout = next(
            step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["persist-credentials"] is False
    validation = [step["run"] for step in jobs["surface-impact"]["steps"] if "run" in step]
    assert validation == [
        'python tools/validate-surface-impact.py --event-file "$GITHUB_EVENT_PATH"',
    ]
    capability = [step["run"] for step in jobs["capability-map"]["steps"] if "run" in step]
    assert capability == [
        "python -m pip install -e .",
        "python tools/capability-map.py --check",
    ]
