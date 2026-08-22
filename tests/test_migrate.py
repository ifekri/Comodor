"""Bringing settings over from another agent.

Somebody arriving from OpenClaw or Hermes has already found their API keys and
pasted them somewhere. Asking them to do it again is the first impression.

The fixtures here are the real shapes, taken from those projects rather than
invented: OpenClaw keeps a JSON file whose name changed twice across two
rebrands and inlines keys under `models.providers`, Hermes keeps a `.env` and a
`config.yaml`. Most of what is checked is restraint — that nothing is
overwritten, nothing is moved, and a file in an odd state is skipped rather
than fatal.
"""

from __future__ import annotations

import json

import pytest

from comodor import catalogue, migrate
from comodor.config import provider_from_spec


@pytest.fixture
def configured(config):
    """The shared fixture carries one fake provider; a real `load` builds a
    slot for every provider in the catalogue. The import is asked about
    Anthropic, so Anthropic has to be there to have an opinion about."""
    config.providers["anthropic"] = provider_from_spec(catalogue.get("anthropic"))
    return config


def openclaw(home, name=".openclaw", **parts):
    root = home / name
    (root / "skills").mkdir(parents=True)
    document = parts.pop("config", {
        "models": {"providers": {
            "anthropic": {"apiKey": "sk-ant-from-openclaw",
                          "baseUrl": "https://api.anthropic.com/v1"},
        }},
        "agents": {"defaults": {"model": "claude-sonnet-5"}},
    })
    (root / parts.pop("config_name", "openclaw.json")).write_text(
        json.dumps(document), encoding="utf-8")
    return root


def hermes(home, env="OPENAI_API_KEY=sk-openai-from-hermes\n",
           config="model: gpt-4o\nverbose: true\n"):
    root = home / ".hermes"
    (root / "skills").mkdir(parents=True)
    (root / ".env").write_text(env, encoding="utf-8")
    (root / "config.yaml").write_text(config, encoding="utf-8")
    return root


def skill(folder, name, body="Do the thing."):
    made = folder / name
    made.mkdir(parents=True, exist_ok=True)
    (made / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A skill\n---\n\n{body}\n",
        encoding="utf-8")
    return made


# --------------------------------------------------------------------------- #
# finding it
# --------------------------------------------------------------------------- #


def test_nothing_installed_is_not_an_error(tmp_path):
    assert migrate.discover(tmp_path) == []


def test_it_finds_openclaw(tmp_path):
    openclaw(tmp_path)

    found = migrate.discover(tmp_path)

    assert [entry.tool for entry in found] == ["OpenClaw"]
    assert found[0].keys["ANTHROPIC_API_KEY"] == "sk-ant-from-openclaw"
    assert found[0].model == "claude-sonnet-5"


def test_it_finds_hermes(tmp_path):
    hermes(tmp_path)

    found = migrate.discover(tmp_path)

    assert [entry.tool for entry in found] == ["Hermes"]
    assert found[0].keys["OPENAI_API_KEY"] == "sk-openai-from-hermes"
    assert found[0].model == "gpt-4o"


def test_it_finds_both(tmp_path):
    openclaw(tmp_path)
    hermes(tmp_path)

    assert {entry.tool for entry in migrate.discover(tmp_path)} == \
        {"OpenClaw", "Hermes"}


@pytest.mark.parametrize("folder, name", [
    (".openclaw", "openclaw.json"),
    (".clawdbot", "clawdbot.json"),
    (".moltbot", "moltbot.json"),
])
def test_the_two_rebrands_are_still_on_real_machines(tmp_path, folder, name):
    """It was clawd, then clawdbot, then moltbot, then OpenClaw. Somebody who
    installed it early still has the old directory."""
    openclaw(tmp_path, name=folder, config_name=name)

    found = migrate.discover(tmp_path)

    assert found and found[0].tool == "OpenClaw"
    assert found[0].keys


def test_an_empty_installation_is_not_offered(tmp_path):
    """Offering to import nothing is a question that wastes somebody's time."""
    (tmp_path / ".hermes").mkdir()

    assert migrate.discover(tmp_path) == []


# --------------------------------------------------------------------------- #
# reading other people's files
# --------------------------------------------------------------------------- #


