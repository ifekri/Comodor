#!/usr/bin/env python3
"""Reconcile one release against what its destinations already hold.

    python tools/release-reconcile.py pypi --version 2.0.1 --dist dist/ --stage publish/
    python tools/release-reconcile.py github --tag v2.0.1 --version 2.0.1 --dist dist/ \
        --repo ifekri/Comodor [--apply]
    python tools/release-reconcile.py image --repository ghcr.io/ifekri/comodor \
        --version 2.0.1 [--apply]
    python tools/release-reconcile.py simulate state.json

A release is four publications — PyPI, the GitHub Release, GHCR and Docker
Hub — and a workflow that stops between two of them must be able to run
again and finish the rest without touching what is already right. So each
destination is looked at on its own and classified:

    ABSENT     nothing there yet: publish it
    PARTIAL    some of it there, all of it correct: publish only the rest
    COMPLETE   all of it there and correct: verify, and do nothing
    CONFLICT   something there that is not this release: stop, say what

"Correct" is checked, not assumed. A distribution is the same distribution
when its SHA-256 matches the file this build produced — the build is
byte-reproducible, and PyPI and GitHub both report the digest of what they
hold. An image is the same image when its version label names the release
and it carries the platforms a release ships. Nothing here overwrites a
published file, replaces a published asset, or moves a semantic version tag
that already resolves; the only tag that is ever moved is `latest`, and only
to the release being built.

The decisions are pure functions over observed state (`plan_*`), so they are
tested without a network; the commands around them observe and apply. Only
the standard library, `gh` and `docker` are used: this runs on the release
runner, not in the product.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# states and actions
# --------------------------------------------------------------------------- #

ABSENT = "ABSENT"
PARTIAL = "PARTIAL"
COMPLETE = "COMPLETE"
CONFLICT = "CONFLICT"
#: The destination was not asked for: no credentials, or no tag to publish.
NOT_CONFIGURED = "NOT_CONFIGURED"
#: `latest` already resolves to the release.
CURRENT = "CURRENT"
#: `latest` resolves to something older, or to nothing.
STALE = "STALE"

#: The platforms a release image ships. An image missing one is not this
#: release, however its label reads.
REQUIRED_PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})


@dataclass(frozen=True)
class Dist:
    """One distribution file, local or remote, named and hashed."""

    name: str
    sha256: str
    size: int = 0


@dataclass(frozen=True)
class Asset:
    """A GitHub Release asset. `sha256` is empty until the digest is known."""

    name: str
    sha256: str
    id: int = 0
    state: str = "uploaded"
    size: int = 0


@dataclass(frozen=True)
class Release:
    id: int
    draft: bool
    immutable: bool
    assets: tuple[Asset, ...] = ()
    html_url: str = ""


@dataclass(frozen=True)
class Image:
    """What a registry tag resolves to: a manifest list and its labels."""

    digest: str
    platforms: frozenset[str] = frozenset()
    version: str = ""
    revision: str = ""


@dataclass(frozen=True)
class Action:
    """One thing the release would do. `kind` is the verb: SKIP, UPLOAD,
    CREATE, REPLACE, PUBLISH, BUILD, COPY, UPDATE_LATEST, FAIL."""

    kind: str
    target: str
    why: str = ""

    def __str__(self) -> str:
        line = f"{self.kind:<14}{self.target}"
        return f"{line}  — {self.why}" if self.why else line


@dataclass
class Plan:
    destination: str
    state: str
    actions: list[Action] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def add(self, kind: str, target: str, why: str = "") -> None:
        self.actions.append(Action(kind, target, why))

    def fail(self, target: str, why: str) -> None:
        self.state = CONFLICT
        self.actions.append(Action("FAIL", target, why))
        self.problems.append(f"{target}: {why}")

    def uploads(self) -> list[str]:
        return [action.target for action in self.actions
                if action.kind in ("UPLOAD", "REPLACE")]

    def render(self) -> str:
        lines = [f"{self.destination}: {self.state}"]
        lines.extend(f"  {action}" for action in self.actions)
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# PyPI
# --------------------------------------------------------------------------- #


def plan_pypi(expected: list[Dist], remote: list[Dist] | None) -> Plan:
    """What PyPI needs, given what it has for this version.

    `remote` is None when the version is not on PyPI at all. A file that is
    there with the digest this build produced is verified and left alone; a
    file that is there with another digest, or a file this build did not
    produce, is someone else's release under our number, and nothing is
    uploaded next to it. PyPI never lets a filename be uploaded twice, so
    "already there and identical" has to be a success or the release could
    never be finished.
    """
    plan = Plan("PyPI", ABSENT)
    if remote is None:
        for dist in expected:
            plan.add("UPLOAD", dist.name, "the version is not on PyPI")
        return plan

    have = {dist.name: dist for dist in remote}
    for dist in expected:
        found = have.pop(dist.name, None)
        if found is None:
            plan.add("UPLOAD", dist.name, "not on PyPI yet")
        elif found.sha256 == dist.sha256:
            plan.add("SKIP", dist.name, f"on PyPI, sha256 {dist.sha256[:12]}… matches")
        else:
            plan.fail(dist.name, (
                f"PyPI holds a file of this name with sha256 {found.sha256}, this "
                f"build produced {dist.sha256}. PyPI files cannot be replaced; "
                "either another publisher released this version, or this build no "
                "longer reproduces the tag's bytes. Compare the two before deciding "
                "on a new patch version."))
    for name in sorted(have):
        plan.fail(name, "PyPI holds this file for the version, but this build did "
                        "not produce it — another publisher's release")
    if plan.problems:
        return plan
    uploads = plan.uploads()
    plan.state = COMPLETE if not uploads else (
        PARTIAL if len(uploads) < len(expected) else ABSENT)
    return plan


def fetch_pypi(project: str, version: str, base: str = "https://pypi.org") -> list[Dist] | None:
    """The files PyPI holds for `project==version`, or None when it has none."""
    url = f"{base}/pypi/{project}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:      # noqa: S310
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    return [Dist(entry["filename"], entry["digests"]["sha256"], int(entry.get("size") or 0))
            for entry in data.get("urls", [])]


# --------------------------------------------------------------------------- #
# GitHub Release
# --------------------------------------------------------------------------- #


def plan_github(expected: list[Dist], release: Release | None) -> Plan:
    """What the GitHub Release needs.

    A release object is not a release: the page a person downloads from has
    to carry the files. So a published release with the assets is COMPLETE,
    a published release missing some is PARTIAL and finished in place while
    GitHub still allows it, and a published release GitHub has frozen — the
    repository turns immutability on, and it is right to — cannot be finished
    at all, which is said plainly rather than warned about. Drafts take
    uploads freely; an asset in a draft is replaced only when it is not
    actually uploaded (an interrupted transfer), never when it is a different
    file, because a different file is a different release.
    """
    plan = Plan("GitHub Release", ABSENT)
    if release is None:
        plan.add("CREATE", "draft release", "no release for the tag")
        for dist in expected:
            plan.add("UPLOAD", dist.name, "to the draft")
        plan.add("PUBLISH", "draft release", "after every asset is verified")
        return plan

    have = {asset.name: asset for asset in release.assets}
    missing: list[Dist] = []
    for dist in expected:
        asset = have.get(dist.name)
        if asset is None:
            missing.append(dist)
        elif asset.state != "uploaded":
            if release.draft:
                plan.add("REPLACE", dist.name,
                         f"the draft's copy is in state {asset.state!r}: an upload that "
                         "never finished")
            else:
                plan.fail(dist.name, f"the published release holds this asset in state "
                                     f"{asset.state!r} and it cannot be replaced")
        elif asset.sha256 == dist.sha256:
            plan.add("SKIP", dist.name, f"attached, sha256 {dist.sha256[:12]}… matches")
        else:
            plan.fail(dist.name, (
                f"the release holds an asset of this name with sha256 {asset.sha256}, "
                f"this build produced {dist.sha256}. A published asset is never "
                "replaced; either another publisher attached it, or this build no "
                "longer reproduces the tag's bytes."))
    if plan.problems:
        return plan

    if release.draft:
        for dist in missing:
            plan.add("UPLOAD", dist.name, "to the draft")
        plan.add("PUBLISH", "draft release", "after every asset is verified")
        plan.state = PARTIAL if have else ABSENT
        return plan

    if not missing and not plan.uploads():
        plan.state = COMPLETE
        plan.add("SKIP", "published release", "every asset is attached and verified")
        return plan
    if release.immutable:
        names = ", ".join(dist.name for dist in missing)
        plan.fail("published release", (
            f"the release is published and immutable, and is missing {names}. "
            "GitHub does not allow assets to be added to an immutable release, so "
            "this release cannot be completed in place. The package on PyPI is "
            "unaffected. To ship these files on a release page, cut the next "
            "patch version; do not delete or recreate this release."))
        return plan
    for dist in missing:
        plan.add("UPLOAD", dist.name, "the published release is still mutable")
    plan.state = PARTIAL
    return plan


class GitHub:
    """The release API through `gh`, which the runner has signed in."""

    def __init__(self, repo: str, run=None) -> None:
        self.repo = repo
        self._run = run or _run

    def api(self, endpoint: str, *args: str) -> str:
        return self._run(["gh", "api", f"repos/{self.repo}/{endpoint}", *args])

    def release(self, tag: str) -> Release | None:
        try:
            raw = self.api(f"releases/tags/{tag}")
        except subprocess.CalledProcessError as error:
            if "HTTP 404" in (error.stderr or "") + (error.stdout or ""):
                return None
            raise
        return self.parse_release(json.loads(raw))

    def parse_release(self, data: dict) -> Release:
        assets = []
        for entry in data.get("assets", []):
            digest = str(entry.get("digest") or "")
            sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
            asset = Asset(entry["name"], sha256, int(entry["id"]),
                          str(entry.get("state") or "uploaded"), int(entry.get("size") or 0))
            if not asset.sha256 and asset.state == "uploaded":
                asset = Asset(asset.name, self.download_sha256(asset), asset.id,
                              asset.state, asset.size)
            assets.append(asset)
        return Release(int(data["id"]), bool(data.get("draft")),
                       bool(data.get("immutable")), tuple(assets),
                       str(data.get("html_url") or ""))

    def download_sha256(self, asset: Asset) -> str:
        """GitHub reports a digest for every asset uploaded since mid-2025;
        an older one is fetched and hashed, which is slower and just as true."""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / asset.name
            self._run(["gh", "api", f"repos/{self.repo}/releases/assets/{asset.id}",
                       "-H", "Accept: application/octet-stream", "--output", str(target)])
            return sha256_of(target)

    def create_draft(self, tag: str, name: str, body: str) -> Release:
        # The body is put above the notes GitHub generates, as the API says.
        payload = json.dumps({"tag_name": tag, "name": name, "body": body,
                              "draft": True, "generate_release_notes": True})
        raw = self.api("releases", "--method", "POST", "--input", "-", stdin=payload)
        return self.parse_release(json.loads(raw))

    def upload(self, tag: str, path: Path) -> None:
        # No `--clobber`: replacing is a decision the plan makes explicitly,
        # by deleting first, and only for an upload that never finished.
        self._run(["gh", "release", "upload", tag, str(path), "--repo", self.repo])

    def delete_asset(self, asset: Asset) -> None:
        self.api(f"releases/assets/{asset.id}", "--method", "DELETE")

    def publish(self, release: Release) -> None:
        self.api(f"releases/{release.id}", "--method", "PATCH", "-F", "draft=false")

    def body(self, release: Release) -> str:
        return self.api(f"releases/{release.id}", "--jq", ".body")

    def set_body(self, release: Release, body: str) -> None:
        self.api(f"releases/{release.id}", "--method", "PATCH", "--input", "-",
                 stdin=json.dumps({"body": body}))


REQUIREMENTS = """## Requirements

