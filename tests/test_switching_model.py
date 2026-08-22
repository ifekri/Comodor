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


# --------------------------------------------------------------------------- #
# what gets said at the top of a session
# --------------------------------------------------------------------------- #


def test_a_refused_project_setting_is_reported_without_crashing(config):
    """This path had no test, and the method it called did not exist. The
    interface would have raised AttributeError on startup - for exactly the
    people the refusal was protecting."""
    config.project_refused = ["safety", "providers"]
    config.complaints = ["agent.max_steps must be a whole number; keeping 24"]
    app_ = App(config, demo=True)
    app_.geometry = layout_module.compute(128, 36)

    app_._complain_about_the_config()

    said = " ".join(str(toast.text) for toast in app_.state.toasts.items)
    assert "safety" in said
    assert "max_steps" in said


def test_a_budget_that_cannot_fire_is_said_before_the_run(config):
    """Waiting for `comodor doctor` to mention it means telling somebody who
    already suspected. It belongs where the decision to walk away is made."""
    config.agent.max_cost_usd = 5.0
    config.use("openai", api_key="sk-x", model="gpt-4o")
    app_ = App(config, demo=True)
    app_.geometry = layout_module.compute(128, 36)

    app_._warn_if_the_budget_is_a_decoration()

    said = " ".join(str(toast.text) for toast in app_.state.toasts.items)
    assert "cannot be enforced" in said and "gpt-4o" in said


def test_nothing_is_said_when_the_budget_works(config):
    config.agent.max_cost_usd = 5.0
    config.use("anthropic", api_key="sk-x", model="claude-sonnet-5")
    app_ = App(config, demo=True)
    app_.geometry = layout_module.compute(128, 36)

    app_._warn_if_the_budget_is_a_decoration()

    assert not app_.state.toasts.items


def test_nothing_is_said_for_a_model_on_your_own_machine(config):
    """It costs nothing, so there is nothing to enforce."""
    config.agent.max_cost_usd = 5.0
    config.use("ollama", model="qwen2.5-coder:14b")
    app_ = App(config, demo=True)
    app_.geometry = layout_module.compute(128, 36)

    app_._warn_if_the_budget_is_a_decoration()

    assert not app_.state.toasts.items