def test_a_dotenv_is_read_the_way_people_write_them(tmp_path):
    root = tmp_path / ".hermes"
    root.mkdir()
    (root / ".env").write_text(
        "# a comment\n"
        "\n"
        "export ANTHROPIC_API_KEY=sk-exported\n"
        'OPENAI_API_KEY="sk-quoted"\n'
        "GROQ_API_KEY = sk-spaced \n"
        "DEEPSEEK_API_KEY=sk-trailing  # why\n"
        "NOT_A_KEY=ignored\n"
        "EMPTY_API_KEY=\n"
        "TEMPLATED_API_KEY=${SOMETHING_ELSE}\n",
        encoding="utf-8")

    keys = migrate._read_env(root / ".env")

    assert keys["ANTHROPIC_API_KEY"] == "sk-exported"
    assert keys["OPENAI_API_KEY"] == "sk-quoted"
    assert keys["GROQ_API_KEY"] == "sk-spaced"
    assert keys["DEEPSEEK_API_KEY"] == "sk-trailing"
    assert "NOT_A_KEY" not in keys
    assert "EMPTY_API_KEY" not in keys
    assert "TEMPLATED_API_KEY" not in keys, "a template means nothing here"


def test_a_key_stored_somewhere_else_is_reported_not_guessed(tmp_path):
    """OpenClaw lets a key be a reference to a file or a command. Those mean
    something on the machine they were written for and nothing here."""
    openclaw(tmp_path, config={"models": {"providers": {
        "anthropic": {"apiKey": {"source": "exec", "command": "pass show key"},
                      "baseUrl": "https://api.anthropic.com"}}}})

    found = migrate.discover(tmp_path)

    assert found == [] or not found[0].keys
    if found:
        assert any("stored elsewhere" in note for note in found[0].passed_over)


def test_a_model_written_as_an_object_is_understood(tmp_path):
    openclaw(tmp_path, config={
        "models": {"providers": {"a": {"apiKey": "sk-x",
                                       "baseUrl": "https://api.openai.com"}}},
        "agents": {"defaults": {"model": {"primary": "gpt-4o",
                                          "fallback": "gpt-4o-mini"}}}})

    assert migrate.discover(tmp_path)[0].model == "gpt-4o"


def test_a_broken_config_is_skipped_not_fatal(tmp_path):
    """Half the value of this is that it runs on a machine whose other agent is
    in an odd state."""
    root = tmp_path / ".openclaw"
    (root / "skills").mkdir(parents=True)
    (root / "openclaw.json").write_text("{ this is not json", encoding="utf-8")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-still-here\n", encoding="utf-8")

    found = migrate.discover(tmp_path)

    assert found[0].keys["ANTHROPIC_API_KEY"] == "sk-still-here"


def test_yaml_is_not_pretended_to_be_parsed(tmp_path):
    """Only a top-level scalar is read. Anything structured is left alone
    rather than half-understood."""
    hermes(tmp_path, config="model:\n  primary: gpt-4o\nother: 1\n")

    found = migrate.discover(tmp_path)

    assert found[0].model == "", "a nested value should not be guessed at"


# --------------------------------------------------------------------------- #
# taking it
# --------------------------------------------------------------------------- #


def test_a_key_you_already_have_is_never_replaced(configured, tmp_path):
    """Somebody who configured a key here meant it."""
    openclaw(tmp_path)
    configured.providers["anthropic"].api_key = "sk-mine"

    outcome = migrate.apply(migrate.discover(tmp_path)[0], configured)

    assert configured.providers["anthropic"].api_key == "sk-mine"
    assert any("already have a key" in note for note in outcome.skipped)
    assert "Anthropic" not in outcome.keys


def test_a_gap_is_filled(configured, tmp_path):
    openclaw(tmp_path)
    configured.providers["anthropic"].api_key = ""

    outcome = migrate.apply(migrate.discover(tmp_path)[0], configured)

    assert configured.providers["anthropic"].api_key == "sk-ant-from-openclaw"
    assert outcome.keys == ["Anthropic"]


def test_the_model_is_taken_only_when_something_here_offers_it(config, tmp_path):
    openclaw(tmp_path, config={
        "models": {"providers": {}},
        "agents": {"defaults": {"model": "some-model-of-theirs"}}})
    config.model = ""

    outcome = migrate.apply(migrate.discover(tmp_path)[0], config)

    assert config.model == ""
    assert any("no provider here offers it" in note for note in outcome.skipped)


