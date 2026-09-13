"""`tools/release-reconcile.py` — a release that can be run again.

`v2.0.0` failed in the build job and published nothing, which was the easy
case: rerun from nothing. The hard case is the one the old workflow could not
survive: a run that put the package on PyPI and then died. PyPI never takes a
filename twice, so the second run's upload would have been refused, and the
GitHub Release stage counted a published release as done even with no files on
it. Every one of `v1.1.0` … `v2.0.0` is an immutable published release, and
two of them carry no assets.

So each destination is classified against the files this build produced —
ABSENT, PARTIAL, COMPLETE, CONFLICT — and only what is missing is published.
The decisions are pure functions over observed state; these tests drive them
with every state the mission names, with a fake GitHub and a fake registry
underneath the executors, and never touch a live service.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release-reconcile.py"
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"
IMAGE_YML = ROOT / ".github" / "workflows" / "image.yml"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("release_reconcile", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


VERSION = "2.0.1"
WHEEL = f"comodor-{VERSION}-py3-none-any.whl"
SDIST = f"comodor-{VERSION}.tar.gz"
WHEEL_SHA = "a" * 64
SDIST_SHA = "b" * 64
OTHER_SHA = "f" * 64


def expected(tool):
    return [tool.Dist(WHEEL, WHEEL_SHA, 10), tool.Dist(SDIST, SDIST_SHA, 20)]


def kinds(plan) -> list[tuple[str, str]]:
    return [(action.kind, action.target) for action in plan.actions]


def mutations(plans) -> list:
    return [action for plan in plans for action in plan.actions
            if action.kind not in ("SKIP", "FAIL")]


# --------------------------------------------------------------------------- #
# PyPI
# --------------------------------------------------------------------------- #


def test_pypi_absent_uploads_everything(tool):
    plan = tool.plan_pypi(expected(tool), None)
    assert plan.state == tool.ABSENT and plan.ok
    assert plan.uploads() == [WHEEL, SDIST]


def test_pypi_complete_is_verified_and_skipped(tool):
    plan = tool.plan_pypi(expected(tool), expected(tool))
    assert plan.state == tool.COMPLETE and plan.ok
    assert plan.uploads() == []
    assert kinds(plan) == [("SKIP", WHEEL), ("SKIP", SDIST)]


def test_pypi_partial_uploads_only_the_missing_file(tool):
    """The wheel went up and the run died before the sdist. PyPI refuses a
    second copy of the wheel, so the wheel must not be in the upload set."""
    plan = tool.plan_pypi(expected(tool), [tool.Dist(WHEEL, WHEEL_SHA)])
    assert plan.state == tool.PARTIAL and plan.ok
    assert plan.uploads() == [SDIST]
    assert ("SKIP", WHEEL) in kinds(plan)


def test_pypi_same_filename_with_other_bytes_fails_closed(tool):
    plan = tool.plan_pypi(expected(tool), [tool.Dist(WHEEL, OTHER_SHA),
                                           tool.Dist(SDIST, SDIST_SHA)])
    assert plan.state == tool.CONFLICT and not plan.ok
    assert plan.uploads() == [], "nothing is uploaded next to a conflict"
    assert OTHER_SHA in plan.problems[0] and WHEEL_SHA in plan.problems[0]
    assert "cannot be replaced" in plan.problems[0]


def test_pypi_a_file_this_build_did_not_make_fails_closed(tool):
    """A platform wheel under our version number was built by somebody else."""
    stranger = tool.Dist(f"comodor-{VERSION}-cp312-cp312-linux_x86_64.whl", OTHER_SHA)
    plan = tool.plan_pypi(expected(tool), expected(tool) + [stranger])
    assert plan.state == tool.CONFLICT
    assert stranger.name in plan.problems[0]


# --------------------------------------------------------------------------- #
# GitHub Release
# --------------------------------------------------------------------------- #


def release(tool, *, draft=False, immutable=False, assets=(), id=7):
    return tool.Release(id, draft, immutable, tuple(assets), "https://x/releases/v" + VERSION)


def asset(tool, name, sha, state="uploaded", id=1):
    return tool.Asset(name, sha, id, state)


def test_github_absent_creates_a_draft_attaches_and_publishes(tool):
    plan = tool.plan_github(expected(tool), None)
    assert plan.state == tool.ABSENT and plan.ok
    assert [k for k, _ in kinds(plan)] == ["CREATE", "UPLOAD", "UPLOAD", "PUBLISH"], kinds(plan)


def test_github_draft_with_one_missing_asset_uploads_only_that_one(tool):
    plan = tool.plan_github(expected(tool), release(
        tool, draft=True, assets=[asset(tool, WHEEL, WHEEL_SHA)]))
    assert plan.ok and plan.state == tool.PARTIAL
    assert plan.uploads() == [SDIST]
    assert kinds(plan)[-1] == ("PUBLISH", "draft release")


def test_github_draft_replaces_only_an_upload_that_never_finished(tool):
    """A transfer the first run started and did not finish is not a file;
    it is deleted and uploaded again. A different file is never replaced,
    draft or not, because a different file is a different release."""
    plan = tool.plan_github(expected(tool), release(
        tool, draft=True, assets=[asset(tool, WHEEL, "", state="starting"),
                                  asset(tool, SDIST, SDIST_SHA)]))
    assert plan.ok
    assert ("REPLACE", WHEEL) in kinds(plan) and ("SKIP", SDIST) in kinds(plan)

    plan = tool.plan_github(expected(tool), release(
        tool, draft=True, assets=[asset(tool, WHEEL, OTHER_SHA)]))
    assert plan.state == tool.CONFLICT
    assert "never replaced" in plan.problems[0]


def test_github_published_mutable_with_missing_asset_adds_only_it(tool):
    plan = tool.plan_github(expected(tool), release(
        tool, assets=[asset(tool, WHEEL, WHEEL_SHA)]))
    assert plan.ok and plan.state == tool.PARTIAL
    assert plan.uploads() == [SDIST]
    assert ("SKIP", WHEEL) in kinds(plan)
    assert not any(kind == "PUBLISH" for kind, _ in kinds(plan)), "already published"


def test_github_published_immutable_with_all_assets_is_complete(tool):
    plan = tool.plan_github(expected(tool), release(
        tool, immutable=True,
        assets=[asset(tool, WHEEL, WHEEL_SHA), asset(tool, SDIST, SDIST_SHA)]))
    assert plan.state == tool.COMPLETE and plan.ok
    assert plan.uploads() == []


def test_github_published_immutable_missing_an_asset_fails_closed(tool):
    """`v2.0.0` and `v1.2.1` are exactly this: published, immutable, no
    files. The old job warned and went green; a release page with no files
    is not a release, and GitHub will not let it be finished."""
    plan = tool.plan_github(expected(tool), release(
        tool, immutable=True, assets=[asset(tool, WHEEL, WHEEL_SHA)]))
    assert plan.state == tool.CONFLICT and not plan.ok
    message = plan.problems[0]
    assert "immutable" in message and SDIST in message
    assert "cannot be completed in place" in message
    assert "next" in message and "patch" in message
    assert "do not delete" in message


def test_github_published_release_with_a_conflicting_asset_fails_closed(tool):
    plan = tool.plan_github(expected(tool), release(
        tool, assets=[asset(tool, WHEEL, OTHER_SHA), asset(tool, SDIST, SDIST_SHA)]))
    assert plan.state == tool.CONFLICT
    assert plan.uploads() == []
    assert "never replaced" in plan.problems[0]


def test_github_a_published_release_is_not_evidence_of_completeness(tool):
    """The exact regression: a release object with nothing on it."""
    plan = tool.plan_github(expected(tool), release(tool))
    assert plan.state == tool.PARTIAL
    assert plan.uploads() == [WHEEL, SDIST]


# --------------------------------------------------------------------------- #
# the GitHub executor, over a fake API
# --------------------------------------------------------------------------- #


class FakeGitHub:
    """The subset of the release API the executor uses, kept in memory with
    a log of every mutation. Immutability is enforced the way GitHub does:
    nothing may be uploaded to, or deleted from, a published immutable
    release."""

    def __init__(self, tool, current=None, immutable_on_publish=True):
        self.tool = tool
        self.current = current
        self.immutable_on_publish = immutable_on_publish
        self.log: list[tuple] = []
        self.notes = "## What's Changed\n* things\n"
        self._next_id = 100

    def release(self, tag):
        return self.current

    def create_draft(self, tag, name, body):
        assert self.current is None
        self.log.append(("create_draft", tag))
        self.notes = body + "\n\n## What's Changed\n* generated\n"
        self.current = self.tool.Release(42, True, False, (), "https://x/" + tag)
        return self.current

    def _guard(self):
        assert self.current is not None
        if not self.current.draft and self.current.immutable:
            raise AssertionError("mutated an immutable published release")

    def upload(self, tag, path):
        self._guard()
        self.log.append(("upload", path.name))
        sha = {WHEEL: WHEEL_SHA, SDIST: SDIST_SHA}[path.name]
        assert path.name not in [a.name for a in self.current.assets], "clobbered"
        assets = self.current.assets + (self.tool.Asset(path.name, sha, self._next_id),)
        self._next_id += 1
        self.current = self.tool.Release(self.current.id, self.current.draft,
                                         self.current.immutable, assets,
                                         self.current.html_url)

    def delete_asset(self, asset):
        self._guard()
        self.log.append(("delete", asset.name))
        assets = tuple(a for a in self.current.assets if a.id != asset.id)
        self.current = self.tool.Release(self.current.id, self.current.draft,
                                         self.current.immutable, assets,
                                         self.current.html_url)

    def publish(self, rel):
        self.log.append(("publish", rel.id))
        self.current = self.tool.Release(rel.id, False, self.immutable_on_publish,
                                         self.current.assets, self.current.html_url)

    def body(self, rel):
        return self.notes

    def set_body(self, rel, body):
        self.log.append(("set_body",))
        self.notes = body


@pytest.fixture
def dist_dir(tmp_path):
    folder = tmp_path / "dist"
    folder.mkdir()
    (folder / WHEEL).write_bytes(b"wheel")
    (folder / SDIST).write_bytes(b"sdist")
    return folder


def run_github(tool, github, dist_dir):
    plan = tool.plan_github(expected(tool), github.current)
    assert plan.ok, plan.problems
    after = tool.apply_github(plan, github, "v" + VERSION, VERSION, dist_dir, github.current)
    return tool.plan_github(expected(tool), after)


def test_from_nothing_the_release_is_drafted_filled_then_published(tool, dist_dir):
    github = FakeGitHub(tool)
    verified = run_github(tool, github, dist_dir)
    assert verified.state == tool.COMPLETE
    assert [entry[0] for entry in github.log] == ["create_draft", "upload", "upload", "publish"]
    assert not github.current.draft and github.current.immutable
    assert github.notes.startswith("## Requirements"), "the page states what it needs"
    assert "## Install" in github.notes and VERSION in github.notes


def test_a_draft_somebody_wrote_keeps_its_words_under_the_requirements(tool, dist_dir):
    github = FakeGitHub(tool, release(tool, draft=True))
    github.notes = "Hand-written notes about this release.\n"
    verified = run_github(tool, github, dist_dir)
    assert verified.state == tool.COMPLETE
    assert github.notes.startswith("## Requirements")
    assert "Hand-written notes" in github.notes
    assert ("set_body",) in github.log


def test_a_published_mutable_release_gains_only_the_missing_file(tool, dist_dir):
    github = FakeGitHub(tool, release(tool, assets=[asset(tool, WHEEL, WHEEL_SHA)]))
    verified = run_github(tool, github, dist_dir)
    assert verified.state == tool.COMPLETE
    assert github.log == [("upload", SDIST)], "no publish, no body edit, no re-upload"


def test_a_complete_release_is_not_touched_at_all(tool, dist_dir):
    github = FakeGitHub(tool, release(
        tool, immutable=True,
        assets=[asset(tool, WHEEL, WHEEL_SHA), asset(tool, SDIST, SDIST_SHA)]))
    plan = tool.plan_github(expected(tool), github.current)
    assert plan.state == tool.COMPLETE
    # The executor is only called for a plan with work; the command skips it.
    assert github.log == []


def test_an_interrupted_draft_upload_is_replaced_not_clobbered(tool, dist_dir):
    github = FakeGitHub(tool, release(
        tool, draft=True, assets=[asset(tool, WHEEL, "", state="starting", id=5)]))
    verified = run_github(tool, github, dist_dir)
    assert verified.state == tool.COMPLETE
    assert github.log[:2] == [("delete", WHEEL), ("upload", WHEEL)]


# --------------------------------------------------------------------------- #
# container images
# --------------------------------------------------------------------------- #

GHCR = "ghcr.io/ifekri/comodor"
PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})


def image(tool, digest="sha256:" + "1" * 64, version=VERSION, platforms=PLATFORMS):
    return tool.Image(digest, frozenset(platforms), version, "abc123")


def test_ghcr_version_missing_is_built_then_latest_moved(tool):
    plan = tool.plan_image("GHCR", GHCR, VERSION, None, image(tool, version="1.2.1"))
    assert plan.state == tool.ABSENT and plan.ok
    assert kinds(plan) == [("BUILD", f"{GHCR}:{VERSION}"), ("UPDATE_LATEST", f"{GHCR}:latest")]


def test_ghcr_version_valid_is_skipped(tool):
    current = image(tool)
    plan = tool.plan_image("GHCR", GHCR, VERSION, current, current)
    assert plan.state == tool.COMPLETE and plan.ok
    assert kinds(plan) == [("SKIP", f"{GHCR}:{VERSION}"), ("SKIP", f"{GHCR}:latest")]
    assert tool.latest_state(plan) == tool.CURRENT


def test_ghcr_version_correct_but_latest_stale_updates_only_latest(tool):
    current = image(tool)
    older = image(tool, digest="sha256:" + "9" * 64, version="1.2.1")
    plan = tool.plan_image("GHCR", GHCR, VERSION, current, older)
    assert plan.state == tool.COMPLETE and plan.ok
    assert kinds(plan) == [("SKIP", f"{GHCR}:{VERSION}"), ("UPDATE_LATEST", f"{GHCR}:latest")]
    assert "no rebuild" in plan.actions[1].why
    assert tool.latest_state(plan) == tool.STALE


def test_ghcr_version_tag_that_is_another_version_fails_closed(tool):
    plan = tool.plan_image("GHCR", GHCR, VERSION, image(tool, version="1.2.1"), None)
    assert plan.state == tool.CONFLICT and not plan.ok
    assert "never overwritten" in plan.problems[0]
    assert not any(kind == "UPDATE_LATEST" for kind, _ in kinds(plan)), (
        "latest must not be moved to an image that failed verification")


def test_ghcr_version_tag_missing_a_platform_fails_closed(tool):
    plan = tool.plan_image("GHCR", GHCR, VERSION,
                           image(tool, platforms={"linux/amd64"}), None)
    assert plan.state == tool.CONFLICT
    assert "linux/arm64" in plan.problems[0]


def test_docker_hub_without_credentials_is_skipped_not_failed(tool):
    plan = tool.plan_image("Docker Hub", "docker.io/comodor", VERSION, None, None,
                           configured=False)
    assert plan.state == tool.NOT_CONFIGURED and plan.ok
    assert kinds(plan) == [("SKIP", "docker.io/comodor")]


def test_docker_hub_version_missing_is_copied_from_a_verified_ghcr_image(tool):
    """One build, two registries: when GHCR already has the verified image,
    Docker Hub gets a registry-side copy of it, not a second build."""
    plan = tool.plan_image("Docker Hub", "ifekri/comodor", VERSION, None, None,
                           source=f"{GHCR}:{VERSION}")
    assert plan.state == tool.ABSENT and plan.ok
    assert kinds(plan)[0] == ("COPY", f"ifekri/comodor:{VERSION}")
    assert kinds(plan)[1][0] == "UPDATE_LATEST"


def test_docker_hub_version_missing_is_built_when_ghcr_is_missing_too(tool):
    plan = tool.plan_image("Docker Hub", "ifekri/comodor", VERSION, None, None)
    assert kinds(plan)[0] == ("BUILD", f"ifekri/comodor:{VERSION}")


def test_docker_hub_version_already_valid_is_skipped(tool):
    current = image(tool)
    plan = tool.plan_image("Docker Hub", "ifekri/comodor", VERSION, current, current,
                           source=f"{GHCR}:{VERSION}")
    assert plan.state == tool.COMPLETE
    assert all(kind == "SKIP" for kind, _ in kinds(plan))


def test_the_registry_answer_is_read_for_platforms_and_labels(tool):
    """`docker buildx imagetools inspect --format '{{json .}}'`: a manifest
    list with an attestation entry (os "unknown", which is not a platform)
    and one image config per platform, carrying the labels."""
    raw = json.dumps({
        "manifest": {"digest": "sha256:" + "c" * 64, "manifests": [
            {"platform": {"os": "linux", "architecture": "amd64"}},
            {"platform": {"os": "linux", "architecture": "arm64"}},
            {"platform": {"os": "unknown", "architecture": "unknown"}},
        ]},
        "image": {
            "linux/amd64": {"os": "linux", "architecture": "amd64",
                            "config": {"Labels": {
                                "org.opencontainers.image.version": VERSION,
                                "org.opencontainers.image.revision": "deadbeef"}}},
            "linux/arm64": {"os": "linux", "architecture": "arm64",
                            "config": {"Labels": {
                                "org.opencontainers.image.version": VERSION}}},
        },
    })
    parsed = tool.parse_imagetools(raw)
    assert parsed.digest == "sha256:" + "c" * 64
    assert parsed.platforms == PLATFORMS
    assert parsed.version == VERSION and parsed.revision == "deadbeef"


def test_an_image_without_the_version_label_is_not_this_release(tool):
    """The images published before the label existed classify as conflicts
    under their own version numbers — none of which is ever run again — and
    a tag pushed by some other hand does too."""
    unlabeled = tool.Image("sha256:" + "d" * 64, PLATFORMS, "", "")
    plan = tool.plan_image("GHCR", GHCR, VERSION, unlabeled, None)
    assert plan.state == tool.CONFLICT


class FakeRegistry:
    """Two registries in memory, addressed by reference; `create` copies a
    manifest list from one reference to another the way `imagetools create`
    does, across repositories and registries alike."""

    def __init__(self, tool, refs: dict):
        self.tool = tool
        self.refs = dict(refs)
        self.log: list[tuple] = []

    def inspect(self, reference):
        return self.refs.get(reference)

    def retag(self, source, target):
        self.log.append(("retag", source, target))
        self.refs[target] = self.refs[source]


def run_image(tool, monkeypatch, registry, argv):
    monkeypatch.setattr(tool, "Registry", lambda: registry)
    return tool.main(["image", *argv, "--github-output", "", "--summary", ""])


def test_apply_moves_only_latest_and_verifies(tool, monkeypatch):
    current = image(tool)
    registry = FakeRegistry(tool, {f"{GHCR}:{VERSION}": current,
                                   f"{GHCR}:latest": image(tool, "sha256:" + "9" * 64, "1.2.1")})
    code = run_image(tool, monkeypatch, registry,
                     ["--repository", GHCR, "--version", VERSION, "--apply", "--verify"])
    assert code == 0
    assert registry.log == [("retag", f"{GHCR}:{VERSION}", f"{GHCR}:latest")]
    assert registry.refs[f"{GHCR}:latest"] is current


def test_apply_copies_the_version_to_docker_hub_from_ghcr(tool, monkeypatch):
    current = image(tool)
    registry = FakeRegistry(tool, {f"{GHCR}:{VERSION}": current})
    code = run_image(tool, monkeypatch, registry,
                     ["--name", "Docker Hub", "--repository", "ifekri/comodor",
                      "--version", VERSION, "--source", f"{GHCR}:{VERSION}",
                      "--apply", "--verify"])
    assert code == 0
    assert registry.log == [("retag", f"{GHCR}:{VERSION}", f"ifekri/comodor:{VERSION}"),
                            ("retag", f"ifekri/comodor:{VERSION}", "ifekri/comodor:latest")]


def test_apply_refuses_to_touch_a_conflicting_version_tag(tool, monkeypatch):
    registry = FakeRegistry(tool, {f"{GHCR}:{VERSION}": image(tool, version="1.2.1")})
    code = run_image(tool, monkeypatch, registry,
                     ["--repository", GHCR, "--version", VERSION, "--apply"])
    assert code == 1
    assert registry.log == []


def test_apply_never_builds(tool, monkeypatch):
    """A missing version image is the build step's job, decided by the plan's
    `build` output; `--apply` on an absent image does nothing and, with
    `--verify`, says the image is not there."""
    registry = FakeRegistry(tool, {})
    code = run_image(tool, monkeypatch, registry,
                     ["--repository", GHCR, "--version", VERSION, "--apply", "--verify"])
    assert code == 1
    assert registry.log == []


# --------------------------------------------------------------------------- #
# the whole release: partial failures, complete reruns, dry runs
# --------------------------------------------------------------------------- #


def state(tool, **overrides) -> dict:
    """A simulated observed state, as `simulate` reads it. Defaults to
    nothing published anywhere and Docker Hub configured but empty."""
    base = {
        "version": VERSION,
        "expected": [{"name": WHEEL, "sha256": WHEEL_SHA}, {"name": SDIST, "sha256": SDIST_SHA}],
        "pypi": None,
        "github": None,
        "ghcr": {"version": None, "latest": None},
        "dockerhub": {"version": None, "latest": None},
    }
    base.update(overrides)
    return base


PYPI_DONE = [{"name": WHEEL, "sha256": WHEEL_SHA}, {"name": SDIST, "sha256": SDIST_SHA}]
GITHUB_DONE = {"draft": False, "immutable": True, "assets": PYPI_DONE}
IMAGE_DONE = {"digest": "sha256:" + "1" * 64, "platforms": sorted(PLATFORMS), "version": VERSION}


def summary(plans) -> dict[str, list[str]]:
    return {plan.destination: [action.kind for action in plan.actions] for plan in plans}


def test_all_destinations_absent(tool):
    plans = tool.load_state(state(tool))
    assert [plan.state for plan in plans] == [tool.ABSENT] * 4
    assert summary(plans)["PyPI"] == ["UPLOAD", "UPLOAD"]
    assert summary(plans)["GitHub Release"] == ["CREATE", "UPLOAD", "UPLOAD", "PUBLISH"]
    assert summary(plans)["GHCR"] == ["BUILD", "UPDATE_LATEST"]
    assert summary(plans)["Docker Hub"] == ["BUILD", "UPDATE_LATEST"]


def test_partial_failure_after_pypi(tool):
    """Scenario 1: PyPI succeeded, the run died before the GitHub Release.
    The rerun verifies PyPI and skips it, and does everything else."""
    plans = tool.load_state(state(tool, pypi=PYPI_DONE))
    assert plans[0].state == tool.COMPLETE and summary(plans)["PyPI"] == ["SKIP", "SKIP"]
    assert plans[1].state == tool.ABSENT
    assert plans[2].state == tool.ABSENT and plans[3].state == tool.ABSENT
    assert all(plan.ok for plan in plans)


def test_partial_failure_after_github_release(tool):
    """Scenario 2: PyPI and the release page done; containers not."""
    plans = tool.load_state(state(tool, pypi=PYPI_DONE, github=GITHUB_DONE))
    assert [plan.state for plan in plans] == [tool.COMPLETE, tool.COMPLETE,
                                              tool.ABSENT, tool.ABSENT]
    assert summary(plans)["GitHub Release"] == ["SKIP", "SKIP", "SKIP"]
    assert summary(plans)["GHCR"] == ["BUILD", "UPDATE_LATEST"]


def test_partial_failure_after_ghcr(tool):
    """Scenario 3: everything but Docker Hub. The rerun copies the verified
    GHCR image across rather than building again, and moves only Hub's
    `latest`."""
    plans = tool.load_state(state(
        tool, pypi=PYPI_DONE, github=GITHUB_DONE,
        ghcr={"version": IMAGE_DONE, "latest": IMAGE_DONE}))
    assert [plan.state for plan in plans] == [tool.COMPLETE, tool.COMPLETE,
                                              tool.COMPLETE, tool.ABSENT]
    assert summary(plans)["GHCR"] == ["SKIP", "SKIP"]
    assert summary(plans)["Docker Hub"] == ["COPY", "UPDATE_LATEST"]
    assert plans[3].actions[0].why.startswith(f"from {GHCR}:{VERSION}")


def test_a_complete_release_run_again_publishes_nothing(tool):
    """Scenario 4: every destination verifies and no-ops; zero mutations."""
    plans = tool.load_state(state(
        tool, pypi=PYPI_DONE, github=GITHUB_DONE,
        ghcr={"version": IMAGE_DONE, "latest": IMAGE_DONE},
        dockerhub={"version": IMAGE_DONE, "latest": IMAGE_DONE}))
    assert [plan.state for plan in plans] == [tool.COMPLETE] * 4
    assert mutations(plans) == []
    assert all(plan.ok for plan in plans)


def test_only_latest_needs_moving(tool):
    older = {"digest": "sha256:" + "9" * 64, "platforms": sorted(PLATFORMS), "version": "1.2.1"}
    plans = tool.load_state(state(
        tool, pypi=PYPI_DONE, github=GITHUB_DONE,
        ghcr={"version": IMAGE_DONE, "latest": older},
        dockerhub={"version": IMAGE_DONE, "latest": IMAGE_DONE}))
    assert [action.kind for action in mutations(plans)] == ["UPDATE_LATEST"]
    assert mutations(plans)[0].target == f"{GHCR}:latest"


def test_docker_hub_not_configured_in_a_whole_release(tool):
    plans = tool.load_state(state(tool, pypi=PYPI_DONE, github=GITHUB_DONE,
                                  ghcr={"version": IMAGE_DONE, "latest": IMAGE_DONE},
                                  dockerhub=None))
    assert plans[3].state == tool.NOT_CONFIGURED
    assert mutations(plans) == []


def test_a_conflict_anywhere_is_reported_and_the_rest_still_planned(tool):
    """Destinations are independent: a conflicting PyPI file does not stop
    the plan from saying what the image needs. (The workflow still stops,
    because the package must be on PyPI before an image installs it.)"""
    plans = tool.load_state(state(
        tool, pypi=[{"name": WHEEL, "sha256": OTHER_SHA}, {"name": SDIST, "sha256": SDIST_SHA}]))
    assert plans[0].state == tool.CONFLICT
    assert plans[2].state == tool.ABSENT


def test_the_simulation_command_reports_and_exits_by_problems(tool, tmp_path, capsys):
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps(state(
        tool, pypi=PYPI_DONE, github=GITHUB_DONE,
        ghcr={"version": IMAGE_DONE, "latest": IMAGE_DONE}, dockerhub=None)),
        encoding="utf-8")
    assert tool.main(["simulate", str(clean)]) == 0
    out = capsys.readouterr().out
    assert "mutations: 0   problems: 0" in out
    assert "PyPI: COMPLETE" in out and "Docker Hub: NOT_CONFIGURED" in out

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(state(tool, github={
        "draft": False, "immutable": True, "assets": []})), encoding="utf-8")
    assert tool.main(["simulate", str(broken)]) == 1
    assert "problems: 1" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# the pypi command against a fake index and a real dist/ folder
# --------------------------------------------------------------------------- #


def test_the_pypi_command_stages_only_what_is_missing(tool, dist_dir, monkeypatch, tmp_path):
    real_wheel_sha = tool.sha256_of(dist_dir / WHEEL)
    monkeypatch.setattr(tool, "fetch_pypi",
                        lambda project, version, base: [tool.Dist(WHEEL, real_wheel_sha)])
    stage = tmp_path / "publish"
    output = tmp_path / "out.txt"
    code = tool.main(["pypi", "--version", VERSION, "--dist", str(dist_dir),
                      "--stage", str(stage), "--github-output", str(output), "--summary", ""])
    assert code == 0
    assert sorted(path.name for path in stage.iterdir()) == [SDIST]
    assert output.read_text(encoding="utf-8") == "state=PARTIAL\nuploads=1\n"


def test_the_pypi_command_refuses_files_of_another_version(tool, dist_dir, monkeypatch):
    monkeypatch.setattr(tool, "fetch_pypi", lambda *a: None)
    with pytest.raises(SystemExit, match="not built for version 9.9.9"):
        tool.main(["pypi", "--version", "9.9.9", "--dist", str(dist_dir), "--summary", ""])


def test_the_pypi_command_verify_fails_on_a_partial_version(tool, dist_dir, monkeypatch):
    monkeypatch.setattr(tool, "fetch_pypi",
                        lambda *a: [tool.Dist(WHEEL, tool.sha256_of(dist_dir / WHEEL))])
    code = tool.main(["pypi", "--version", VERSION, "--dist", str(dist_dir),
                      "--verify", "--github-output", "", "--summary", ""])
    assert code == 1


# --------------------------------------------------------------------------- #
# the workflow around the tool
# --------------------------------------------------------------------------- #


def workflow(path=RELEASE_YML) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_pypi_publication_is_planned_before_the_environment_is_entered():
    jobs = workflow()["jobs"]
    assert "environment" not in jobs["pypi-plan"]
    assert jobs["pypi-publish"]["environment"]["name"] == "pypi"
    assert jobs["pypi-publish"]["needs"] == ["build", "pypi-plan"]
    assert "pypi-plan.outputs.uploads != '0'" in jobs["pypi-publish"]["if"]
    publish = [s for s in jobs["pypi-publish"]["steps"] if "pypi-publish" in str(s.get("uses"))]
    assert publish[0]["with"]["packages-dir"] == "publish/", (
        "the publisher must see only the files PyPI is missing")
    run = "\n".join(s.get("run", "") for s in jobs["pypi-plan"]["steps"])
    assert "release-reconcile.py pypi" in run and "--stage publish/" in run


def test_no_upload_error_is_hidden():
    body = RELEASE_YML.read_text(encoding="utf-8") + IMAGE_YML.read_text(encoding="utf-8")
    assert "continue-on-error" not in body
    assert "skip-existing" not in body, "an upload PyPI refuses is a decision, not noise"
    for line in body.splitlines():
        if "release-reconcile" in line or "pypi-publish" in line:
            assert "|| true" not in line


def test_a_complete_pypi_leaves_the_later_jobs_runnable():
    """A skipped `pypi-publish` (nothing to upload) must not skip the release
    page and the image with it, which is what `needs` does by default."""
    jobs = workflow()["jobs"]
    for name in ("github-release", "image"):
        condition = jobs[name]["if"]
        assert "always()" in condition
        assert "needs.pypi-publish.result != 'failure'" in condition
        assert "needs.pypi-publish.result != 'cancelled'" in condition
        assert "needs.build.result == 'success'" in condition
        assert "pypi-publish" in jobs[name]["needs"]


def test_the_release_page_and_the_image_check_pypi_themselves():
    steps = workflow()["jobs"]["github-release"]["steps"]
    verify = [s for s in steps if s.get("name", "").startswith("PyPI holds the version")]
    assert verify and "--verify" in verify[0]["run"]
    image = workflow(IMAGE_YML)["jobs"]["build"]["steps"]
    assert any(s.get("name") == "Wait for PyPI to have it" for s in image)


def test_a_dry_run_reads_every_destination_and_mutates_none():
    """`workflow_dispatch` with dry_run left ticked: the plan for every
    destination, and not one call that could publish."""
    jobs = workflow()["jobs"]
    reconcile = [s for s in jobs["github-release"]["steps"]
                 if s.get("id") == "reconcile"][0]
    assert reconcile["env"]["APPLY"] == (
        "${{ needs.build.outputs.publish == 'true' && '--apply' || '' }}")
    assert "$APPLY" in reconcile["run"] and "--apply" not in reconcile["run"]
    assert "needs.build.outputs.publish == 'true'" in jobs["pypi-publish"]["if"]
    assert jobs["image"]["with"]["dry_run"] == "${{ needs.build.outputs.publish != 'true' }}"

    image = workflow(IMAGE_YML)["jobs"]["build"]["steps"]
    by_name = {s.get("name"): s for s in image}
    build = by_name["Build and push"]
    assert "steps.pick.outputs.publish == 'yes'" in build["with"]["push"]
    for name in ("Publish GHCR", "Publish Docker Hub"):
        assert "steps.pick.outputs.publish == 'yes'" in by_name[name]["if"]
        assert "--apply" in by_name[name]["run"]
    for name in ("Plan GHCR", "Plan Docker Hub"):
        assert "--apply" not in by_name[name]["run"]
    pick = by_name["Which version"]["run"]
    assert '"$DRY" = "true"' in pick and 'echo "publish="' in pick


def test_latest_is_moved_by_retagging_never_by_a_build():
    image = workflow(IMAGE_YML)["jobs"]["build"]["steps"]
    tags = [s for s in image if s.get("id") == "tags"][0]["run"]
    release_branch = tags.split("else")[-1]
    assert ":latest" not in release_branch, "a release build pushes only version tags"
    assert "GHCR_BUILD" in tags and "HUB_BUILD" in tags


def test_the_image_says_its_version_on_its_label_and_out_loud():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'org.opencontainers.image.version="${COMODOR_VERSION}"' in dockerfile
    assert 'org.opencontainers.image.revision="${COMODOR_REVISION}"' in dockerfile
    final = dockerfile.split("FROM python:3.13-slim-bookworm\n")[-1]
    assert "ARG COMODOR_VERSION=" in final, "an ARG does not cross a stage boundary"

    image = workflow(IMAGE_YML)["jobs"]["build"]["steps"]
    check = [s for s in image if s.get("name") == "The image carries the version it is tagged with"]
    assert check and "--version" in check[0]["run"] and "exit 1" in check[0]["run"]
    build = [s for s in image if s.get("name") == "Build and push"][0]
    assert "COMODOR_REVISION=" in build["with"]["build-args"]


def test_the_summary_job_runs_whatever_happened():
    job = workflow()["jobs"]["summary"]
    assert job["if"].startswith("always()")
    assert set(job["needs"]) == {"build", "pypi-plan", "pypi-publish", "github-release", "image"}


# --------------------------------------------------------------------------- #
# the tag gate, run for real
# --------------------------------------------------------------------------- #


def gate_script() -> str:
    for step in workflow()["jobs"]["gate"]["steps"]:
        if step.get("name") == "The tag must not be behind main":
            return step["run"]
    raise AssertionError("no tag gate")


@pytest.fixture
def bash():
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not available")
    return found


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def run_gate(bash: str, checkout: Path, tag: str, tmp_path: Path) -> subprocess.CompletedProcess:
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    env = {**os.environ, "GITHUB_REF_NAME": tag, "GITHUB_STEP_SUMMARY": str(summary)}
    return subprocess.run([bash, "-c", gate_script()], cwd=checkout, env=env,
                          capture_output=True, text=True)


def test_the_gate_still_refuses_a_tag_behind_main(bash, tmp_path):
    """The gate is the workflow's own script, run against a repository with
    an `origin/main` one commit past the tag."""
    origin = tmp_path / "origin"
    git(tmp_path, "init", "-q", "-b", "main", str(origin))
    (origin / "a").write_text("1", encoding="utf-8")
    git(origin, "add", "a")
    git(origin, "commit", "-q", "-m", "one")
    git(origin, "tag", "v9.9.9")
    (origin / "a").write_text("2", encoding="utf-8")
    git(origin, "commit", "-q", "-am", "two")

    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(origin), str(checkout))
    behind = run_gate(bash, checkout, "v9.9.9", tmp_path)
    assert behind.returncode == 1, behind.stdout + behind.stderr
    assert "1 commit(s) behind main" in behind.stdout

    git(origin, "tag", "v9.9.10")
    git(checkout, "fetch", "-q", "--tags")
    current = run_gate(bash, checkout, "v9.9.10", tmp_path)
    assert current.returncode == 0, current.stdout + current.stderr


# --------------------------------------------------------------------------- #
# the GitHub client over a `gh` that is not there: every call the release
# makes, with the arguments and the standard input it makes it with
# --------------------------------------------------------------------------- #


class FakeGh:
    """Stands in for the `gh` binary under `GitHub`: answers the calls the
    release makes, records each one with its standard input, and refuses
    what the real `gh api` refuses — a flag it does not have, a body sent
    without `--input -`. Binary output is bytes, as `gh` prints it."""

    def __init__(self, tool, release_json=None, assets_bytes=None):
        self.tool = tool
        self.release = release_json          # None: no release for the tag
        self.assets_bytes = assets_bytes or {}
        self.calls: list[tuple[list[str], str | None, bool]] = []
        self._next_asset_id = 900

    def __call__(self, argv, stdin=None, binary=False):
        self.calls.append((list(argv), stdin, binary))
        if "--output" in argv:
            raise subprocess.CalledProcessError(1, argv, "", "unknown flag: --output")
        if argv[:2] == ["gh", "api"]:
            return self._api(argv, stdin, binary)
        if argv[:3] == ["gh", "release", "upload"]:
            assert self.release is not None
            path = Path(argv[4])
            self.release["assets"].append({
                "name": path.name, "id": self._next_asset_id, "state": "uploaded",
                "digest": "sha256:" + self.tool.sha256_of(path)})
            self._next_asset_id += 1
            return ""
        raise AssertionError(f"unexpected command {argv}")

    def _api(self, argv, stdin, binary):
        endpoint = argv[2]
        method = argv[argv.index("--method") + 1] if "--method" in argv else "GET"
        if "--input" in argv:
            assert argv[argv.index("--input") + 1] == "-", "a body is sent on stdin"
            assert stdin is not None, "gh would block on an empty stdin"
            payload = json.loads(stdin)
        else:
            payload = None
        if endpoint.endswith("/releases") and method == "POST":
            assert self.release is None
            self.release = {"id": 42, "draft": payload["draft"], "immutable": False,
                            "assets": [], "html_url": "https://x/" + payload["tag_name"],
                            "body": payload["body"] + "\n\n## What's Changed\n* generated\n",
                            "tag_name": payload["tag_name"]}
            assert payload["generate_release_notes"] is True
            return json.dumps(self.release)
        if "/releases/tags/" in endpoint:
            if self.release is None:
                raise subprocess.CalledProcessError(
                    1, argv, "", "gh: Not Found (HTTP 404)")
            return json.dumps(self.release)
        if "/releases/assets/" in endpoint:
            asset_id = int(endpoint.rsplit("/", 1)[1])
            assert "Accept: application/octet-stream" in argv
            if not binary:
                raise AssertionError("an asset body must be read as bytes")
            return self.assets_bytes[asset_id]
        if endpoint.endswith(f"/releases/{self.release['id']}"):
            if "--jq" in argv:
                return self.release["body"]
            if method == "PATCH":
                if payload is not None:
                    self.release.update(payload)
                elif "draft=false" in argv:
                    self.release["draft"] = False
                    self.release["immutable"] = True
                return json.dumps(self.release)
        raise AssertionError(f"unexpected api call {argv}")


def calls_to(gh: FakeGh, *prefix: str):
    return [call for call in gh.calls if call[0][:len(prefix)] == list(prefix)]


def expected_from(tool, dist_dir):
    return tool.local_dists(dist_dir, VERSION)


def test_a_first_release_is_created_through_the_wrapper_with_stdin(tool, dist_dir):
    """Path A, the normal first publication: no release for the tag, so the
    draft is created with a JSON body on `gh api`'s standard input, the
    files are uploaded, the draft is published. On the previous head the
    wrapper took no `stdin` and the very first call raised a TypeError."""
    gh = FakeGh(tool)
    github = tool.GitHub("ifekri/Comodor", run=gh)
    plan = tool.plan_github(expected_from(tool, dist_dir), github.release("v" + VERSION))
    assert plan.state == tool.ABSENT
    after = tool.apply_github(plan, github, "v" + VERSION, VERSION, dist_dir, None)
    assert tool.plan_github(expected_from(tool, dist_dir), after).state == tool.COMPLETE

    creates = [c for c in calls_to(gh, "gh", "api") if "POST" in c[0]]
    assert len(creates) == 1
    argv, stdin, binary = creates[0]
    assert argv[2] == "repos/ifekri/Comodor/releases"
    assert argv[argv.index("--input") + 1] == "-" and binary is False
    body = json.loads(stdin)
    assert body["tag_name"] == "v" + VERSION and body["draft"] is True
    assert body["body"].startswith("## Requirements")
    uploads = calls_to(gh, "gh", "release", "upload")
    assert [Path(c[0][4]).name for c in uploads] == [WHEEL, SDIST]
    assert all("--clobber" not in c[0] for c in uploads)
    assert not gh.release["draft"], "published at the end"


def test_a_draft_gains_the_requirements_through_stdin(tool, dist_dir):
    """Path B: a hand-written draft is finished and its body is set with a
    JSON document on standard input — the second call that took `stdin`."""
    gh = FakeGh(tool, {"id": 7, "draft": True, "immutable": False, "assets": [],
                       "html_url": "https://x/v" + VERSION,
                       "body": "Hand-written notes.\n"})
    github = tool.GitHub("ifekri/Comodor", run=gh)
    found = github.release("v" + VERSION)
    plan = tool.plan_github(expected_from(tool, dist_dir), found)
    tool.apply_github(plan, github, "v" + VERSION, VERSION, dist_dir, found)

    patches = [c for c in calls_to(gh, "gh", "api")
               if "PATCH" in c[0] and "--input" in c[0]]
    assert len(patches) == 1
    argv, stdin, _ = patches[0]
    assert argv[2] == "repos/ifekri/Comodor/releases/7"
    assert json.loads(stdin)["body"].startswith("## Requirements")
    assert "Hand-written notes." in json.loads(stdin)["body"]
    assert gh.release["body"].startswith("## Requirements")
    assert not gh.release["draft"]


def test_a_legacy_asset_without_a_digest_is_downloaded_as_bytes_and_hashed(tool):
    """Path C: an asset uploaded before GitHub reported digests. `gh api`
    has no `--output`; the body is read from standard output as bytes —
    a wheel is a zip and is not UTF-8 — and hashed from those bytes."""
    payload = b"PK\x03\x04\xff\xfe\x00\x80 not text \xc3\x28" * 1000
    gh = FakeGh(tool, {"id": 7, "draft": False, "immutable": True,
                       "html_url": "", "body": "",
                       "assets": [{"name": WHEEL, "id": 321, "state": "uploaded",
                                   "size": len(payload)}]},
                assets_bytes={321: payload})
    github = tool.GitHub("ifekri/Comodor", run=gh)
    found = github.release("v" + VERSION)
    assert found is not None
    assert found.assets[0].sha256 == hashlib.sha256(payload).hexdigest()

    fetches = [c for c in gh.calls if "/releases/assets/321" in c[0][2]]
    assert len(fetches) == 1
    argv, stdin, binary = fetches[0]
    assert argv == ["gh", "api", "repos/ifekri/Comodor/releases/assets/321",
                    "-H", "Accept: application/octet-stream"]
    assert binary is True and stdin is None


def test_the_runner_keeps_bytes_as_bytes_and_errors_as_text(tool, tmp_path):
    """`_run` itself, on a real process: binary output is returned intact,
    text output is decoded, a failure carries both streams as text."""
    script = tmp_path / "emit.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.buffer.write(bytes(range(256)))\n"
        "sys.stdout.buffer.flush()\n"
        "sys.stderr.write('warned')\n"
        "sys.exit(int(sys.argv[1]))\n", encoding="utf-8")
    raw = tool._run([sys.executable, str(script), "0"], binary=True)
    assert raw == bytes(range(256))
    with pytest.raises(subprocess.CalledProcessError) as caught:
        tool._run([sys.executable, str(script), "3"], binary=True)
    assert caught.value.returncode == 3 and "warned" in caught.value.stderr
    assert isinstance(caught.value.stdout, str)

    echo = tmp_path / "echo.py"
    echo.write_text("import sys; sys.stdout.write(sys.stdin.read().upper())",
                    encoding="utf-8")
    assert tool._run([sys.executable, str(echo)], stdin="hello") == "HELLO"


# --------------------------------------------------------------------------- #
# the image tag is not the package version
# --------------------------------------------------------------------------- #

# The reference grammar from distribution/reference (docker/distribution):
# a name is domain-optional path components; a tag is up to 128 word
# characters, dots and dashes, starting with a word character. `+` is not
# in it — and a hatch-vcs dev version has one.
_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
_LABEL = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
_DOMAIN = rf"(?:{_LABEL}(?:\.{_LABEL})*(?::[0-9]+)?)"
REFERENCE = re.compile(
    rf"^(?:{_DOMAIN}/)?{_COMPONENT}(?:/{_COMPONENT})*(?::(?P<tag>[\w][\w.-]{{0,127}}))?$")


def is_valid_reference(reference: str) -> bool:
    return REFERENCE.match(reference) is not None


def test_the_reference_grammar_is_the_one_registries_use():
    assert is_valid_reference("ghcr.io/ifekri/comodor:2.0.1")
    assert is_valid_reference("ifekri/comodor:latest")
    assert is_valid_reference("ghcr.io/ifekri/comodor:dry-run")
    assert not is_valid_reference("ghcr.io/ifekri/comodor:2.0.2.dev3+g1234abc")
    assert not is_valid_reference("ghcr.io/ifekri/comodor:")
    assert not is_valid_reference("ghcr.io/ifekri/comodor:-x")


def image_step(name: str) -> dict:
    for step in workflow(IMAGE_YML)["jobs"]["build"]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step {name!r}")


def run_step(bash: str, step: dict, env: dict[str, str], tmp_path: Path) -> dict[str, str]:
    """Run a workflow step's script with `env`, the way the runner would,
    and return what it wrote to GITHUB_OUTPUT (multi-line values included)."""
    output = tmp_path / f"{step['id']}.out"
    output.write_text("", encoding="utf-8")
    full = {**os.environ, **env, "GITHUB_OUTPUT": str(output)}
    completed = subprocess.run([bash, "-c", step["run"]], env=full,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    parsed: dict[str, str] = {}
    lines = output.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        key, _, value = lines[index].partition("=")
        if lines[index].endswith("<<EOF"):
            key, _, _ = lines[index].partition("<<")
            block = []
            index += 1
            while lines[index] != "EOF":
                block.append(lines[index])
                index += 1
            parsed[key] = "\n".join(block)
        else:
            parsed[key] = value
        index += 1
    return parsed


def pick_and_tag(bash, tmp_path, *, version, event, dry_run,
                 hub="", ghcr_build="", hub_build=""):
    pick = run_step(bash, image_step("Which version"),
                    {"WANTED": version, "DRY": dry_run, "EVENT": event}, tmp_path)
    tags = run_step(bash, image_step("Which tags"), {
        "OWNER": "ifekri", "VERSION": pick["version"], "RELEASE": pick["release"],
        "PUBLISH": pick["publish"], "HUB": hub,
        "GHCR_BUILD": ghcr_build, "HUB_BUILD": hub_build}, tmp_path)
    return pick, tags


def test_a_dry_run_from_a_development_main_gets_a_docker_safe_tag(bash, tmp_path):
    """Path D: `workflow_dispatch` between releases, where hatch-vcs names
    the tree `2.0.2.dev3+g1234abc`. Not a release version, so nothing is
    published — and the local tag must be one a registry would accept,
    because `docker build -t` applies the same grammar."""
    pick, tags = pick_and_tag(bash, tmp_path, version="2.0.2.dev3+g1234abc",
                              event="workflow_dispatch", dry_run="true")
    assert pick["release"] == "" and pick["publish"] == ""
    assert tags["build"] == "yes"
    references = tags["list"].splitlines()
    assert references == ["ghcr.io/ifekri/comodor:dry-run"]
    assert tags["test"] == "ghcr.io/ifekri/comodor:dry-run"
    for reference in references + [tags["test"]]:
        assert is_valid_reference(reference), reference
        assert "2.0.2.dev3" not in reference


def test_a_pull_request_build_is_tagged_the_same_way(bash, tmp_path):
    pick, tags = pick_and_tag(bash, tmp_path, version="", event="pull_request", dry_run="")
    assert pick["publish"] == ""
    assert tags["list"].splitlines() == ["ghcr.io/ifekri/comodor:dry-run"]
    assert all(is_valid_reference(r) for r in tags["list"].splitlines())


def test_a_stable_release_is_tagged_with_exactly_its_version(bash, tmp_path):
    """Path E: the version is the tag, character for character, in every
    registry the plan says to push to, and `latest` is not among them."""
    pick, tags = pick_and_tag(bash, tmp_path, version="2.0.1", event="push", dry_run="",
                              hub="ifekri/comodor", ghcr_build="true", hub_build="true")
    assert pick["release"] == "yes" and pick["publish"] == "yes"
    assert tags["tag"] == "2.0.1"
    assert tags["list"].splitlines() == ["ghcr.io/ifekri/comodor:2.0.1",
                                         "ifekri/comodor:2.0.1"]
    assert tags["test"] == "ghcr.io/ifekri/comodor:2.0.1"
    assert all(is_valid_reference(r) for r in tags["list"].splitlines())

    _, only_hub = pick_and_tag(bash, tmp_path, version="2.0.1", event="push", dry_run="",
                               hub="ifekri/comodor", ghcr_build="false", hub_build="true")
    assert only_hub["list"].splitlines() == ["ifekri/comodor:2.0.1"]
    _, nothing = pick_and_tag(bash, tmp_path, version="2.0.1", event="push", dry_run="",
                              hub="", ghcr_build="false", hub_build="false")
    assert nothing["list"] == "" and nothing["build"] == ""


def test_a_main_push_without_a_version_is_edge_and_latest(bash, tmp_path):
    _, tags = pick_and_tag(bash, tmp_path, version="", event="push", dry_run="",
                           hub="ifekri/comodor")
    assert tags["list"].splitlines() == [
        "ghcr.io/ifekri/comodor:latest", "ghcr.io/ifekri/comodor:edge",
        "ifekri/comodor:latest", "ifekri/comodor:edge"]


def test_a_publishing_run_never_rewrites_a_non_release_version_into_a_tag(bash, tmp_path):
    """A version that is not a release version is refused, not sanitized:
    a tag that differs from the version would be a different identity."""
    pick = run_step(bash, image_step("Which version"),
                    {"WANTED": "2.0.2.dev3+g1234abc", "DRY": "false", "EVENT": "push"},
                    tmp_path)
    assert pick["publish"] == "yes" and pick["release"] == ""
    step = image_step("Which tags")
    output = tmp_path / "refused.out"
    output.write_text("", encoding="utf-8")
    completed = subprocess.run([bash, "-c", step["run"]], env={
        **os.environ, "OWNER": "ifekri", "VERSION": "2.0.2.dev3+g1234abc", "RELEASE": "",
        "PUBLISH": "yes", "HUB": "", "GHCR_BUILD": "", "HUB_BUILD": "",
        "GITHUB_OUTPUT": str(output)}, capture_output=True, text=True)
    assert completed.returncode == 1
    assert "not a release version" in completed.stdout
    assert output.read_text(encoding="utf-8") == ""
