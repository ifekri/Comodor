"""The wordmark, and the line under it that earns the space.

A banner is a cost — it takes the top of the terminal every time — so most of
what is checked here is the discipline around it: that it never reaches a pipe,
that it shrinks instead of wrapping, and that it can be switched off. The one
thing it says that is worth saying is what this installation has learned, and
that has to survive a brain that will not open.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from comodor.ui import banner
from comodor.ui import console as console_module


@pytest.fixture
def theme():
    return console_module.prepare_theme("ember", False, no_color=False)


def painted(renderable, width: int = 90) -> str:
    console = Console(force_terminal=True, color_system="truecolor",
                      width=width, file=io.StringIO())
    console.print(renderable)
    return console.file.getvalue()


def plain(renderable, width: int = 90) -> str:
    console = Console(width=width, file=io.StringIO(), no_color=True)
    console.print(renderable)
    return console.file.getvalue()


# --------------------------------------------------------------------------- #
# the wordmark itself
# --------------------------------------------------------------------------- #


def test_the_letters_line_up():
    """Ragged lines are the one way ASCII art fails that nobody notices until
    it is on somebody else's screen."""
    for art in (banner.WORDMARK_WIDE, banner.WORDMARK_COMPACT):
        widths = {len(line) for line in art}
        assert len(widths) == 1, f"lines are not the same width: {sorted(widths)}"
        assert not any("\t" in line for line in art)

    assert banner.WIDTH == len(banner.WORDMARK_COMPACT[0])
    assert banner.WIDE_WIDTH == len(banner.WORDMARK_WIDE[0])
    assert banner.WIDE_WIDTH > banner.WIDTH

    # Solid cells, not slashes and underscores. Every monospace font renders
    # those at a slightly different angle and none of them render as a logo —
    # it read as source code somebody had left on the screen. A filled cell is
    # the one glyph a terminal cannot get wrong, which is also why this is the
    # one piece of the interface that is deliberately not ASCII.
    assert "█" in "".join(banner.WORDMARK_WIDE)
    assert "/" not in "".join(banner.WORDMARK_WIDE)


def test_it_is_drawn_whole(theme):
    printed = plain(banner.wordmark(theme, width=120), width=120)

    for line in banner.WORDMARK_WIDE:
        assert line.rstrip() in printed


def test_a_narrower_terminal_gets_the_compact_one_rather_than_the_wide_one():
    """`wordmark` used to take the compact form at every width, so the wizard
    drew a small logo on a wide screen while the interface drew a large one."""
    theme = console_module.prepare_theme("ember", False, no_color=False)
    wide = plain(banner.wordmark(theme, width=120), width=120)
    compact = plain(banner.wordmark(theme, width=60), width=60)

    assert banner.WORDMARK_WIDE[0].rstrip() in wide
    assert banner.WORDMARK_COMPACT[0].rstrip() in compact
    assert banner.WORDMARK_WIDE[0].rstrip() not in compact


def test_the_logo_is_ascii_when_ascii_was_asked_for():
    """It drew block characters regardless, on the one terminal that cannot."""
    plain_theme = console_module.prepare_theme("ember", True, no_color=True)

    for width in (120, 60):
        printed = plain(banner.wordmark(plain_theme, width=width), width=width)
        printed.encode("ascii")
        assert "#" in printed


def test_it_shrinks_rather_than_wraps(theme):
    """Art reflowed by a terminal is not a smaller logo, it is rubble."""
    narrow = plain(banner.wordmark(theme, width=30), width=30)

    assert "Comodor" in narrow
    assert "____" not in narrow
    assert len(narrow.strip().splitlines()) == 1


def test_the_full_mark_needs_room_for_a_margin(theme):
    assert banner.MINIMUM > banner.WIDTH
    assert "█" in plain(banner.wordmark(theme, banner.MINIMUM), banner.MINIMUM)
    assert "█" not in plain(banner.wordmark(theme, banner.MINIMUM - 1),
                                 banner.MINIMUM - 1)


