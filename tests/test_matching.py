"""`edit_file` finding the text that was meant.

An exact-match edit tool has one failure mode and it is the commonest wasted
turn in any coding agent: the model reproduced the block from memory and got an
invisible character wrong. A trailing space. A CRLF where the model wrote LF.
The turn is then spent discovering that, and the discovery teaches nothing.

Two properties are load-bearing here and everything else is detail.

*A relaxed match is announced.* An edit that landed somewhere slightly
different from what was asked for, silently, is worse than one that refused.

*A relaxed match that becomes ambiguous is refused.* If ignoring whitespace
turns one intended target into three candidates, the information that told them
apart is gone, and picking one is a coin toss on somebody's source file.
"""

from __future__ import annotations

import pytest

from comodor.tools import matching
from comodor.tools.fs import EditFile


def edit(ctx, path, old, new, **extra):
    return EditFile().run(ctx, path=path, old_string=old, new_string=new, **extra)


def given(ctx, name: str, body: str):
    (ctx.cwd / name).write_text(body, encoding="utf-8", newline="")
    return ctx.cwd / name


# --------------------------------------------------------------------------- #
# exact, which must keep behaving exactly as it did
# --------------------------------------------------------------------------- #


def test_an_exact_match_is_still_an_exact_match(tool_context):
    given(tool_context, "a.py", "def f():\n    return 1\n")

    result = edit(tool_context, "a.py", "return 1", "return 2")

    assert result.ok
    assert (tool_context.cwd / "a.py").read_text() == "def f():\n    return 2\n"


def test_an_exact_match_says_nothing_about_how_it_matched(tool_context):
    given(tool_context, "a.py", "x = 1\n")

    result = edit(tool_context, "a.py", "x = 1", "x = 2")

    assert "matched after" not in result.content


def test_two_exact_matches_are_still_refused(tool_context):
    given(tool_context, "a.py", "x = 1\ny = 2\nx = 1\n")

    result = edit(tool_context, "a.py", "x = 1", "x = 3")

    assert not result.ok
    assert "matches 2 places" in result.content


def test_the_refusal_now_says_where_they_are(tool_context):
    """"Add surrounding context" is advice you cannot follow without knowing
    which places need telling apart."""
    given(tool_context, "a.py", "x = 1\ny = 2\nx = 1\n")

    result = edit(tool_context, "a.py", "x = 1", "x = 3")

    assert "lines 1, 3" in result.content


def test_replace_all_still_replaces_all(tool_context):
    given(tool_context, "a.py", "x = 1\ny = 2\nx = 1\n")

    result = edit(tool_context, "a.py", "x = 1", "x = 3", replace_all=True)

    assert result.ok
    assert (tool_context.cwd / "a.py").read_text() == "x = 3\ny = 2\nx = 3\n"


# --------------------------------------------------------------------------- #
# the rungs
# --------------------------------------------------------------------------- #


def test_a_crlf_file_edited_with_lf(tool_context):
    """The single likeliest invisible mismatch, and the default on Windows."""
    given(tool_context, "a.py", "def f():\r\n    return 1\r\n    return 2\r\n")

    result = edit(tool_context, "a.py",
                  "    return 1\n    return 2\n", "    return 3\n")

    assert result.ok, result.content
    assert "line endings" in result.content
    assert "return 3" in (tool_context.cwd / "a.py").read_text()


def test_a_trailing_space_the_model_did_not_reproduce(tool_context):
    given(tool_context, "a.py", "def f():   \n    return 1\n")

    result = edit(tool_context, "a.py", "def f():\n", "def g():\n")

    assert result.ok, result.content
    assert "trailing whitespace" in result.content
    assert "def g():" in (tool_context.cwd / "a.py").read_text()


def test_a_block_reproduced_flush_left(tool_context):
    given(tool_context, "a.py",
          "class T:\n    def f(self):\n        return 1\n")

    result = edit(tool_context, "a.py",
                  "def f(self):\n    return 1\n",
                  "def f(self):\n    return 2\n")

    assert result.ok, result.content
    assert "indentation" in result.content


