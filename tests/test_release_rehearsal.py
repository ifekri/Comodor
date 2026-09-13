"""A release can be rehearsed as the version it will be, without its tag.

`workflow_dispatch` with dry run ticked used to rehearse nothing that
mattered: from a branch the build named itself `2.0.2.dev3+g…`, so the image
reconciler was never asked about `:2.0.1`, and the GitHub Release job was
skipped outright because the ref was not a tag. The run went green and said
nothing about what the release would find.

Now `target_version=2.0.1` makes the run build exactly 2.0.1 and ask every
destination what it holds for `v2.0.1` — with nothing written anywhere, and
with a branch never able to publish however the inputs are set. The rules
live in `decide_identity`; the workflow wires them through jobs, `if`
expressions, outputs and inputs, and those wires are what these tests
execute: the workflow files are read as they are, their expressions are
evaluated, their scripts are run under bash, and the tools they call are
recorded — the only thing not run is the network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "release-reconcile.py"
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"
IMAGE_YML = ROOT / ".github" / "workflows" / "image.yml"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("release_reconcile_rehearsal", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# the rules
# --------------------------------------------------------------------------- #


def test_a_target_version_on_a_branch_dry_run_is_a_rehearsal(tool):
    identity = tool.decide_identity("workflow_dispatch", "branch", "main", True, "2.0.1")
    assert identity == tool.Identity("rehearsal", "2.0.1", "v2.0.1", False)


def test_a_branch_dry_run_without_a_target_is_development(tool):
    identity = tool.decide_identity("workflow_dispatch", "branch", "main", True, "")
    assert identity == tool.Identity("development", "", "", False)


@pytest.mark.parametrize("bad", ["2.0.2.dev3+g1234abc", "2.0.1rc1", "v2.0.1", "2.0",
                                 "2.0.1.post1", "latest", "2.0.1 ", "1.2.3.4"])
def test_a_target_that_is_not_a_release_version_is_refused(tool, bad):
    with pytest.raises(tool.Refused, match="not a release version"):
        tool.decide_identity("workflow_dispatch", "branch", "main", True, bad)


def test_a_branch_never_publishes_whatever_the_inputs_say(tool):
    """The critical one: typing 2.0.1 into the box and unticking dry run
    must not publish a stable version from an untagged commit."""
    with pytest.raises(tool.Refused, match="anchored to a tag"):
        tool.decide_identity("workflow_dispatch", "branch", "main", False, "2.0.1")
    with pytest.raises(tool.Refused, match="anchored to a tag"):
        tool.decide_identity("workflow_dispatch", "branch", "main", False, "")


def test_a_pushed_release_tag_is_production(tool):
    assert tool.decide_identity("push", "tag", "v2.0.1", False) == \
        tool.Identity("production", "2.0.1", "v2.0.1", True)


@pytest.mark.parametrize("tag", ["v2.0.1rc1", "2.0.1", "v2.0", "vnext", "v2.0.1+local"])
def test_a_tag_that_is_not_a_release_tag_is_refused(tool, tag):
    with pytest.raises(tool.Refused, match="not a release tag"):
        tool.decide_identity("push", "tag", tag, False)


def test_a_run_by_hand_on_an_existing_tag_recovers_or_rehearses_it(tool):
    assert tool.decide_identity("workflow_dispatch", "tag", "v2.0.1", False) == \
        tool.Identity("recovery", "2.0.1", "v2.0.1", True)
    assert tool.decide_identity("workflow_dispatch", "tag", "v2.0.1", True) == \
        tool.Identity("rehearsal", "2.0.1", "v2.0.1", False)
    assert tool.decide_identity("workflow_dispatch", "tag", "v2.0.1", False, "2.0.1").publish
    with pytest.raises(tool.Refused, match="does not match the tag"):
        tool.decide_identity("workflow_dispatch", "tag", "v2.0.1", False, "2.0.2")


def test_no_other_event_or_ref_has_a_release_path(tool):
    with pytest.raises(tool.Refused):
        tool.decide_identity("push", "branch", "main", False)
    with pytest.raises(tool.Refused):
        tool.decide_identity("pull_request", "branch", "main", True)
    with pytest.raises(tool.Refused):
        tool.decide_identity("workflow_dispatch", "commit", "abc", True)


def test_deciding_touches_no_git_and_no_network(tool, monkeypatch):
    """A synthetic target is a name for a lookup, never a ref: the decision
    is a pure function and cannot create anything."""
    def forbidden(*args, **kwargs):
        raise AssertionError(f"decide_identity ran a process: {args} {kwargs}")

    monkeypatch.setattr(tool.subprocess, "run", forbidden)
    monkeypatch.setattr(tool.subprocess, "Popen", forbidden)
    identity = tool.decide_identity("workflow_dispatch", "branch", "main", True, "2.0.1")
    assert identity.tag == "v2.0.1"


# --------------------------------------------------------------------------- #
# a small GitHub Actions: the expressions the two workflows use
# --------------------------------------------------------------------------- #

TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>\d+(?:\.\d+)?)|"
                   r"(?P<op>&&|\|\||==|!=|[!(),])|(?P<id>[A-Za-z_][\w.\-]*))")


class Expressions:
    """`${{ … }}` as GitHub evaluates it, for the subset in these
    workflows: literals, dotted contexts, `!`, `==`, `!=`, `&&`, `||`,
    parentheses, `always()`, `format()`. `&&`/`||` return operands, not
    booleans, which is what makes `cond && 'x' || ''` work."""

    def __init__(self, contexts: dict):
        self.contexts = contexts

    # -- text with expressions in it ---------------------------------------- #

    def render(self, text):
        if not isinstance(text, str):
            return text
        if text.strip().startswith("${{") and text.strip().endswith("}}") \
                and text.count("${{") == 1:
            return self.evaluate(text.strip()[3:-2])
        return re.sub(r"\$\{\{(.*?)\}\}", lambda m: stringify(self.evaluate(m.group(1))),
                      text, flags=re.S)

    def condition(self, text) -> bool:
        if text is None:
            return True
        text = str(text)
        if text.strip().startswith("${{"):
            return truthy(self.render(text))
        return truthy(self.evaluate(text))

    # -- the parser ---------------------------------------------------------- #

    def evaluate(self, source: str):
        self.tokens = self.tokenize(source)
        self.index = 0
        value = self.parse_or()
        assert self.index == len(self.tokens), f"trailing tokens in {source!r}"
        return value

    @staticmethod
    def tokenize(source: str) -> list[tuple[str, str]]:
        tokens = []
        position = 0
        source = source.strip()
        while position < len(source):
            match = TOKEN.match(source, position)
            assert match and match.end() > position, f"cannot tokenize {source[position:]!r}"
            position = match.end()
            kind = match.lastgroup
            tokens.append((kind, match.group(kind)))
        return tokens

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else (None, None)

    def take(self, kind=None, value=None):
        token = self.peek()
        assert token[0] is not None, "unexpected end of expression"
        assert kind is None or token[0] == kind, f"expected {kind}, got {token}"
        assert value is None or token[1] == value, f"expected {value!r}, got {token}"
        self.index += 1
        return token[1]

    def parse_or(self):
        left = self.parse_and()
        while self.peek() == ("op", "||"):
            self.take()
            right = self.parse_and()
            left = left if truthy(left) else right
        return left

    def parse_and(self):
        left = self.parse_cmp()
        while self.peek() == ("op", "&&"):
            self.take()
            right = self.parse_cmp()
            left = right if truthy(left) else left
        return left

    def parse_cmp(self):
        left = self.parse_unary()
        while self.peek() in (("op", "=="), ("op", "!=")):
            operator = self.take()
            right = self.parse_unary()
            equal = loosely_equal(left, right)
            left = equal if operator == "==" else not equal
        return left

    def parse_unary(self):
        if self.peek() == ("op", "!"):
            self.take()
            return not truthy(self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        kind, value = self.peek()
        if kind == "op" and value == "(":
            self.take()
            inner = self.parse_or()
            self.take("op", ")")
            return inner
        if kind == "str":
            self.take()
            return value[1:-1].replace("''", "'")
        if kind == "num":
            self.take()
            return float(value) if "." in value else int(value)
        if kind == "id":
            self.take()
            if self.peek() == ("op", "("):
                self.take()
                args = []
                while self.peek() != ("op", ")"):
                    args.append(self.parse_or())
                    if self.peek() == ("op", ","):
                        self.take()
                self.take("op", ")")
                return self.call(value, args)
            if value == "true":
                return True
            if value == "false":
                return False
            if value == "null":
                return None
            return self.lookup(value)
        raise AssertionError(f"unexpected token {kind} {value!r}")

    def call(self, name, args):
        if name == "always":
            return True
        if name == "format":
            template, *values = args
            return re.sub(r"\{(\d+)\}", lambda m: stringify(values[int(m.group(1))]),
                          template)
        raise AssertionError(f"no function {name!r}")

    def lookup(self, path: str):
        node = self.contexts
        for segment in path.split("."):
            if isinstance(node, dict) and segment in node:
                node = node[segment]
            else:
                return ""            # an unset context value is empty
        return node


def truthy(value) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value != ""
    return bool(value)


def loosely_equal(left, right) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left.lower() == right.lower()
    if isinstance(left, bool) or isinstance(right, bool):
        return to_number(left) == to_number(right)
    return to_number(left) == to_number(right)


def to_number(value):
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except ValueError:
        return float("nan")


def stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# --------------------------------------------------------------------------- #
# a small GitHub Actions: jobs, steps, outputs, and the tools they call
# --------------------------------------------------------------------------- #

SHIM = """#!/bin/bash
# Stands in for python/python3 on the runner: the release tool's identity
# decision and the wheel-metadata check run for real (they are pure); every
# other invocation is recorded and answered with the outputs the workflow
# expects, so the wires can be followed without a network.
printf '%s\\n' "$*" >> "$SHIM_LOG"
case " $* " in
  *" identity "*) exec "$REAL_PYTHON" "$REPO_ROOT/$1" "${@:2}" ;;
  " - ") exec "$REAL_PYTHON" "$@" ;;
  *" -m build "*|*" -m build")
    printf '%s' "${SETUPTOOLS_SCM_PRETEND_VERSION:-}" > "$SHIM_DIR/pretend"
    exec "$REAL_PYTHON" "$SHIM_DIR/fake_build.py" \
      "${FAKE_BUILD_VERSION:-${SETUPTOOLS_SCM_PRETEND_VERSION:-$SOURCE_VERSION}}" ;;
  *"release-reconcile.py pypi "*)
    printf 'state=ABSENT\\nuploads=2\\n' >> "$GITHUB_OUTPUT" ;;
  *"release-reconcile.py github "*)
    printf 'found=ABSENT\\nstate=ABSENT\\nurl=\\n' >> "$GITHUB_OUTPUT" ;;
  *"release-reconcile.py image "*)
    case " $* " in
      *" --not-configured "*)
        printf 'state=NOT_CONFIGURED\\nlatest=NOT_CONFIGURED\\nbuild=false\\n' \\
          >> "$GITHUB_OUTPUT" ;;
      *) printf 'state=ABSENT\\nlatest=STALE\\nbuild=true\\n' >> "$GITHUB_OUTPUT" ;;
    esac ;;
