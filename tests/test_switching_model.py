"""Changing the model, the provider or the theme in the middle of a session.

The context window is the one that bites. It is set once by the setup wizard,
from the model chosen then, and the loop compacts the conversation at a
fraction of it. Left behind after a switch to a smaller model, the agent never
compacts and the run fails at the provider's real ceiling instead - with the
gauge in the corner reading the old number the whole way there.
"""

from __future__ import annotations

import pytest

from comodor.providers import registry
from comodor.ui import layout as layout_module
from comodor.ui.app import App


@pytest.fixture
def app(config):
    """An app wired to the offline provider, with a fixed terminal size."""
    instance = App(config, demo=True)
    instance.geometry = layout_module.compute(128, 36)
    return instance


def test_the_window_follows_the_model(app):
    """A million-token window does not survive a move to a 128k model."""
    app.config.agent.context_limit = 1_000_000
    app.state.status.context_limit = 1_000_000

    app._pick_model("gpt-4o")

    expected = registry.lookup("gpt-4o").context
    assert expected < 1_000_000, "this test needs a genuinely smaller model"
    assert app.config.agent.context_limit == expected
    assert app.state.status.context_limit == expected


def test_typing_the_model_and_choosing_it_do_the_same_thing(app):
    """They had drifted: typing left the session record naming the old model,
    so a saved transcript said whichever way it had been chosen."""
    app.cmd_model("gpt-4o")
    typed = (app.config.model, app.session.model,
             app.state.status.model, app.config.agent.context_limit)

    app._pick_model("gpt-4o")
    chosen = (app.config.model, app.session.model,
              app.state.status.model, app.config.agent.context_limit)

    assert typed == chosen
    assert app.session.model == "gpt-4o"


def test_a_model_nothing_knows_leaves_the_window_alone(app):
    """A local or brand-new model is not a reason to guess at a window."""
    app.config.agent.context_limit = 200_000
    app.state.status.context_limit = 200_000

    app._pick_model("some-model-nobody-has-heard-of")

    assert app.config.model == "some-model-nobody-has-heard-of"
    assert app.config.agent.context_limit == 200_000


def test_switching_provider_moves_the_window_too(app):
    """A different provider means a different model, and a different model
    means a different window."""
    app.config.agent.context_limit = 1_000_000
    entry = app.config.providers["fake"]
    entry.model = "gpt-4o"
    entry.api_key = "x"
    entry.configured = True

    app._pick_provider("fake")

    assert app.config.agent.context_limit == registry.lookup("gpt-4o").context
    assert app.session.model == "gpt-4o"


def test_an_unknown_theme_is_refused_rather_than_reported_as_applied(app):
    """The palette table falls back to Ember for anything it does not know, so
    without checking, the toast said one thing and the screen showed another."""
    before = app.config.ui.theme

    app._apply_theme("not-a-theme")

    assert app.config.ui.theme == before
    assert any("no theme called" in str(toast.text)
               for toast in app.state.toasts.items)


def test_a_real_theme_still_applies(app):
    from comodor.ui.theme import theme_names

    name = [n for n in theme_names() if n != app.config.ui.theme][0]

    app._apply_theme(name)

    assert app.config.ui.theme == name