def test_an_exact_match_wins_over_a_looser_one_elsewhere(tool_context):
    """A file holding both must be edited at the place that matched exactly,
    or the relaxed rungs make the tool less predictable rather than more."""
    body = "alpha();\nalpha();   \n"
    given(tool_context, "a.py", body)

    matches, _ = matching.find(body, "alpha();\n")

    assert len(matches) == 1, "the trailing-space line must not be reached"
    assert matches[0].exact
    assert matches[0].start == 0

    result = edit(tool_context, "a.py", "alpha();\n", "beta();\n")
    assert result.ok
    assert (tool_context.cwd / "a.py").read_text() == "beta();\nalpha();   \n"


# --------------------------------------------------------------------------- #
# what must never happen
# --------------------------------------------------------------------------- #


def test_a_relaxed_match_that_is_ambiguous_is_refused(tool_context):
    """Ignoring indentation makes these two lines identical. The information
    that told them apart is exactly the information that was dropped."""
    body = "if a:\n    do_it()\nif b:\n        do_it()\n"
    given(tool_context, "a.py", body)

    result = edit(tool_context, "a.py", "do_it()\n", "do_it_twice()\n")

    assert not result.ok, "it picked one of two indistinguishable places"
    assert body == (tool_context.cwd / "a.py").read_text()


def test_a_relaxed_match_is_never_silent(tool_context):
    given(tool_context, "a.py", "value = 1   \n")

    result = edit(tool_context, "a.py", "value = 1\n", "value = 2\n")

    assert result.ok
    assert "matched after" in result.content.lower(), \
        f"the edit was relaxed and said nothing: {result.content!r}"


def test_nothing_like_it_is_still_not_found(tool_context):
    given(tool_context, "a.py", "def f():\n    return 1\n")

    result = edit(tool_context, "a.py", "class Widget:\n", "class Gadget:\n")

    assert not result.ok
    assert "not found" in result.content


# --------------------------------------------------------------------------- #
# the near misses, which turn a dead turn into a correct next call
# --------------------------------------------------------------------------- #


def test_a_failure_points_at_the_closest_place(tool_context):
    given(tool_context, "a.py",
          "def one():\n    return 1\n\n\ndef two():\n    return 22222\n")

    result = edit(tool_context, "a.py",
                  "def two():\n    return 2\n", "def two():\n    return 3\n")

    assert not result.ok
    assert "closest thing in the file is at line 5" in result.content
    assert "return 22222" in result.content, "the diff should show what is there"


def test_a_file_with_nothing_similar_offers_nothing(tool_context):
    """A suggestion that is not a suggestion wastes the turn it was meant to
    save."""
    given(tool_context, "a.py", "import os\nimport sys\n")

    result = edit(tool_context, "a.py",
                  "def compute_the_thing(alpha, beta):\n    raise SystemExit\n",
                  "pass\n")

    assert not result.ok
    assert "closest thing" not in result.content


def test_the_second_and_third_candidates_are_named_not_diffed():
    haystack = "\n".join([
        "def alpha(x):", "    return x + 1", "",
        "def beta(x):", "    return x + 2", "",
        "def gamma(x):", "    return x + 3", "",
    ])

    report = matching.near_misses(haystack, "def alpha(x):\n    return x + 9")

    assert report.count("@@") <= 2, "only the closest should be diffed"
    assert "Other candidates" in report


# --------------------------------------------------------------------------- #
# the matcher on its own
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("haystack,needle", [
    ("", "x"),
    ("x", ""),
    ("\n\n\n", "y\n"),
])
def test_the_empty_cases_do_not_raise(haystack, needle):
    matches, note = matching.find(haystack, needle)

    assert matches == []
    assert isinstance(note, str)


def test_offsets_are_into_the_original_text_not_the_normalised_one():
    """The returned span is spliced straight into the file. An offset measured
    against a transformed copy would cut the file in the wrong place."""
    haystack = "alpha\r\nbeta\r\ngamma\r\n"

    matches, _ = matching.find(haystack, "beta\n")

    assert len(matches) == 1
    one = matches[0]
    assert haystack[one.start:one.end] == "beta\r\n"