esac
"""


class Runner:
    """Runs one workflow job the way the runner would, for the steps that
    can run here: `if` expressions are evaluated, `env` is rendered, `run`
    scripts are executed under bash with GITHUB_OUTPUT and the summary
    file, `uses` steps are recorded with their rendered inputs. Tool
    invocations go through the shim above and are logged."""

    def __init__(self, bash: str, workdir: Path, github: dict, inputs: dict,
                 secrets: dict | None = None):
        self.bash = bash
        self.workdir = workdir
        self.github = github
        self.inputs = inputs
        self.secrets = secrets or {}
        self.needs: dict[str, dict] = {}
        self.log: list[str] = []
        self.actions: list[tuple[str, str, dict]] = []      # (step, uses, with)
        self.summary = workdir / "summary.md"
        self.summary.write_text("", encoding="utf-8")
        self.shim_dir = workdir / "shim"
        self.shim_dir.mkdir(exist_ok=True)
        for name in ("python", "python3"):
            shim = self.shim_dir / name
            shim.write_text(SHIM, encoding="utf-8", newline="\n")
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.shim_log = workdir / "tools.log"
        self.shim_log.write_text("", encoding="utf-8")
        (self.shim_dir / "fake_build.py").write_text(FAKE_BUILD, encoding="utf-8", newline="\n")
        self.extra_env: dict[str, str] = {}

    def tool_calls(self) -> list[str]:
        return [line for line in self.shim_log.read_text(encoding="utf-8").splitlines()
                if line]

    def expressions(self, workflow_env: dict | None = None, steps: dict | None = None,
                    job_env: dict | None = None) -> Expressions:
        contexts = {"github": self.github, "inputs": self.inputs, "secrets": self.secrets,
                    "needs": self.needs, "steps": steps or {}, "env": {}}
        env = {}
        for source in (workflow_env or {}), (job_env or {}):
            for key, value in source.items():
                contexts["env"] = env
                env[key] = stringify(Expressions(contexts).render(value))
        contexts["env"] = env
        return Expressions(contexts)

    def run_job(self, workflow: dict, name: str, execute: set[str] = frozenset(),
                cwd: Path | None = None) -> dict:
        """Run job `name`; returns its result and outputs, and records them
        under `needs` for the jobs after it."""
        job = workflow["jobs"][name]
        expressions = self.expressions(workflow.get("env"))
        needs = job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        # As on the runner: without `always()` in its `if`, a job whose
        # needs did not all succeed is skipped, whatever its `if` says.
        upstream_ok = all(self.needs.get(need, {}).get("result") == "success"
                          for need in needs)
        runnable = upstream_ok or "always()" in str(job.get("if", ""))
        if not runnable or not expressions.condition(job.get("if")):
            self.needs[name] = {"result": "skipped", "outputs": {}}
            self.log.append(f"{name}: skipped")
            return self.needs[name]

        if "uses" in job:                       # a reusable workflow
            with_ = {key: expressions.render(value)
                     for key, value in (job.get("with") or {}).items()}
            self.log.append(f"{name}: calls {job['uses']} with {with_}")
            called_path = ROOT / job["uses"].removeprefix("./")
            called = yaml.safe_load(called_path.read_text(encoding="utf-8"))
            declared = called[True]["workflow_call"]["inputs"]
            defaults = {key: spec.get("default", "") for key, spec in declared.items()}
            (self.workdir / name).mkdir(exist_ok=True)
            inner = Runner(self.bash, self.workdir / name, self.github,
                           {**defaults, **with_}, self.secrets)
            inner.shim_log = self.shim_log
            inner.summary = self.summary
            result = inner.run_job(called, "build", execute, cwd)
            self.called = inner
            outputs = {}
            if result["result"] == "success":
                jobs_context = Expressions({"jobs": {"build": {"outputs": result["outputs"]}}})
                outputs = {key: stringify(jobs_context.render(spec["value"]))
                           for key, spec in called[True]["workflow_call"]["outputs"].items()}
            self.needs[name] = {"result": result["result"], "outputs": outputs}
            return self.needs[name]

        steps: dict[str, dict] = {}
        result = "success"
        for step in job["steps"]:
            label = step.get("name") or step.get("id") or step.get("uses", "?")
            expressions = self.expressions(workflow.get("env"), steps, job.get("env"))
            if not expressions.condition(step.get("if")):
                self.log.append(f"{name}/{label}: skipped")
                if "id" in step:
                    steps[step["id"]] = {"outputs": {}, "outcome": "skipped"}
                continue
            env = {key: stringify(expressions.render(value))
                   for key, value in (step.get("env") or {}).items()}
            if "uses" in step:
                with_ = {key: expressions.render(value)
                         for key, value in (step.get("with") or {}).items()}
                self.log.append(f"{name}/{label}: uses {step['uses']} {json.dumps(with_)}")
                self.actions.append((label, step["uses"], with_))
                if "id" in step:
                    steps[step["id"]] = {"outputs": {}, "outcome": "success", "with": with_}
                continue
            if label not in execute:
                self.log.append(f"{name}/{label}: not executed here")
                if "id" in step:
                    steps[step["id"]] = {"outputs": {}, "outcome": "success"}
                continue
            output_file = self.workdir / f"{name}-{step.get('id', 'step')}.out"
            output_file.write_text("", encoding="utf-8")
            script = expressions.render(step["run"])
            completed = subprocess.run(
                [self.bash, "-e", "-c", script],
                cwd=cwd or self.workdir, capture_output=True, text=True,
                env={**os.environ,
                     "PATH": f"{self.shim_dir}{os.pathsep}{os.environ['PATH']}",
                     "REAL_PYTHON": sys.executable, "SHIM_LOG": str(self.shim_log),
                     "REPO_ROOT": str(ROOT), "SOURCE_VERSION": SOURCE_VERSION,
                     **self.extra_env,
                     "SHIM_DIR": str(self.shim_dir),
                     "GITHUB_OUTPUT": str(output_file),
                     "GITHUB_STEP_SUMMARY": str(self.summary),
                     "GITHUB_REPOSITORY": self.github.get("repository", ""),
                     **{key: stringify(value) for key, value in
                        (job.get("env") or {}).items()},
                     **env})
            outputs = parse_outputs(output_file.read_text(encoding="utf-8"))
            self.log.append(f"{name}/{label}: exit {completed.returncode} {outputs}")
            if "id" in step:
                steps[step["id"]] = {"outputs": outputs,
                                     "outcome": "success" if completed.returncode == 0
                                     else "failure"}
            if completed.returncode != 0:
                result = "failure"
                self.failure = (label, completed.stdout + completed.stderr)
                break
        expressions = self.expressions(workflow.get("env"), steps, job.get("env"))
        outputs = {}
        if result == "success":
            outputs = {key: stringify(expressions.render(value))
                       for key, value in (job.get("outputs") or {}).items()}
        self.needs[name] = {"result": result, "outputs": outputs, "steps": steps}
        return self.needs[name]


def parse_outputs(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.endswith("<<EOF"):
            key = line[:-len("<<EOF")]
            block = []
            index += 1
            while lines[index] != "EOF":
                block.append(lines[index])
                index += 1
            parsed[key] = "\n".join(block)
        elif "=" in line:
            key, _, value = line.partition("=")
            parsed[key] = value
        index += 1
    return parsed


@pytest.fixture
def bash():
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not available")
    return found


def release() -> dict:
    return yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))


def make_wheel(folder: Path, version: str) -> Path:
    """A wheel as far as the workflow reads one: the filename and the
    METADATA inside."""
    folder.mkdir(parents=True, exist_ok=True)
    wheel = folder / f"comodor-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"comodor-{version}.dist-info/METADATA",
                         f"Metadata-Version: 2.4\nName: comodor\nVersion: {version}\n")
    (folder / f"comodor-{version}.tar.gz").write_bytes(b"sdist")
    return wheel


#: What hatch-vcs names a tree between releases when nothing overrides it.
SOURCE_VERSION = "2.0.2.dev3+g1234abc"

#: `python -m build`, as far as the workflow can tell: the wheel and sdist
#: named after the version the build was given, in `dist/`.
FAKE_BUILD = """import sys, zipfile
from pathlib import Path
version = sys.argv[1]
folder = Path("dist")
folder.mkdir(exist_ok=True)
with zipfile.ZipFile(folder / f"comodor-{version}-py3-none-any.whl", "w") as archive:
    archive.writestr(f"comodor-{version}.dist-info/METADATA",
                     f"Metadata-Version: 2.4\\nName: comodor\\nVersion: {version}\\n")
