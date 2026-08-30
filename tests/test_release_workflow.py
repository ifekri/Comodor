"""The release workflow, checked from the repository it releases.

`v0.20.2` reached PyPI and the workflow went red anyway. The package was
published, the wheel was installed and verified, and then the last job tried to
attach the files to the GitHub release and was refused:

    Cannot upload asset comodor-0.20.2.tar.gz to an immutable release.
    GitHub only allows asset uploads before a release is published.

This repository has immutable releases turned on, which is a good thing and
changes the order of operations: assets go on while the release is a draft, and
publishing freezes them. Creating the release by hand in the web interface
publishes it at once, so the tag push then starts a workflow that arrives to
find a release it cannot add anything to.

The damage was not the missing files — they are on PyPI, which is where
`pip install` looks. The damage was a red cross on a job called "Release" for a
release that entirely succeeded, which says the wrong thing about the part that
mattered.

Nothing here runs the workflow; these are checks on its shape, which is what
can be checked without cutting a release.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def job(name: str) -> dict:
    return workflow()["jobs"][name]


def steps_of(name: str) -> list[dict]:
    return job(name)["steps"]


def body_of(name: str, step_name: str) -> str:
    for step in steps_of(name):
        if step.get("name") == step_name:
            return step.get("run", "")
    raise AssertionError(f"{name} has no step called {step_name!r}")


# --------------------------------------------------------------------------- #
# the order immutable releases require
# --------------------------------------------------------------------------- #


def test_a_release_it_creates_is_drafted_before_its_files_go_on():
    """Assets first, published second. The only order that works."""
    run = body_of("github-release", "Create the release with its files")

    assert "--draft" in run
    assert "--draft=false" in run
    assert run.index("--draft") < run.index("--draft=false"), \
        "it publishes before attaching, which an immutable release refuses"


def test_it_looks_before_it_writes():
    """The three cases are different work: no release, a draft, or one already
    published and frozen."""
    run = body_of("github-release", "What state is the release in")

    for state in ("absent", "draft", "published"):
        assert f"state={state}" in run, f"it does not detect {state!r}"


def test_an_already_published_release_is_not_a_failure():
    """The package is on PyPI. Losing the convenience of files on the release
    page must not report as a broken release."""
    names = [step.get("name", "") for step in steps_of("github-release")]
    assert "Say why the files are not attached" in names

    for step in steps_of("github-release"):
        if step.get("name") == "Say why the files are not attached":
            assert step["if"] == "steps.state.outputs.state == 'published'"
            assert "exit 1" not in step.get("run", ""), \
                "it fails on a release that succeeded"


def test_nothing_uploads_unconditionally():
    """The step that failed did exactly this: attach, always, whatever state
    the release was in."""
    for step in steps_of("github-release"):
        run = step.get("run", "")
        if "gh release upload" in run or "gh release create" in run:
            assert step.get("if"), f"{step.get('name')!r} runs unconditionally"


def test_the_summary_says_what_reached_pypi():
    """A person reading a red or amber run needs the answer to one question
    first: did the package ship?"""
    run = body_of("github-release", "Record what shipped")

    assert "PyPI" in run
    assert "always()" in steps_of("github-release")[-1]["if"]


# --------------------------------------------------------------------------- #
# the parts that were already right, kept that way
# --------------------------------------------------------------------------- #


def test_the_tag_and_the_built_version_must_agree():
    """A version number PyPI will never let us use again is the one mistake
    here that cannot be undone."""
    run = "\n".join(step.get("run", "") for step in steps_of("build"))

    assert "GITHUB_REF_NAME#v" in run
    assert "::error::" in run


def test_the_checkout_is_deep_enough_to_carry_the_tag():
    """hatch-vcs reads the version from the tag. A shallow checkout builds
    everything as 0.1.dev1."""
    for name in ("gate", "build"):
        checkout = [step for step in steps_of(name)
                    if "actions/checkout" in str(step.get("uses", ""))]
        assert checkout, f"{name} does not check anything out"
        assert checkout[0]["with"]["fetch-depth"] == 0, \
            f"{name} uses a shallow checkout"


def test_publishing_needs_the_gate_to_have_passed():
    assert job("build")["needs"] == "gate"
    assert job("publish")["needs"] == "build"
    assert "publish" in job("github-release")["needs"]


def test_the_gate_runs_the_whole_suite():
    """A gate that runs something other than what the developer runs is a gate
    nobody trusts."""
    run = "\n".join(step.get("run", "") for step in steps_of("gate"))

    assert "pytest -q" in run
    assert "ruff check" in run


@pytest.mark.parametrize("name", ["gate", "build", "publish", "github-release"])
def test_every_job_has_a_ceiling_or_is_bounded_by_what_it_runs(name):
    """The image workflow hung for three hours because one step could wait
    forever. The jobs here are bounded by the tools they call, except the one
    that talks to the GitHub API, which says how long it may take."""
    entry = job(name)
    if name == "github-release":
        assert entry.get("timeout-minutes"), "no ceiling on the API calls"
    else:
        assert entry["runs-on"], f"{name} does not say where it runs"
