"""The model writes Markdown; none of the three chat apps reads it.

Every one of them was being handed the answer as-is, so a reply arrived on
somebody's phone with the asterisks, brackets and backticks still in it. A
person reading that does not conclude the renderer is wrong — they conclude the
tool is sloppy.

Most of what is checked here is the near-misses, because output that is
*almost* right is what actually ships: bold that came out italic, an identifier
that turned into emphasis, an asterisk inside a shell command that became bold
and swallowed the rest of the line.
"""

from __future__ import annotations

import pytest

from comodor.channels.markdown import (
    FLAVOURS,
    to_slack,
    to_telegram,
    to_whatsapp,
)

EVERY = pytest.mark.parametrize("flavour", list(FLAVOURS.values()),
                                ids=lambda f: f.name)


def render(text: str, flavour) -> str:
    from comodor.channels.markdown import render as do

    return do(text, flavour)


# --------------------------------------------------------------------------- #
# the thing that was actually broken
# --------------------------------------------------------------------------- #


@EVERY
def test_no_markdown_only_punctuation_survives(flavour):
    """Backticks are not the test: Slack and WhatsApp both use them. What must
    not survive is the markup that only Markdown has."""
    out = render("Use **bold** and *italic* and [a link](https://x.dev/).",
                 flavour)

    assert "**" not in out
    assert "](" not in out
    assert "bold" in out and "italic" in out and "a link" in out


def test_telegram_gets_html_not_escaped_markdown():
    out = to_telegram("Use **`Path.resolve()`** — see [docs](https://x.dev/).")

    assert "<b>" in out and "<code>" in out
    assert '<a href="https://x.dev/">docs</a>' in out
    assert "**" not in out and "](" not in out


def test_bold_does_not_come_out_italic():
    """Bold emits `*` on Slack and WhatsApp, and running the italic pass over
    that turned every bold word italic."""
    for render_to in (to_slack, to_whatsapp):
        out = render_to("This is **important** text.")
        assert out == "This is *important* text.", out


def test_slack_uses_its_own_link_shape():
    out = to_slack("see [the docs](https://x.dev/a_b)")

    assert "<https://x.dev/a_b|the docs>" in out


def test_whatsapp_keeps_both_halves_of_a_link():
    """WhatsApp has no link markup, so dropping either half loses something."""
    out = to_whatsapp("see [the docs](https://x.dev/a)")

    assert "the docs" in out and "https://x.dev/a" in out


def test_a_bare_url_is_not_doubled_on_whatsapp():
    out = to_whatsapp("[https://x.dev/a](https://x.dev/a)")

    assert out.count("https://x.dev/a") == 1


# --------------------------------------------------------------------------- #
# code, which is the part that most needs setting apart
# --------------------------------------------------------------------------- #


@EVERY
def test_a_fenced_block_becomes_a_block(flavour):
    out = render("Try:\n\n```python\nprint('hi')\n```\n", flavour)

    assert "print('hi')" in out
    if flavour.name == "telegram":
        assert '<pre><code class="language-python">' in out
    else:
        assert out.count("```") == 2


@EVERY
def test_markup_inside_code_is_left_alone(flavour):
    """An asterisk in a shell command is not emphasis, and a `_` in a filename
    is not italics."""
    out = render("```\nrm -rf *.log && mv a_b_c d\n```", flavour)

    assert "*.log" in out
    assert "a_b_c" in out


def test_telegram_escapes_inside_a_code_block():
    """An unescaped `<` turns the rest of the message into an unclosed tag,
    and Telegram then rejects the whole thing."""
    out = to_telegram("```\nif a < b and c > d:\n```")

    assert "&lt;" in out and "&gt;" in out
    assert "if a < b" not in out


@EVERY
def test_a_block_cut_off_mid_stream_still_renders_as_code(flavour):
    """A reply is drawn while it arrives, so half a fence is the normal case,
    not an edge one."""
    out = render("Here:\n\n```python\ndef f():\n    return 1", flavour)

    assert "def f():" in out
    if flavour.name == "telegram":
        assert "<pre>" in out
    else:
        assert "```" in out


@EVERY
def test_inline_code_survives_a_line_of_prose(flavour):
    out = render("Call `Path.exists()` before `resolve()`.", flavour)

    assert "Path.exists()" in out and "resolve()" in out


# --------------------------------------------------------------------------- #
# the near-misses
# --------------------------------------------------------------------------- #


@EVERY
def test_an_identifier_is_not_italics(flavour):
    """`some_var_name` is the single most common false positive there is."""
    out = render("Rename some_var_name and __init__ carefully.", flavour)

    assert "some_var_name" in out
    if flavour.name == "telegram":
        assert "<i>" not in out