(folder / f"comodor-{version}.tar.gz").write_bytes(b"sdist")
"""


def dispatch(ref_type: str, ref_name: str, dry_run: bool, target: str,
             event: str = "workflow_dispatch") -> tuple[dict, dict]:
    github = {"event_name": event, "ref_type": ref_type, "ref_name": ref_name,
              "ref": f"refs/{'tags' if ref_type == 'tag' else 'heads'}/{ref_name}",
              "repository": "ifekri/Comodor", "repository_owner": "ifekri",
              "sha": "3659c34df29892c0aaa967554e87988dc8b10515", "token": "t"}
    inputs = {"dry_run": dry_run, "target_version": target} \
        if event == "workflow_dispatch" else {}
    return github, inputs


RELEASE_STEPS = {
    "Decide what this run releases", "Record the identity",
    "Build sdist and wheel", "Read version from built wheel",
    "A release must produce its own version", "Record build",
    "Compare the build with what PyPI holds",
    "PyPI holds the version this release page will describe",
    "Reconcile the GitHub Release", "Write the summary",
}
IMAGE_STEPS = {
    "Is Docker Hub configured", "Which version", "The wheel is the one asked for",
    "Plan GHCR", "Plan Docker Hub", "Which tags", "Name the image under test",
}
JOBS = ["identity", "gate", "build", "pypi-plan", "pypi-publish", "github-release",
        "image", "summary"]


def run_release(bash, tmp_path, github, inputs, secrets=None, wheel_version=None):
    """The whole workflow, job by job, with the wheel the build 'produces'
    named `wheel_version` (the identity's version unless told otherwise)."""
    workdir = tmp_path / "run"
    workdir.mkdir()
    runner = Runner(bash, workdir, github, inputs, secrets)
    if wheel_version:
        runner.extra_env["FAKE_BUILD_VERSION"] = wheel_version
    workflow = release()
    results = {}
    for name in JOBS:
        results[name] = runner.run_job(workflow, name, RELEASE_STEPS | IMAGE_STEPS, workdir)
    return runner, results


# --------------------------------------------------------------------------- #
# B, H, I, J, K — the rehearsal of v2.0.1 from main
# --------------------------------------------------------------------------- #


def test_a_rehearsal_of_v2_0_1_from_main_asks_every_destination_and_writes_nothing(
        bash, tmp_path):
    github, inputs = dispatch("branch", "main", True, "2.0.1")
    runner, results = run_release(bash, tmp_path, github, inputs,
                                  secrets={"DOCKERHUB_USERNAME": "ifekri", "DOCKERHUB_TOKEN": "x"})
    for name in JOBS:
        assert results[name]["result"] == ("skipped" if name == "pypi-publish" else "success"), \
            (name, results[name], getattr(runner, "failure", None), runner.log)

    identity = results["identity"]["outputs"]
    assert identity == {"mode": "rehearsal", "version": "2.0.1", "tag": "v2.0.1",
                        "publish": "false"}

    # 1. the build names itself 2.0.1 — through the supported override, and
    #    the version read back off the wheel and its METADATA agree
    assert (runner.workdir / "shim" / "pretend").read_text(encoding="utf-8") == "2.0.1"
    build = results["build"]["outputs"]
    assert build["version"] == "2.0.1" and build["wheel"] == "comodor-2.0.1-py3-none-any.whl"
    assert build["publish"] == "false" and build["tag"] == "v2.0.1"

    calls = runner.tool_calls()
    # 2. PyPI is asked about 2.0.1, with the built files, and nothing is uploaded
    pypi = [c for c in calls if "release-reconcile.py pypi" in c]
    assert pypi and all("--version 2.0.1" in c and "--dist dist/" in c for c in pypi)
    assert results["pypi-publish"]["result"] == "skipped"
    # 3. the GitHub Release job runs, asks about v2.0.1, and does not apply
    reconcile = [c for c in calls if "release-reconcile.py github" in c]
    assert len(reconcile) == 1
    assert "--tag v2.0.1 --version 2.0.1" in reconcile[0]
    assert "--apply" not in reconcile[0]
    # 4, 5. GHCR and Docker Hub are asked about :2.0.1 (and :latest)
    images = [c for c in calls if "release-reconcile.py image" in c]
    assert any("--repository ghcr.io/ifekri/comodor --version 2.0.1" in c for c in images)
    assert any("--repository ifekri/comodor --version 2.0.1" in c for c in images)
    assert not any("--apply" in c for c in images)
    # 6, 7. the local tag is Docker-safe, the image carries exactly 2.0.1
    image_steps = runner.called.needs["build"]["steps"]
    assert image_steps["tags"]["outputs"]["list"] == "ghcr.io/ifekri/comodor:dry-run"
    assert image_steps["wheel"]["outputs"]["install"] == "2.0.1"
    with_ = [w for _, uses, w in runner.called.actions if "build-push-action" in uses][0]
    assert with_["push"] is False and with_["load"] is True
    assert "COMODOR_VERSION=2.0.1" in with_["build-args"]
    assert "COMODOR_WHEEL=comodor-2.0.1-py3-none-any.whl" in with_["build-args"]
    assert with_["tags"] == "ghcr.io/ifekri/comodor:dry-run"
    # 8. every mutation flag is off
    assert build["publish"] == "false"
    image_log = " ".join(runner.called.log)
    assert "Publish GHCR: skipped" in image_log
    assert "Publish Docker Hub: skipped" in image_log
    assert not any("imagetools create" in c or "docker push" in c for c in calls)
    assert results["pypi-publish"]["result"] == "skipped"
    # 9. no tag is created: nothing in either workflow tags or pushes
    for path in (RELEASE_YML, IMAGE_YML):
        body = path.read_text(encoding="utf-8")
        assert not re.search(r"git (tag|push)\b", body), path
    assert not any("git " in c for c in calls)
    # 10. the summary names all four destinations, as a rehearsal
    summary = runner.summary.read_text(encoding="utf-8")
    assert "publication rehearsal of v2.0.1" in summary
    assert "DRY RUN" in summary and "ZERO PRODUCTION MUTATIONS" in summary
    rows = [line for line in summary.splitlines() if line.startswith("| ")]
    labels = [row.split("|")[1].strip() for row in rows]
    assert any(label.startswith("PyPI `comodor==2.0.1`") for label in labels)
    assert any(label.startswith("GitHub Release `v2.0.1`") for label in labels)
    assert any(label.startswith("GHCR `ghcr.io/ifekri/comodor:2.0.1`") for label in labels)
    assert any(label.startswith("Docker Hub `comodor:2.0.1`") for label in labels)
    assert "not asked" not in summary


def test_a_rehearsal_without_docker_hub_credentials_says_so(bash, tmp_path):
    github, inputs = dispatch("branch", "main", True, "2.0.1")
    runner, results = run_release(bash, tmp_path, github, inputs, secrets={})
    assert results["image"]["outputs"]["dockerhub_found"] == "NOT_CONFIGURED"
    summary = runner.summary.read_text(encoding="utf-8")
    assert "| Docker Hub `comodor:2.0.1` | NOT_CONFIGURED | skipped: no credentials |" in summary
    assert any("--not-configured" in c for c in runner.tool_calls())


# --------------------------------------------------------------------------- #
# A, L — a development dry run claims nothing it did not ask
# --------------------------------------------------------------------------- #


def test_a_development_dry_run_builds_the_source_and_asks_no_destination(bash, tmp_path):
    github, inputs = dispatch("branch", "main", True, "")
    runner, results = run_release(bash, tmp_path, github, inputs, secrets={})
    assert results["identity"]["outputs"]["mode"] == "development"
    assert (runner.workdir / "shim" / "pretend").read_text(encoding="utf-8") == ""
    assert results["build"]["outputs"]["version"] == SOURCE_VERSION
    assert results["github-release"]["result"] == "skipped"
    calls = runner.tool_calls()
    assert not any("release-reconcile.py github" in c for c in calls)
    assert not any("release-reconcile.py image" in c for c in calls), (
        "a development version names no registry tag; nothing is asked")
    assert results["image"]["result"] == "success"
    tags = runner.called.needs["build"]["steps"]["tags"]["outputs"]
    assert tags["list"] == "ghcr.io/ifekri/comodor:dry-run"
    summary = runner.summary.read_text(encoding="utf-8")
    assert "development dry run" in summary
    assert "| GitHub Release | not asked |" in summary
    assert f"| GHCR `ghcr.io/ifekri/comodor:{SOURCE_VERSION}` | not asked |" in summary
    assert f"| Docker Hub `comodor:{SOURCE_VERSION}` | not asked |" in summary


# --------------------------------------------------------------------------- #
# C, D — refused before anything is built
# --------------------------------------------------------------------------- #


def test_an_invalid_target_stops_the_run_at_the_identity(bash, tmp_path):
    github, inputs = dispatch("branch", "main", True, "2.0.2.dev3+g1234abc")
    runner, results = run_release(bash, tmp_path, github, inputs)
    assert results["identity"]["result"] == "failure"
    assert "not a release version" in runner.failure[1]
    assert results["gate"]["result"] == "skipped" and results["build"]["result"] == "skipped"
    assert runner.tool_calls() == [c for c in runner.tool_calls() if " identity " in c]


def test_a_target_with_dry_run_off_on_a_branch_fails_closed(bash, tmp_path):
    """Both gates: the workflow expression is false, and the identity
    refuses — so nothing after it runs, and nothing could publish."""
    github, inputs = dispatch("branch", "main", False, "2.0.1")
    runner, results = run_release(bash, tmp_path, github, inputs)
    assert results["identity"]["result"] == "failure"
    assert "anchored to a tag" in runner.failure[1]
    expressions = runner.expressions(release()["env"])
    assert expressions.render(release()["env"]["SHOULD_PUBLISH"]) is False
    for name in JOBS[1:]:
        assert results[name]["result"] == "skipped", name


def test_dry_run_off_on_a_branch_without_a_target_fails_closed_too(bash, tmp_path):
    github, inputs = dispatch("branch", "main", False, "")
    runner, results = run_release(bash, tmp_path, github, inputs)
    assert results["identity"]["result"] == "failure"
    assert results["build"]["result"] == "skipped"


# --------------------------------------------------------------------------- #
# E, F, G — the tag paths
# --------------------------------------------------------------------------- #


def test_a_pushed_tag_publishes_and_applies(bash, tmp_path):
    github, inputs = dispatch("tag", "v2.0.1", False, "", event="push")
    runner, results = run_release(bash, tmp_path, github, inputs,
                                  secrets={"DOCKERHUB_USERNAME": "ifekri", "DOCKERHUB_TOKEN": "x"})
    assert results["identity"]["outputs"] == {"mode": "production", "version": "2.0.1",
                                              "tag": "v2.0.1", "publish": "true"}
    assert results["build"]["outputs"]["publish"] == "true"
    assert (runner.workdir / "shim" / "pretend").read_text(encoding="utf-8") == "2.0.1"
    assert "gate/The tag must not be behind main: not executed here" in runner.log
    assert results["pypi-publish"]["result"] == "success"
    reconcile = [c for c in runner.tool_calls() if "release-reconcile.py github" in c][0]
    assert "--tag v2.0.1 --version 2.0.1" in reconcile and "--apply" in reconcile
    image = [line for line in runner.log if "calls ./.github/workflows/image.yml" in line][0]
    assert "'dry_run': False" in image and "'wheel': ''" in image
    image_steps = runner.called.needs["build"]["steps"]
    assert image_steps["tags"]["outputs"]["list"].splitlines() == [
        "ghcr.io/ifekri/comodor:2.0.1", "ifekri/comodor:2.0.1"]
    assert "Publish GHCR: not executed here" in " ".join(runner.called.log)
    with_ = [w for _, uses, w in runner.called.actions if "build-push-action" in uses][0]
    assert with_["push"] is True and "COMODOR_WHEEL=" + chr(10) in with_["build-args"]
    summary = runner.summary.read_text(encoding="utf-8")
    assert "production release of v2.0.1" in summary and "DRY RUN" not in summary


def test_a_tag_whose_build_names_another_version_fails_closed(bash, tmp_path):
    github, inputs = dispatch("tag", "v2.0.1", False, "", event="push")
    runner, results = run_release(bash, tmp_path, github, inputs, wheel_version="2.0.2")
    assert results["build"]["result"] == "failure"
    assert runner.failure[0] == "A release must produce its own version"
    assert "Release 2.0.1 produced package version 2.0.2" in runner.failure[1]
    for name in ("pypi-plan", "pypi-publish", "github-release", "image"):
        assert results[name]["result"] == "skipped", name


def test_a_run_by_hand_on_the_existing_tag_recovers_it(bash, tmp_path):
    github, inputs = dispatch("tag", "v2.0.1", False, "")
    runner, results = run_release(bash, tmp_path, github, inputs)
    assert results["identity"]["outputs"]["mode"] == "recovery"
    assert results["build"]["outputs"]["publish"] == "true"
    assert results["pypi-publish"]["result"] == "success"
    assert "recovery of v2.0.1" in runner.summary.read_text(encoding="utf-8")


def test_a_run_by_hand_on_the_existing_tag_with_dry_run_rehearses_it(bash, tmp_path):
    github, inputs = dispatch("tag", "v2.0.1", True, "")
    runner, results = run_release(bash, tmp_path, github, inputs)
    assert results["identity"]["outputs"]["mode"] == "rehearsal"
    assert results["build"]["outputs"]["publish"] == "false"
    assert results["pypi-publish"]["result"] == "skipped"
    reconcile = [c for c in runner.tool_calls() if "release-reconcile.py github" in c][0]
    assert "--apply" not in reconcile


# --------------------------------------------------------------------------- #
# the image installs the rehearsed wheel, and refuses the wrong one
# --------------------------------------------------------------------------- #


def test_the_rehearsed_image_installs_the_built_wheel():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG COMODOR_WHEEL=" in dockerfile
    assert "COPY Dockerfile dist*/ /tmp/dist/" in dockerfile, (
        "the copy must succeed with no dist/ at all — hence Dockerfile alongside")
    assert 'pip install --no-cache-dir "/tmp/dist/$COMODOR_WHEEL"' in dockerfile
    assert "!dist/*.whl" in (ROOT / ".dockerignore").read_text(encoding="utf-8")


def test_the_image_workflow_checks_the_wheel_it_is_handed(bash, tmp_path):
    image = yaml.safe_load(IMAGE_YML.read_text(encoding="utf-8"))
    step = [s for s in image["jobs"]["build"]["steps"] if s.get("id") == "wheel"][0]
    make_wheel(tmp_path / "dist", "2.0.1")
    for wheel, version, ok in (("comodor-2.0.1-py3-none-any.whl", "2.0.1", True),
                               ("comodor-2.0.1-py3-none-any.whl", "2.0.2", False),
                               ("comodor-9.9.9-py3-none-any.whl", "9.9.9", False)):
        output = tmp_path / "out"
        output.write_text("", encoding="utf-8")
        completed = subprocess.run([bash, "-c", step["run"]], cwd=tmp_path,
                                   env={**os.environ, "WHEEL": wheel, "VERSION": version,
                                        "GITHUB_OUTPUT": str(output)},
                                   capture_output=True, text=True)
        assert (completed.returncode == 0) is ok, (wheel, version, completed.stdout)
        if ok:
            assert output.read_text(encoding="utf-8") == f"install={version}\n"