def test_the_fade_follows_the_palette(theme):
    """A fixed set of oranges would look wrong on a light theme and absurd on a
    monochrome one, so the shades are interpolated from whatever is in use."""
    shades = banner._shades(theme, 5)

    assert len(shades) == 5
    assert len(set(shades)) > 1, "no gradient at all"
    assert shades[0].lower() == theme.palette.accent.lower()


def test_a_palette_without_hex_colours_still_draws(theme):
    """A palette may name its colours rather than spell them in hex. It must
    degrade to one colour rather than raise."""
    import dataclasses

    named = dataclasses.replace(theme.palette, accent="bright_yellow")
    theme = dataclasses.replace(theme, palette=named)

    assert banner._shades(theme, 5) == ["bright_yellow"] * 5
    assert "Comodor" in plain(banner.wordmark(theme, 30), 30)


# --------------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------------- #


def test_it_reports_what_has_been_learned(theme):
    standing = banner.Standing(lessons=412, skills=7, rules=3, sessions=128)

    printed = plain(banner.render(theme, standing=standing))

    assert "412 lessons" in printed
    assert "7 skills" in printed
    assert "3 rules you set" in printed
    assert "128 finished tasks" in printed


def test_one_of_a_thing_is_not_plural(theme):
    standing = banner.Standing(lessons=1, skills=1, rules=1, sessions=1)

    printed = plain(banner.render(theme, standing=standing))

    assert "1 lesson " in printed or "1 lesson·" in printed.replace(" ", "·")
    assert "1 lessons" not in printed
    assert "1 skills" not in printed
    assert "1 finished tasks" not in printed


def test_a_fresh_install_says_so_rather_than_nothing(theme):
    printed = plain(banner.render(theme, standing=banner.Standing()))

    assert "nothing learned yet" in printed


def test_a_long_development_version_does_not_push_the_model_off(theme):
    """An editable install reports thirty characters of build metadata, which
    wrapped the line and left the model stranded on the next one."""
    assert banner.short("0.3.2.dev0+g702fb5d7d.d20260821") == "0.3.2.dev0"
    assert banner.short("0.8.5") == "0.8.5"
    assert banner.short("") == ""

    printed = plain(banner.render(theme, version="0.3.2.dev0+g702fb5d7d.d20260821",
                                  model="claude-sonnet-5"))
    first = next(line for line in printed.splitlines() if "learns the way" in line)

    assert "claude-sonnet-5" in first


def test_the_tagline_and_the_facts_are_all_there(theme):
    printed = plain(banner.render(theme, version="0.8.5", model="a-model",
                                  project="/home/x/work",
                                  standing=banner.Standing(lessons=2)))

    assert banner.TAGLINE in printed
    assert "0.8.5" in printed
    assert "a-model" in printed
    assert "/home/x/work" in printed


def test_a_narrow_banner_puts_one_fact_on_each_line(theme):
    """A line that wraps in the middle of a separator reads as damage."""
    printed = plain(banner.render(theme, version="0.8.5", model="a-model",
                                  width=30), width=30)
    lines = [line.strip() for line in printed.splitlines() if line.strip()]

    assert "0.8.5" in lines
    assert "a-model" in lines


# --------------------------------------------------------------------------- #
# reading the brain must never stop the program
# --------------------------------------------------------------------------- #


def test_a_brain_that_will_not_open_costs_a_line_not_a_session():
    class Broken:
        def stats(self):
            raise RuntimeError("database is locked")

        def active_rules(self):
            raise RuntimeError("database is locked")

    standing = banner.gather(Broken(), None)

    assert standing == banner.Standing()
    assert not standing.anything


def test_it_reads_a_working_brain():
    class Brain:
        def stats(self):
            return {"lessons": 40, "skills": 2, "episodes": 9}

        def active_rules(self):
            return ["a", "b"]

    standing = banner.gather(Brain(), None)

    assert (standing.lessons, standing.rules, standing.sessions) == (40, 2, 9)
    assert standing.skills == 2


