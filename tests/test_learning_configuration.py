"""Configuration-derived rules carry their own evidence identity (T111;
FR-060, FR-114, SC-032; review 4042406579).

A rule read from the project's configuration — "tests run with pytest",
"keep eslint clean" — is fingerprinted against the configuration sources its
detector actually reads, never against the source-code sample. So removing
pytest from `pyproject.toml` invalidates `python.tests` even when no sampled
`.py` file changed, and editing sampled source never touches it. The two
identities stay separate in the manifest, in staleness and here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from comodor.learning import BrainStore, rules
from comodor.learning.memory import stale_by_fingerprint
from comodor.learning.signals import SignalDetector

SCOPE = "project:p"
PYTEST = "[tool.pytest.ini_options]\naddopts = '-q'\n"
RUFF = "[tool.ruff]\nline-length = 100\n"


@pytest.fixture
def brain(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


@pytest.fixture
def root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(PYTEST + RUFF, encoding="utf-8")
    for index in range(3):
        (project / f"m{index}.py").write_text(
            "\n".join(f"v = 'text{n}'" for n in range(10)), encoding="utf-8")
    return project


def _scan(brain, root):
    detector = SignalDetector(store=brain, checkpoints=None, scope=SCOPE)
    detector.scan_project(root)
    return detector


def _rule(brain, key):
    for rule in brain.all_rules([SCOPE]):
        if rule.key == key:
            return rule
    return None


def _active(brain):
    return {rule.key for rule in brain.all_rules([SCOPE], active_only=True)}


# --------------------------------------------------------------------------- #
# the identity a configuration rule carries
# --------------------------------------------------------------------------- #


def test_pyproject_establishes_pytest_as_an_active_configuration_rule(brain, root):
    _scan(brain, root)
    rule = _rule(brain, "python.tests")
    assert rule is not None and rule.lifecycle == "active"
    assert rule.provenance == "counted_convention"
    assert rules.evidence_kind(rule.source_ref) == rules.EVIDENCE_CONFIGURATION
    assert rule.source_ref == "configuration:python:1:pyproject.toml"
    assert rule.fingerprint == rules.configuration_manifest(root, "python").fingerprint


def test_a_configuration_rule_never_carries_the_source_sample_manifest(brain, root):
    _scan(brain, root)
    sample = _rule(brain, "quotes.style")
    config = _rule(brain, "python.tests")
    assert rules.evidence_kind(sample.source_ref) == rules.EVIDENCE_SAMPLE
    assert "m0.py" in sample.source_ref and "pyproject.toml" not in sample.source_ref
    assert "m0.py" not in config.source_ref
    assert config.fingerprint != sample.fingerprint


def test_the_manifest_names_paths_relatively_and_holds_no_values(root):
    manifest = rules.configuration_manifest(root, "python")
    assert manifest.sources == [("pyproject.toml", rules.file_fingerprint(root / "pyproject.toml"))]
    assert str(root) not in manifest.ref and "pytest" not in manifest.ref
    assert manifest.ref.startswith("configuration:python:1:")


def test_the_manifest_is_independent_of_enumeration_order(root, monkeypatch):
    forward = rules.configuration_manifest(root, "python").fingerprint
    monkeypatch.setitem(rules.CONFIGURATION_SOURCES, "twin", ("pyproject.toml", "Makefile"))
    (root / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    one = rules.configuration_manifest(root, "twin")
    monkeypatch.setitem(rules.CONFIGURATION_SOURCES, "twin", ("Makefile", "pyproject.toml"))
    other = rules.configuration_manifest(root, "twin")
    assert one.fingerprint == other.fingerprint and one.ref == other.ref
    assert forward == rules.configuration_manifest(root, "python").fingerprint


def test_each_detector_has_a_bounded_domain_of_its_own(root):
    assert rules.configuration_domain(root, "python") == [root / "pyproject.toml"]
    assert rules.configuration_domain(root, "js") == [root / "package.json"]
    assert rules.configuration_domain(root, "make") == [root / "Makefile"]
    assert rules.configuration_domain(root, "nothing") == []
    assert rules.configuration_detector("python.tests") == "python"
    assert rules.configuration_detector("js.jest") == "js"
    assert rules.configuration_detector("quotes.style") == ""


# --------------------------------------------------------------------------- #
# add / remove / change
# --------------------------------------------------------------------------- #


def test_removing_pytest_from_pyproject_stales_the_rule_without_a_source_change(brain, root):
    _scan(brain, root)
    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")   # pytest gone, ruff stays

    marked = stale_by_fingerprint(brain, root, [SCOPE])
    assert [item["id"] for item in marked] == [_rule(brain, "python.tests").id]
    assert _rule(brain, "python.tests").lifecycle == "stale"
    assert "python.tests" not in _active(brain)
    assert _rule(brain, "python.lint").lifecycle == "active", "ruff is still configured"
    assert _rule(brain, "quotes.style").lifecycle == "active", "the sample did not move"


def test_changing_the_configured_runner_invalidates_the_old_rule_and_the_new_one_wins(
        brain, root):
    (root / "package.json").write_text('{"devDependencies": {"jest": "29"}}', encoding="utf-8")
    _scan(brain, root)
    assert "js.jest" in _active(brain)

    (root / "package.json").write_text('{"devDependencies": {"vitest": "1"}}', encoding="utf-8")
    stale_by_fingerprint(brain, root, [SCOPE])
    _scan(brain, root)

    assert _rule(brain, "js.jest").lifecycle == "stale"
    assert "js.jest" not in _active(brain)
    assert "js.vitest" in _active(brain)


def test_deleting_the_establishing_file_re_evaluates_the_rule(brain, root):
    _scan(brain, root)
    (root / "pyproject.toml").unlink()

    marked = stale_by_fingerprint(brain, root, [SCOPE])
    assert {item["id"] for item in marked} == {_rule(brain, "python.tests").id,
                                                _rule(brain, "python.lint").id}
    assert _rule(brain, "python.tests").lifecycle == "stale"


def test_an_unrelated_edit_to_the_config_refreshes_the_manifest_and_keeps_the_rule(
        brain, root):
    _scan(brain, root)
    before = _rule(brain, "python.tests").fingerprint
    (root / "pyproject.toml").write_text(PYTEST + RUFF + "[tool.other]\nx = 1\n",
                                         encoding="utf-8")

    assert stale_by_fingerprint(brain, root, [SCOPE]) == []
    after = _rule(brain, "python.tests")
    assert after.lifecycle == "active" and after.fingerprint != before
    assert after.fingerprint == rules.configuration_manifest(root, "python").fingerprint


def test_changing_only_sampled_source_leaves_the_configuration_rule_alone(brain, root):
    _scan(brain, root)
    before = _rule(brain, "python.tests")
    for index in range(4):
        (root / f"n{index}.py").write_text(
            "\n".join(f'v = "t{n}"' for n in range(10)), encoding="utf-8")

    marked = stale_by_fingerprint(brain, root, [SCOPE])
    assert any(item["id"] == _rule(brain, "quotes.style").id for item in marked), \
        "the source sample flipped to double quotes"
    after = _rule(brain, "python.tests")
    assert after.lifecycle == "active"
    assert after.fingerprint == before.fingerprint and after.source_ref == before.source_ref


def test_configuration_invalidates_while_the_source_sample_is_unchanged(brain, root):
    _scan(brain, root)
    sample_before = rules.manifest_fingerprint(rules.sampled_files(root), root)
    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")
    assert rules.manifest_fingerprint(rules.sampled_files(root), root) == sample_before

    stale_by_fingerprint(brain, root, [SCOPE])
    assert _rule(brain, "python.tests").lifecycle == "stale"


def test_a_relevant_source_appearing_changes_the_manifest_and_is_re_evaluated(
        brain, root, monkeypatch):
    """A detector with a bounded candidate set: a candidate that was absent
    and now exists is a membership change, so the recorded manifest cannot
    stay current merely because the previously present file is unchanged."""
    monkeypatch.setitem(rules.CONFIGURATION_SOURCES, "python", ("pyproject.toml", "pytest.ini"))
    _scan(brain, root)
    before = _rule(brain, "python.tests")
    assert before.source_ref == "configuration:python:1:pyproject.toml"

    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    assert stale_by_fingerprint(brain, root, [SCOPE]) == []       # pytest still configured
    after = _rule(brain, "python.tests")
    assert after.fingerprint != before.fingerprint
    assert after.source_ref == "configuration:python:1:pyproject.toml,pytest.ini"


def test_an_unrelated_config_file_appearing_does_not_invalidate(brain, root):
    _scan(brain, root)
    before = _rule(brain, "python.tests")
    (root / "tox.ini").write_text("[tox]\n", encoding="utf-8")       # not a python source
    (root / "package.json").write_text('{"devDependencies": {"jest": "29"}}', encoding="utf-8")

    assert stale_by_fingerprint(brain, root, [SCOPE]) == []
    after = _rule(brain, "python.tests")
    assert after.fingerprint == before.fingerprint and after.source_ref == before.source_ref


# --------------------------------------------------------------------------- #
# path-narrowed checks
# --------------------------------------------------------------------------- #


def test_a_path_narrowed_check_on_the_config_file_re_evaluates_the_rule(brain, root):
    _scan(brain, root)
    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")

    marked = stale_by_fingerprint(brain, root, [SCOPE], paths=["pyproject.toml"])
    assert [item["id"] for item in marked] == [_rule(brain, "python.tests").id]


def test_a_path_narrowed_check_on_a_source_file_skips_configuration_rules(brain, root):
    _scan(brain, root)
    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")

    assert stale_by_fingerprint(brain, root, [SCOPE], paths=["m0.py"]) == []
    assert _rule(brain, "python.tests").lifecycle == "active", \
        "narrowed to a source path, the configuration domain was not touched"


def test_a_path_narrowed_check_on_an_absent_candidate_counts(brain, root, monkeypatch):
    monkeypatch.setitem(rules.CONFIGURATION_SOURCES, "python", ("pyproject.toml", "pytest.ini"))
    _scan(brain, root)
    before = _rule(brain, "python.tests").fingerprint
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    assert stale_by_fingerprint(brain, root, [SCOPE], paths=["pytest.ini"]) == []
    assert _rule(brain, "python.tests").fingerprint != before


# --------------------------------------------------------------------------- #
# persisted data from before the identity existed
# --------------------------------------------------------------------------- #


def test_a_rule_recorded_against_the_source_sample_is_migrated_or_staled(brain, root):
    """Before this identity, `python.tests` carried the source sample's
    manifest. Such a rule is routed to its detector: re-evaluated, and either
    moved onto the configuration manifest or marked stale."""
    sample = rules.sampled_files(root)
    legacy_ref = rules.manifest_ref(root, sample)
    legacy_fp = rules.manifest_fingerprint(sample, root)
    brain.observe_rule(key="python.tests", scope=SCOPE, category="workflow",
                       statement="Write tests with pytest and run them with `pytest -q`.",
                       source="observation", weight=3, provenance="counted_convention",
                       source_ref=legacy_ref, fingerprint=legacy_fp)

    assert stale_by_fingerprint(brain, root, [SCOPE]) == []
    migrated = _rule(brain, "python.tests")
    assert migrated.lifecycle == "active"
    assert migrated.source_ref == "configuration:python:1:pyproject.toml"
    assert migrated.fingerprint == rules.configuration_manifest(root, "python").fingerprint

    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")
    stale_by_fingerprint(brain, root, [SCOPE])
    assert _rule(brain, "python.tests").lifecycle == "stale"


def test_a_legacy_rule_whose_configuration_is_already_gone_is_staled(brain, root):
    sample = rules.sampled_files(root)
    brain.observe_rule(key="python.tests", scope=SCOPE, category="workflow",
                       statement="Write tests with pytest and run them with `pytest -q`.",
                       source="observation", weight=3, provenance="counted_convention",
                       source_ref=rules.manifest_ref(root, sample),
                       fingerprint=rules.manifest_fingerprint(sample, root))
    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")
    assert rules.manifest_fingerprint(rules.sampled_files(root), root) == \
        _rule(brain, "python.tests").fingerprint, "the sample did not move"

    stale_by_fingerprint(brain, root, [SCOPE])
    assert _rule(brain, "python.tests").lifecycle == "stale"


def test_the_identity_round_trips_through_the_store(brain, root):
    _scan(brain, root)
    stored = _rule(brain, "python.tests")
    reopened = BrainStore(brain.path, async_writes=False)
    try:
        again = next(rule for rule in reopened.all_rules([SCOPE]) if rule.key == "python.tests")
    finally:
        reopened.close()
    assert (again.source_ref, again.fingerprint) == (stored.source_ref, stored.fingerprint)


# --------------------------------------------------------------------------- #
# the sample re-count no longer speaks for configuration
# --------------------------------------------------------------------------- #


def test_the_source_recount_does_not_include_configuration_observations(root):
    files = rules.sampled_files(root)
    assert not rules.recount(files, "python.tests", root), \
        "a configuration key is not a convention the sample can vouch for"
    assert rules.recount(files, "quotes.style", root, "Use single quotes for string literals.")


def test_configuration_holds_compares_the_statement_too(root):
    assert rules.configuration_holds(root, "python", "python.tests")
    assert rules.configuration_holds(
        root, "python", "python.tests", "Write tests with pytest and run them with `pytest -q`.")
    assert not rules.configuration_holds(root, "python", "python.tests", "Write tests with nose.")
    assert not rules.configuration_holds(root, "js", "js.jest")


# --------------------------------------------------------------------------- #
# mutation checks: each protection is load-bearing
# --------------------------------------------------------------------------- #


def test_mutation_folding_configuration_into_the_sample_hides_the_change(
        brain, root, monkeypatch):
    """The finding, reproduced: with the configuration rule carrying the
    source sample's identity and no detector routing, removing pytest is
    invisible while the sampled source is unchanged."""
    _scan(brain, root)
    rule = _rule(brain, "python.tests")
    sample = rules.sampled_files(root)
    brain.refresh_fingerprint("rules", rule.id, rules.manifest_fingerprint(sample, root),
                              source_ref=rules.manifest_ref(root, sample))
    monkeypatch.setattr(rules, "configuration_detector", lambda key: "")
    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")

    assert stale_by_fingerprint(brain, root, [SCOPE]) == []
    assert _rule(brain, "python.tests").lifecycle == "active", "the mutation: still current"

    monkeypatch.undo()
    stale_by_fingerprint(brain, root, [SCOPE])
    assert _rule(brain, "python.tests").lifecycle == "stale", "the protection restored"


def test_mutation_ignoring_membership_misses_an_appearing_source(
        brain, root, monkeypatch):
    """The mutation: the check rebuilds the manifest over the members the
    rule recorded instead of the detector's candidate domain. A candidate
    appearing is then invisible, and the recorded evidence stays "current"
    over a configuration the detector would now read differently."""
    monkeypatch.setitem(rules.CONFIGURATION_SOURCES, "python", ("pyproject.toml", "pytest.ini"))
    real = rules.configuration_manifest
    recorded = set(real(root, "python").present)          # what exists when it is learned

    def recorded_members_only(root, detector):
        manifest = real(root, detector)
        manifest.sources = [(name, fp) for name, fp in manifest.sources if name in recorded]
        return manifest

    monkeypatch.setattr(rules, "configuration_manifest", recorded_members_only)
    _scan(brain, root)
    before = _rule(brain, "python.tests").fingerprint
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    stale_by_fingerprint(brain, root, [SCOPE])
    assert _rule(brain, "python.tests").fingerprint == before, "the mutation: unnoticed"

    monkeypatch.setattr(rules, "configuration_manifest", real)
    stale_by_fingerprint(brain, root, [SCOPE])
    assert _rule(brain, "python.tests").fingerprint != before, "the protection restored"


def test_mutation_without_the_domain_the_narrowed_check_skips_the_config(
        brain, root, monkeypatch):
    _scan(brain, root)
    (root / "pyproject.toml").write_text(RUFF, encoding="utf-8")
    monkeypatch.setattr(rules, "configuration_domain", lambda root, detector: [])

    assert stale_by_fingerprint(brain, root, [SCOPE], paths=["pyproject.toml"]) == []
    monkeypatch.undo()
    assert stale_by_fingerprint(brain, root, [SCOPE], paths=["pyproject.toml"])


def test_existing_counted_convention_behaviour_is_unchanged(brain, root):
    _scan(brain, root)
    before = _rule(brain, "quotes.style")
    for index in range(4):
        (root / f"n{index}.py").write_text(
            "\n".join(f'v = "t{n}"' for n in range(10)), encoding="utf-8")
    marked = stale_by_fingerprint(brain, root, [SCOPE])
    assert [item["id"] for item in marked] == [before.id]
    assert _rule(brain, "quotes.style").lifecycle == "stale"
    assert Path(root / "pyproject.toml").exists()