def test_a_model_this_agent_knows_is_taken(config, tmp_path):
    openclaw(tmp_path)
    config.model = ""

    migrate.apply(migrate.discover(tmp_path)[0], config)

    assert config.model == "claude-sonnet-5"


def test_your_own_choice_of_model_survives(config, tmp_path):
    openclaw(tmp_path)
    config.model = "claude-opus-5"

    migrate.apply(migrate.discover(tmp_path)[0], config)

    assert config.model == "claude-opus-5"


# --------------------------------------------------------------------------- #
# skills
# --------------------------------------------------------------------------- #


def test_skills_are_copied_and_namespaced(config, tmp_path):
    root = openclaw(tmp_path)
    skill(root / "skills", "review")

    outcome = migrate.apply(migrate.discover(tmp_path)[0], config)

    assert outcome.skills == ["openclaw-review"]
    assert (config.paths.skills / "openclaw-review" / "SKILL.md").is_file()


def test_an_import_cannot_replace_a_skill_of_your_own(config, tmp_path):
    """Which is what the namespace is for."""
    root = openclaw(tmp_path)
    skill(root / "skills", "review")
    config.paths.skills.mkdir(parents=True, exist_ok=True)
    mine = config.paths.skills / "review"
    mine.mkdir()
    (mine / "SKILL.md").write_text("mine\n", encoding="utf-8")

    migrate.apply(migrate.discover(tmp_path)[0], config)

    assert (mine / "SKILL.md").read_text() == "mine\n"


def test_the_original_is_left_where_it_was(config, tmp_path):
    """Copy, never move: the other tool has to keep working."""
    root = openclaw(tmp_path)
    theirs = skill(root / "skills", "review")

    migrate.apply(migrate.discover(tmp_path)[0], config)

    assert (theirs / "SKILL.md").is_file()


def test_a_single_file_skill_is_taken_too(config, tmp_path):
    root = openclaw(tmp_path)
    (root / "skills" / "notes.md").write_text(
        "---\nname: notes\ndescription: x\n---\n\nDo it.\n", encoding="utf-8")

    outcome = migrate.apply(migrate.discover(tmp_path)[0], config)

    assert outcome.skills == ["openclaw-notes.md"]


def test_something_far_too_large_to_be_a_skill_is_left(config, tmp_path):
    root = openclaw(tmp_path)
    huge = skill(root / "skills", "huge")
    (huge / "SKILL.md").write_text("x" * (migrate.MAX_SKILL_BYTES + 10),
                                   encoding="utf-8")

    outcome = migrate.apply(migrate.discover(tmp_path)[0], config)

    assert outcome.skills == []


# --------------------------------------------------------------------------- #
# what is deliberately left behind
# --------------------------------------------------------------------------- #


def test_a_memory_file_is_noticed_and_not_imported(tmp_path):
    """Their memory is prose. This agent's is lessons with confidence and
    evidence, and inventing those would poison recall with entries nothing
    earned."""
    root = openclaw(tmp_path)
    (root / "MEMORY.md").write_text("- remember the thing\n", encoding="utf-8")

    found = migrate.discover(tmp_path)[0]

    assert any("MEMORY.md" in note for note in found.passed_over)
    assert any("poison recall" in note for note in found.passed_over)


def test_a_persona_is_noticed_and_not_imported(tmp_path):
    root = openclaw(tmp_path)
    (root / "SOUL.md").write_text("You are a pirate.\n", encoding="utf-8")

    found = migrate.discover(tmp_path)[0]

    assert any("SOUL.md" in note for note in found.passed_over)


def test_no_key_is_ever_printed(tmp_path):
    """A key on screen is a key in a scrollback buffer."""
    openclaw(tmp_path)
    found = migrate.discover(tmp_path)[0]

    assert "sk-ant-from-openclaw" not in found.summary()
    assert "1 API key" in found.summary()


# --------------------------------------------------------------------------- #
# leaving a configuration that runs
# --------------------------------------------------------------------------- #