@EVERY
def test_arithmetic_is_not_emphasis(flavour):
    out = render("It ran 2 * 3 * 4 times.", flavour)

    assert "2 * 3 * 4" in out


@EVERY
def test_an_unmatched_marker_does_not_swallow_the_line(flavour):
    """A lone `**` from a truncated stream must stay text."""
    out = render("This is **not finished", flavour)

    assert "not finished" in out


@EVERY
def test_an_empty_answer_is_empty(flavour):
    assert render("", flavour) == ""


# --------------------------------------------------------------------------- #
# block shapes
# --------------------------------------------------------------------------- #


@EVERY
def test_a_heading_becomes_bold_because_none_of_them_have_headings(flavour):
    out = render("## The cause\n", flavour)

    assert "#" not in out
    assert "The cause" in out
    assert out.startswith(flavour.bold[0])


@EVERY
def test_a_bullet_becomes_a_bullet(flavour):
    out = render("- first\n- second\n", flavour)

    assert out.count("•") == 2
    assert "- first" not in out


@EVERY
def test_a_numbered_list_keeps_its_numbers(flavour):
    out = render("1. first\n2. second\n", flavour)

    assert "1. first" in out and "2. second" in out


@EVERY
def test_a_rule_is_not_three_hyphens(flavour):
    out = render("above\n\n---\n\nbelow", flavour)

    assert "---" not in out
    assert "above" in out and "below" in out


def test_a_quote_is_a_quote_on_each_of_them():
    assert "<blockquote>" in to_telegram("> mind this")
    # A raw `>`: `&gt;` renders as the character and makes no quote at all.
    assert to_slack("> mind this").startswith("> ")
    assert to_whatsapp("> mind this").startswith("> ")


def test_whatsapp_does_not_wrap_code_in_emphasis():
    """Its only monospace is a triple backtick, and `*```x```*` renders as
    neither bold nor code."""
    out = to_whatsapp("Call **`resolve()`** now.")

    assert "*```" not in out
    assert "```resolve()```" in out


# --------------------------------------------------------------------------- #
# what the bots actually send
# --------------------------------------------------------------------------- #


def test_the_telegram_reply_is_converted_not_escaped():
    """This is the bug as reported: the answer arrived with its markup in it."""
    import inspect

    from comodor.telegram import bot

    source = inspect.getsource(bot.Service._draw)
    assert "to_telegram(" in source
    assert "escape(text" not in source


def test_the_slack_reply_is_converted_not_escaped():
    import inspect

    from comodor.slack import bot

    source = inspect.getsource(bot.Service._draw)
    assert "to_slack(" in source
    assert "escape(text" not in source


def test_the_whatsapp_reply_is_converted():
    import inspect

    from comodor.whatsapp import bot

    source = inspect.getsource(bot.Service._finish)
    assert "to_whatsapp(" in source


# --------------------------------------------------------------------------- #
# what Telegram's own parser will accept
#
# Telegram rejects a message with malformed HTML *wholesale* — it never
# arrives, and nothing says why. So the shapes most likely to produce a stray
# tag are checked against the rule its parser actually enforces: every tag
# opened is closed, and every `<` that is not a tag is an entity.
# --------------------------------------------------------------------------- #


TAG = __import__("re").compile(r"</?([a-z]+)(?:\s[^>]*)?>")

TRICKY = [
    "Use **`Path.resolve()`** — see [the docs](https://docs.python.org/3/).",
    "```\nMap<String, List<int>> m; rm -rf *.log && a > b\n```",
    "**bold with `a < b` inside** and _italic_ & ~~gone~~",
    "Here:\n\n```python\ndef f():\n    return 1",
    "## Cause\n\n> it was a_b_c, 2 * 3 ago\n\n- one\n- two",
    "a < b and c > d, unquoted",
    "5 > 3 && 2 < 4",
]


@pytest.mark.parametrize("source", TRICKY)
def test_telegram_html_is_balanced(source):
    out = to_telegram(source)

    stack = []
    for match in TAG.finditer(out):
        name = match.group(1)
        if match.group(0).startswith("</"):
            assert stack and stack[-1] == name, f"stray </{name}> in {out!r}"
            stack.pop()
        else:
            stack.append(name)
    assert not stack, f"unclosed {stack} in {out!r}"


@pytest.mark.parametrize("source", TRICKY)
def test_no_raw_angle_bracket_escapes_as_text(source):
    """Every `<` that is not one of our tags has to be an entity, or Telegram
    reads the rest of the message as an unclosed tag."""
    out = to_telegram(source)
    without_tags = TAG.sub("", out)

    assert "<" not in without_tags, f"a bare `<` survived: {without_tags!r}"