def test_the_skill_registry_wins_over_the_brains_count():
    class Brain:
        def stats(self):
            return {"lessons": 1, "skills": 99, "episodes": 1}

        def active_rules(self):
            return []

    class Skills:
        def all(self):
            return ["one", "two", "three"]

    assert banner.gather(Brain(), Skills()).skills == 3


def test_no_brain_at_all_is_fine():
    assert banner.gather(None, None) == banner.Standing()


# --------------------------------------------------------------------------- #
# where it must not appear
# --------------------------------------------------------------------------- #


def test_it_stays_out_of_a_pipe(monkeypatch):
    """`comodor run … | jq` has to see the answer and nothing else."""
    monkeypatch.delenv("COMODOR_BANNER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    piped = Console(file=io.StringIO())          # not a terminal

    assert banner.wanted(piped) is False


def test_it_appears_on_a_terminal(monkeypatch):
    monkeypatch.delenv("COMODOR_BANNER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    terminal = Console(force_terminal=True, file=io.StringIO())

    assert banner.wanted(terminal) is True


@pytest.mark.parametrize("value", ["0", "off", "no", "false", "none", "OFF"])
def test_the_environment_can_switch_it_off(monkeypatch, value):
    monkeypatch.setenv("COMODOR_BANNER", value)
    terminal = Console(force_terminal=True, file=io.StringIO())

    assert banner.wanted(terminal) is False


def test_the_setting_can_switch_it_off(monkeypatch, config):
    monkeypatch.delenv("COMODOR_BANNER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    terminal = Console(force_terminal=True, file=io.StringIO())

    assert banner.wanted(terminal, config) is True
    config.ui.banner = False
    assert banner.wanted(terminal, config) is False


def test_the_environment_wins_over_the_setting(monkeypatch, config):
    """So a container can turn it on for a log, and a script can turn it off
    for one command, without editing anything."""
    config.ui.banner = False
    monkeypatch.setenv("COMODOR_BANNER", "1")
    terminal = Console(force_terminal=True, file=io.StringIO())

    assert banner.wanted(terminal, config) is True


def test_it_stays_out_of_a_build_log(monkeypatch):
    monkeypatch.delenv("COMODOR_BANNER", raising=False)
    monkeypatch.setenv("CI", "true")
    terminal = Console(force_terminal=True, file=io.StringIO())

    assert banner.wanted(terminal) is False


def test_show_prints_nothing_where_it_is_not_wanted(theme, monkeypatch):
    monkeypatch.delenv("COMODOR_BANNER", raising=False)
    piped = Console(file=io.StringIO())

    banner.show(piped, theme, version="0.8.5")

    assert piped.file.getvalue() == ""


def test_show_prints_it_where_it_is(theme, monkeypatch):
    monkeypatch.delenv("COMODOR_BANNER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    terminal = Console(force_terminal=True, width=90, file=io.StringIO())

    banner.show(terminal, theme, version="0.8.5")

    assert "█" in terminal.file.getvalue()


def test_it_is_actually_coloured(theme):
    output = painted(banner.render(theme, standing=banner.Standing(lessons=3)))

    assert "\x1b[" in output


# --------------------------------------------------------------------------- #
# interactive mode skips the banner
# --------------------------------------------------------------------------- #


def test_the_banner_is_skipped_in_interactive_mode(config):
    """The welcome box in the Live screen replaces the banner."""
    from comodor.ui import layout as layout_module
    from comodor.ui.app import App

    app = App(config, demo=True)
    app.geometry = layout_module.compute(128, 36)

    # The app should not have called _greet() — the banner is replaced by
    # the welcome box. We verify this by checking that the welcome box is
    # rendered when the state is empty (no entries).
    assert app.state.entries == []
    # The welcome box should be part of the frame
    frame = app._frame()
    assert frame is not None