def test_a_provider_that_gets_a_key_is_marked_configured(configured, tmp_path):
    """It has a key and the agent will use it; that is what the flag means.
    Left false, `doctor` reports a working provider as one never set up."""
    openclaw(tmp_path)
    configured.providers["anthropic"].api_key = ""
    configured.providers["anthropic"].configured = False

    migrate.apply(migrate.discover(tmp_path)[0], configured)

    assert configured.providers["anthropic"].configured
    assert configured.providers["anthropic"].enabled


def test_an_import_settles_which_provider_is_active(configured, tmp_path):
    """Otherwise `active()` falls back to whichever provider happens to have a
    key — right once, and arbitrary as soon as there are two."""
    openclaw(tmp_path)
    configured.provider = ""
    configured.model = ""

    migrate.apply(migrate.discover(tmp_path)[0], configured)

    assert configured.provider == "anthropic"


def test_the_provider_chosen_is_the_one_that_serves_the_model(config, tmp_path):
    """Two keys arrive together. The one that can actually run the imported
    model wins, rather than whichever sorted first."""
    root = tmp_path / ".hermes"
    root.mkdir()
    (root / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-ant\nOPENAI_API_KEY=sk-openai\n", encoding="utf-8")
    (root / "config.yaml").write_text("model: gpt-4o\n", encoding="utf-8")
    config.provider = ""
    config.model = ""

    migrate.apply(migrate.discover(tmp_path)[0], config)

    assert config.model == "gpt-4o"
    assert config.provider == "openai", "the key that cannot run gpt-4o was chosen"


def test_a_provider_you_already_chose_is_not_changed(configured, tmp_path):
    openclaw(tmp_path)
    configured.provider = "openrouter"

    migrate.apply(migrate.discover(tmp_path)[0], configured)

    assert configured.provider == "openrouter"


# --------------------------------------------------------------------------- #
# what a skill folder is allowed to contain
# --------------------------------------------------------------------------- #


def test_a_link_out_of_the_folder_is_refused(config, tmp_path):
    """A skill is a file whose contents are read into a prompt. A link in
    somebody else's directory pointing at their private key would otherwise
    have been copied in and then sent to a model."""
    root = openclaw(tmp_path)
    folder = skill(root / "skills", "sneaky")
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY\n", encoding="utf-8")
    try:
        (folder / "notes.md").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("this platform will not make a symlink here")

    outcome = migrate.apply(migrate.discover(tmp_path)[0], config)

    assert outcome.skills == []
    assert not (config.paths.skills / "openclaw-sneaky").exists()
    for path in config.paths.skills.rglob("*"):
        assert "PRIVATE KEY" not in path.read_text(errors="ignore") \
            if path.is_file() else True


def test_the_size_budget_is_the_whole_folder_not_one_file(config, tmp_path):
    """`SKILL.md` being small says nothing about the gigabyte beside it."""
    root = openclaw(tmp_path)
    folder = skill(root / "skills", "heavy")
    (folder / "references").mkdir()
    (folder / "references" / "dump.md").write_text(
        "x" * (migrate.MAX_SKILL_TREE_BYTES + 10), encoding="utf-8")

    outcome = migrate.apply(migrate.discover(tmp_path)[0], config)

    assert outcome.skills == []


def test_a_folder_of_references_still_comes_over(config, tmp_path):
    """The limits must not refuse an ordinary skill. The largest one this
    project ships is well under a hundred kilobytes."""
    root = openclaw(tmp_path)
    folder = skill(root / "skills", "taste")
    (folder / "references").mkdir()
    for index in range(5):
        (folder / "references" / f"part-{index}.md").write_text(
            "prose\n" * 500, encoding="utf-8")

    outcome = migrate.apply(migrate.discover(tmp_path)[0], config)

    assert outcome.skills == ["openclaw-taste"]
    landed = config.paths.skills / "openclaw-taste"
    assert (landed / "SKILL.md").is_file()
    assert len(list((landed / "references").glob("*.md"))) == 5


def test_a_skill_that_did_not_arrive_is_named(config, tmp_path):
    """Silence would read as the import being broken."""
    root = openclaw(tmp_path)
    folder = skill(root / "skills", "heavy")
    (folder / "big.md").write_text("x" * (migrate.MAX_SKILL_TREE_BYTES + 10),
                                   encoding="utf-8")

    found = migrate.discover(tmp_path)[0]
    migrate.apply(found, config)

    assert any("heavy" in note for note in found.passed_over)