Python 3.11 or newer. The interactive interface also needs
[Bun](https://bun.sh) 1.3 or newer on the machine; `comodor run`
and `comodor web` work without it. Nothing is downloaded at
first launch. `comodor doctor` says what is there.
"""


def release_body(version: str) -> str:
    return REQUIREMENTS + f"""
## Install

### Linux and macOS

```bash
curl -fsSL get.comodor.ai | sh
```

### Windows

```powershell
irm get.comodor.ai | iex
```

### UV

```bash
uv tool install comodor=={version}
```

### PIP

```bash
pip install comodor=={version}
```

### PIPX

```bash
pipx install comodor=={version}
```
"""


def apply_github(plan: Plan, github: GitHub, tag: str, version: str,
                 dist_dir: Path, release: Release | None) -> Release:
    """Do what the plan says, in the order that keeps a published release
    from ever being touched: create, upload, publish. Returns the release
    as it is afterwards; the caller re-plans against it to verify."""
    files = {path.name: path for path in dist_dir.iterdir() if path.is_file()}
    current = release
    for action in plan.actions:
        if action.kind == "CREATE":
            current = github.create_draft(tag, tag, release_body(version))
        elif action.kind == "REPLACE":
            assert current is not None
            stale = next(asset for asset in current.assets if asset.name == action.target)
            github.delete_asset(stale)
            github.upload(tag, files[action.target])
        elif action.kind == "UPLOAD":
            github.upload(tag, files[action.target])
        elif action.kind == "PUBLISH":
            assert current is not None
            # A draft somebody wrote by hand keeps its words, but the page
            # must state what the package needs; the block goes above the
            # draft's own notes when it is not already there.
            body = github.body(current)
            if "## Requirements" not in body:
                github.set_body(current, REQUIREMENTS + "\n" + body)
            github.publish(current)
    refreshed = github.release(tag)
    if refreshed is None:
        raise SystemExit(f"GitHub Release {tag} vanished while it was being completed")
    return refreshed


# --------------------------------------------------------------------------- #
# container images
# --------------------------------------------------------------------------- #


def plan_image(name: str, repository: str, version: str,
               tagged: Image | None, latest: Image | None,
               configured: bool = True, source: str = "") -> Plan:
    """What a registry needs for `repository:version` and `repository:latest`.

    The version tag is release identity and is never moved: absent, it is
    built (or copied from `source`, a registry that already has the verified
    image — one build, two registries); present and verified, it is left
    alone; present and not this release, the run stops. `latest` is a
    pointer and is moved to the version image when it points elsewhere.
    """
    plan = Plan(name, ABSENT)
    if not configured:
        plan.state = NOT_CONFIGURED
        plan.add("SKIP", repository, "not configured — no credentials")
        return plan

    versioned = f"{repository}:{version}"
    if tagged is None:
        if source:
            plan.add("COPY", versioned, f"from {source}, which is verified")
        else:
            plan.add("BUILD", versioned, "not in the registry")
    else:
        missing = REQUIRED_PLATFORMS - tagged.platforms
        if tagged.version != version:
            plan.fail(versioned, (
                f"the image is there but labels itself version {tagged.version!r}, not "
                f"{version!r}. A semantic version tag is never overwritten; find out "
                "what published it before releasing under this number."))
        elif missing:
            plan.fail(versioned, (
                f"the image is there without {', '.join(sorted(missing))}. A "
                "semantic version tag is never overwritten; the platforms a release "
                "ships are all built in one go."))
        else:
            plan.state = COMPLETE
            plan.add("SKIP", versioned, f"verified: version {version}, "
                     f"{', '.join(sorted(tagged.platforms & REQUIRED_PLATFORMS))}")
    if plan.problems:
        return plan

    latest_tag = f"{repository}:latest"
    if tagged is None:
        plan.add("UPDATE_LATEST", latest_tag, "once the version image is published")
    elif latest is not None and latest.digest == tagged.digest:
        plan.add("SKIP", latest_tag, "already resolves to the release")
    else:
        was = f"pointed at {latest.digest[:19]}…" if latest else "did not exist"
        plan.add("UPDATE_LATEST", latest_tag, f"{was}; retagged to the release, no rebuild")
    return plan


def latest_state(plan: Plan) -> str:
    for action in plan.actions:
        if action.target.endswith(":latest"):
            return CURRENT if action.kind == "SKIP" else STALE
    return NOT_CONFIGURED


def parse_imagetools(raw: str) -> Image:
    """`docker buildx imagetools inspect --format '{{json .}}'`: the manifest
    list, and the image config for each platform, with its labels."""
    data = json.loads(raw)
    manifest = data.get("manifest") or data.get("Manifest") or {}
    digest = str(manifest.get("digest") or data.get("digest") or "")
    platforms: set[str] = set()
    for entry in manifest.get("manifests", []) or []:
        platform = entry.get("platform") or {}
        if platform.get("os") and platform.get("architecture"):
            if platform.get("os") == "unknown":       # attestation manifests
                continue
            platforms.add(f"{platform['os']}/{platform['architecture']}")
    image = data.get("image") or data.get("Image") or {}
    configs = [image] if "config" in image else list(image.values())
    labels: dict = {}
    for config in configs:
        found = (config or {}).get("config", {}).get("Labels") or {}
        labels = labels or found
        if not platforms and config.get("os") and config.get("architecture"):
            platforms.add(f"{config['os']}/{config['architecture']}")
    return Image(digest, frozenset(platforms),
                 str(labels.get("org.opencontainers.image.version") or ""),
                 str(labels.get("org.opencontainers.image.revision") or ""))


class Registry:
    """A registry through `docker buildx imagetools`, signed in by the runner."""

    def __init__(self, run=None) -> None:
        self._run = run or _run

    def inspect(self, reference: str) -> Image | None:
        try:
            raw = self._run(["docker", "buildx", "imagetools", "inspect", reference,
                             "--format", "{{json .}}"])
        except subprocess.CalledProcessError as error:
            text = (error.stderr or "") + (error.stdout or "")
            if any(marker in text.lower() for marker in
                   ("not found", "manifest unknown", "no such manifest", "name unknown")):
                return None
            raise
        return parse_imagetools(raw)

    def retag(self, source: str, target: str) -> None:
        """Point `target` at the manifest list `source` resolves to. Registry
        side, no pull, no rebuild — and across registries it copies blobs."""
        self._run(["docker", "buildx", "imagetools", "create", "-t", target, source])


# --------------------------------------------------------------------------- #
# whole release
# --------------------------------------------------------------------------- #


def plan_release(expected: list[Dist], pypi: list[Dist] | None,
                 release: Release | None, version: str,
                 ghcr: tuple[Image | None, Image | None],
                 hub: tuple[Image | None, Image | None] | None,
                 ghcr_repository: str = "ghcr.io/ifekri/comodor",
                 hub_repository: str = "ifekri/comodor",
                 tag: str = "") -> list[Plan]:
    """Every destination, independently. Used by `simulate` and the tests;
    the workflow runs the destinations as separate jobs with the same rules."""
    plans = [plan_pypi(expected, pypi)]
    if tag:
        plans.append(plan_github(expected, release))
    else:
        skipped = Plan("GitHub Release", NOT_CONFIGURED)
        skipped.add("SKIP", "release", "not a tag build")
        plans.append(skipped)
    ghcr_plan = plan_image("GHCR", ghcr_repository, version, *ghcr)
    plans.append(ghcr_plan)
    if hub is None:
        plans.append(plan_image("Docker Hub", hub_repository, version, None, None,
                                configured=False))
    else:
        source = f"{ghcr_repository}:{version}" if ghcr_plan.state == COMPLETE else ""
        plans.append(plan_image("Docker Hub", hub_repository, version, *hub, source=source))
    return plans


def load_state(data: dict) -> list[Plan]:
    """A simulated state: what every destination holds, as JSON."""
    version = data["version"]

    def dists(entries) -> list[Dist]:
        return [Dist(entry["name"], entry["sha256"], int(entry.get("size") or 0))
                for entry in entries]

    def image(entry) -> Image | None:
        if entry is None:
            return None
        return Image(entry["digest"], frozenset(entry.get("platforms", [])),
                     entry.get("version", ""), entry.get("revision", ""))

    expected = dists(data["expected"])
    pypi = data.get("pypi")
    pypi_dists = None if pypi is None else dists(pypi)
    github = data.get("github")
    release = None
    if github is not None:
        release = Release(int(github.get("id", 1)), bool(github.get("draft")),
                          bool(github.get("immutable")),
                          tuple(Asset(a["name"], a.get("sha256", ""), int(a.get("id", 0)),
                                      a.get("state", "uploaded"))
                                for a in github.get("assets", [])))
    ghcr = data.get("ghcr") or {}
    hub = data.get("dockerhub")
    return plan_release(
        expected, pypi_dists, release, version,
        (image(ghcr.get("version")), image(ghcr.get("latest"))),
        None if hub is None else (image(hub.get("version")), image(hub.get("latest"))),
        tag=data.get("tag", f"v{version}"))


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #


def _run(argv: list[str], stdin: str | None = None) -> str:
    completed = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                               check=False, encoding="utf-8")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, argv,
                                            completed.stdout, completed.stderr)
    return completed.stdout


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_dists(folder: Path, version: str = "") -> list[Dist]:
    """The distributions a build produced: every wheel and sdist in `dist/`.
    Each must carry `version` in its name — the files are the release."""
    found = [Dist(path.name, sha256_of(path), path.stat().st_size)
             for path in sorted(folder.iterdir())
             if path.is_file() and path.suffix in (".whl", ".gz")]
    if not found:
        raise SystemExit(f"no distributions in {folder}")
    strays = [dist.name for dist in found
              if version and f"-{version}" not in dist.name.replace(".tar.gz", "")]
    if strays:
        raise SystemExit(f"not built for version {version}: {', '.join(strays)}")
    return found


def write_outputs(pairs: dict[str, str], path: str | None) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def write_summary(text: str, path: str | None) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def summarize(plan: Plan, heading: str, note: str = "") -> str:
    lines = [f"## {heading}", "", f"State: **{plan.state}**", "", "```text",
             plan.render(), "```"]
    if note:
        lines += ["", note]
    return "\n".join(lines)


def finish(plan: Plan) -> int:
    print(plan.render())
    if not plan.ok:
        for problem in plan.problems:
            print(f"::error::{plan.destination}: {problem}")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def cmd_pypi(args) -> int:
    expected = local_dists(Path(args.dist), args.version)
    remote = fetch_pypi(args.project, args.version, args.index)
    plan = plan_pypi(expected, remote)
    # PyPI is a CDN: a file accepted a moment ago is not listed everywhere
    # yet. A verify that follows an upload waits, bounded, for the listing
    # to catch up — and stops waiting the moment it sees a conflict.
    deadline = time.monotonic() + args.wait
    while args.verify and plan.ok and plan.state != COMPLETE and time.monotonic() < deadline:
        time.sleep(10)
        remote = fetch_pypi(args.project, args.version, args.index)
        plan = plan_pypi(expected, remote)
    if args.verify and plan.ok and plan.state != COMPLETE:
        plan.fail(f"comodor=={args.version}", "publication was expected to be complete, "
                  f"but the version is {plan.state} on PyPI")
    if args.stage and plan.ok:
        stage = Path(args.stage)
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        for name in plan.uploads():
            shutil.copy2(Path(args.dist) / name, stage / name)
    write_outputs({"state": plan.state, "uploads": str(len(plan.uploads()))},
                  args.github_output)
    write_summary(summarize(plan, f"PyPI — comodor {args.version}"), args.summary)
    return finish(plan)


def cmd_github(args) -> int:
    expected = local_dists(Path(args.dist), args.version)
    github = GitHub(args.repo)
    release = github.release(args.tag)
    plan = plan_github(expected, release)
    if plan.ok and args.apply and plan.state != COMPLETE:
        print(plan.render())
        print()
        release = apply_github(plan, github, args.tag, args.version, Path(args.dist), release)
        plan = plan_github(expected, release)
        if plan.state != COMPLETE:
            plan.fail(args.tag, "after applying the plan the release is still "
                                f"{plan.state}; see the actions above")
    elif plan.ok and args.verify and plan.state != COMPLETE:
        plan.fail(args.tag, f"the release was expected to be complete but is {plan.state}")
    write_outputs({"state": plan.state,
                   "url": release.html_url if release else ""}, args.github_output)
    write_summary(summarize(plan, f"GitHub Release — {args.tag}"), args.summary)
    return finish(plan)


def cmd_image(args) -> int:
    registry = Registry()
    configured = not args.not_configured
    tagged = latest = None
    if configured:
        tagged = registry.inspect(f"{args.repository}:{args.version}")
        latest = registry.inspect(f"{args.repository}:latest")
    plan = plan_image(args.name, args.repository, args.version, tagged, latest,
                      configured=configured, source=args.source)
    if plan.ok and args.apply and not any(a.kind == "BUILD" for a in plan.actions):
        # Registry-side only: a copy from the verified source, and `latest`.
        # A version image that is not there is the build step's job.
        applied = False
        if any(a.kind in ("COPY", "UPDATE_LATEST") for a in plan.actions):
            print(plan.render())
            print()
        for action in plan.actions:
            if action.kind == "COPY":
                registry.retag(args.source, action.target)
                applied = True
            elif action.kind == "UPDATE_LATEST":
                registry.retag(f"{args.repository}:{args.version}", action.target)
                applied = True
        if applied:
            tagged = registry.inspect(f"{args.repository}:{args.version}")
            latest = registry.inspect(f"{args.repository}:latest")
            plan = plan_image(args.name, args.repository, args.version, tagged, latest)
            if plan.ok and (plan.state != COMPLETE or latest_state(plan) != CURRENT):
                plan.fail(args.repository, "after retagging, the registry does not "
                                           "resolve as expected; see the actions above")
    if args.verify and plan.ok and plan.state != COMPLETE:
        plan.fail(f"{args.repository}:{args.version}",
                  f"expected to be published by now, but it is {plan.state}")
    write_outputs({"state": plan.state, "latest": latest_state(plan),
                   "build": str(any(a.kind == "BUILD" for a in plan.actions)).lower()},
                  args.github_output)
    write_summary(summarize(plan, f"{args.name} — {args.repository}"), args.summary)
    return finish(plan)


def cmd_simulate(args) -> int:
    data = json.loads(Path(args.state).read_text(encoding="utf-8"))
    plans = load_state(data)
    for plan in plans:
        print(plan.render())
        print()
    mutations = [action for plan in plans for action in plan.actions
                 if action.kind not in ("SKIP", "FAIL")]
    problems = [problem for plan in plans for problem in plan.problems]
    print(f"mutations: {len(mutations)}   problems: {len(problems)}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    commands = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    common.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))

    pypi = commands.add_parser("pypi", parents=[common])
    pypi.add_argument("--version", required=True)
    pypi.add_argument("--dist", required=True)
    pypi.add_argument("--project", default="comodor")
    pypi.add_argument("--index", default="https://pypi.org")
    pypi.add_argument("--stage", help="copy the files that still need uploading here")
    pypi.add_argument("--verify", action="store_true",
                      help="fail unless the version is complete")
    pypi.add_argument("--wait", type=float, default=0.0,
                      help="with --verify: seconds to wait for PyPI's listing to catch up")
    pypi.set_defaults(func=cmd_pypi)

    github = commands.add_parser("github", parents=[common])
    github.add_argument("--tag", required=True)
    github.add_argument("--version", required=True)
    github.add_argument("--dist", required=True)
    github.add_argument("--repo", required=True)
    github.add_argument("--apply", action="store_true")
    github.add_argument("--verify", action="store_true")
    github.set_defaults(func=cmd_github)

    image = commands.add_parser("image", parents=[common])
    image.add_argument("--name", default="GHCR")
    image.add_argument("--repository", required=True)
    image.add_argument("--version", required=True)
    image.add_argument("--source", default="",
                       help="a verified image to copy the version from instead of building")
    image.add_argument("--not-configured", action="store_true")
    image.add_argument("--apply", action="store_true",
                       help="copy the version and retag latest as planned; never builds")
    image.add_argument("--verify", action="store_true")
    image.set_defaults(func=cmd_image)

    simulate = commands.add_parser("simulate")
    simulate.add_argument("state")
    simulate.set_defaults(func=cmd_simulate)

    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):     # a runner's log is UTF-8; a console may not be
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
