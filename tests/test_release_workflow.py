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

import re
from pathlib import Path

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




# --------------------------------------------------------------------------- #
# the image, which never got built
# --------------------------------------------------------------------------- #


def test_the_release_builds_the_container_image():
    """`release: [published]` looks right and does not work: GitHub raises no
    workflow events for anything done with GITHUB_TOKEN, so a release created
    by this workflow fires nothing. v0.20.3 shipped and no image was built."""
    entry = job("image")

    assert entry["uses"].endswith("image.yml")
    assert "publish" in entry["needs"], \
        "it would build before PyPI has the version it installs"


def test_the_image_job_is_given_the_secrets_it_needs():
    """A called workflow gets none unless they are passed, and the push would
    fall back to GHCR without saying why."""
    assert job("image")["secrets"] == "inherit"


def test_the_image_is_told_which_version_to_install():
    assert "needs.build.outputs.version" in str(job("image")["with"]["version"])


def test_the_image_workflow_no_longer_listens_for_a_release():
    image = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "image.yml").read_text(encoding="utf-8"))
    triggers = image[True] if True in image else image["on"]

    assert "release" not in triggers, \
        "an event that cannot fire for our own releases"
    assert "workflow_call" in triggers, "the release workflow cannot call it"


def test_the_image_waits_for_pypi():
    """PyPI is a CDN. A version uploaded a second ago is not installable
    everywhere, and the failure reads as a broken Dockerfile."""
    image = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "image.yml").read_text(encoding="utf-8"))
    names = [step.get("name", "") for step in image["jobs"]["build"]["steps"]]

    assert "Wait for PyPI to have it" in names


# --------------------------------------------------------------------------- #
# the command a person types
# --------------------------------------------------------------------------- #


def test_the_guide_pushes_the_tag_on_its_own():
    """`git push origin main --tags` does two things, and if either is refused
    neither happens - so a local main that is behind, which is the normal state
    after merging a pull request on the web, stops the tag from ever leaving.

    Checked inside the fenced commands only. The prose above them explains what
    not to do and has to be allowed to quote it, which the first version of
    this test forbade.
    """
    guide = (ROOT / "RELEASING.md").read_text(encoding="utf-8")
    commands = "\n".join(re.findall(r"```bash\n(.*?)```", guide, re.DOTALL))

    assert commands, "the guide has no commands in it"
    assert "--tags" not in commands, (
        "a command in the guide still pushes a branch and every tag at once")
    assert re.search(r"git push origin v\d", commands), (
        "the guide never shows pushing the tag by name")


# --------------------------------------------------------------------------- #
# the artifact rebuild and the version
# --------------------------------------------------------------------------- #


def test_the_artifact_rebuild_does_not_change_the_version_a_tag_publishes():
    """The build job rebuilds `src/comodor/tui/dist` for every platform before
    packaging, which rewrites the committed manifest; a dirty tree makes
    hatch-vcs append `+dYYYYMMDD`, and the tag check then refuses the wheel.
    Never exercised before S1 — no tag was cut after the artifact entered the
    workflow — and it would have failed the first one.

    A tag build names its own version, and only after proving the rebuild is
    the only change: the guard step must come first, and must fail on
    anything dirty outside the artifact.
    """
    names = [step.get("name", "") for step in steps_of("build")]
    guard = names.index("The only change since the tag is the rebuilt artifact")
    rebuild = names.index("Build the production TUI artifact for every platform")
    build = names.index("Build sdist and wheel")
    assert rebuild < guard < build, names

    guard_body = body_of("build", "The only change since the tag is the rebuilt artifact")
    assert "git status --porcelain" in guard_body
    assert "src/comodor/tui/dist/" in guard_body
    assert "exit 1" in guard_body

    build_body = body_of("build", "Build sdist and wheel")
    assert "SETUPTOOLS_SCM_PRETEND_VERSION" in build_body
    assert 'GITHUB_REF_TYPE:-}" = "tag"' in build_body, (
        "only a tag names its version; a dry run keeps the honest dev one")
    assert "GITHUB_REF_NAME#v" in build_body


def test_the_release_wheel_is_checked_for_the_retired_interface():
    """The same guard CI runs on every wheel, on the one that ships."""
    names = [step.get("name", "") for step in steps_of("build")]
    assert "The retired interface is not in the wheel" in names
    assert "check-wheel-contents.py" in body_of(
        "build", "The retired interface is not in the wheel")


def test_every_release_page_states_the_requirements():
    """Python 3.11 and Bun for the interface, on the page a person reads
    before installing — whether the workflow wrote the draft or found one
    somebody wrote by hand. The hand-written path used to publish the draft
    untouched, so a release could omit the one prerequisite the installer
    does not mention."""
    for step in steps_of("github-release"):
        if step.get("name") == "Create draft release and attach distributions":
            body = step["with"]["body"]
            assert body.lstrip().startswith("## Requirements"), body[:60]
            assert "Python 3.11" in body and "bun.sh" in body
            break
    else:
        raise AssertionError("no fresh-draft step")

    draft = body_of("github-release", "Attach distributions to existing draft")
    assert "## Requirements" in draft and "bun.sh" in draft
    assert "gh release edit" in draft and "--notes-file" in draft
    assert "grep -q '^## Requirements'" in draft, (
        "a draft that already states them must be left alone")
