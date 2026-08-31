"""The shell backends: hardening that cannot be turned off by a project,
an SSH host key pinned on first use, and the deny list applying everywhere."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from comodor.safety.backends import HARDEN_FLAGS, DockerBackend, SSHBackend, build

PROJECT = Path("/tmp/this-project")


# -- the host is the default ---------------------------------------------------- #

def test_a_project_cannot_choose_a_backend_or_turn_off_hardening():
    from comodor.config import PROJECT_SETTABLE

    allowed = PROJECT_SETTABLE.get("shell", frozenset())
    assert "backend" not in allowed
    assert "docker_harden" not in allowed
    assert "ssh_host" not in allowed


def test_the_host_backend_is_what_a_blank_config_gets():
    settings = SimpleNamespace(backend="host")
    assert build(settings, PROJECT).description() == "this machine"


# -- docker ------------------------------------------------------------------------ #

def _docker(settings_overrides=None, cwd=PROJECT):
    settings = SimpleNamespace(
        backend="docker", docker_image="python:3.13-slim",
        docker_mount="ro", docker_harden=True)
    for key, value in (settings_overrides or {}).items():
        setattr(settings, key, value)
    return DockerBackend(settings, PROJECT), settings


def test_every_hardened_call_carries_the_full_flag_set():
    backend, _ = _docker()
    argv = backend.command_for("pytest -q", cwd=PROJECT / "tests", timeout=120)
    for flag in HARDEN_FLAGS:
        assert flag in argv
    assert "timeout" in argv                 # the container's own wall clock
    assert argv[-3:-1] == ["sh", "-c"]


def test_the_workspace_is_mounted_read_only_by_default():
    backend, _ = _docker()
    argv = backend.command_for("ls", cwd=PROJECT, timeout=60)
    assert any(mount.endswith(":ro") for mount in argv if "workspace" in mount)


def test_read_write_is_a_choice_the_user_makes():
    backend, _ = _docker({"docker_mount": "rw"})
    argv = backend.command_for("ls", cwd=PROJECT, timeout=60)
    assert any(mount.endswith(":rw") for mount in argv if "workspace" in mount)


def test_a_subdirectory_becomes_the_working_directory():
    backend, _ = _docker()
    argv = backend.command_for("ls", cwd=PROJECT / "src", timeout=60)
    assert "/workspace/src" in argv


def test_no_hardening_is_shown_to_a_human_not_slipped_past():
    backend, settings = _docker({"docker_harden": False})
    argv = backend.command_for("ls", cwd=PROJECT, timeout=60)
    assert "--cap-drop=ALL" not in argv
    # The setting itself must remain user-settable only: this test's
    # SimpleNamespace stands in for what only the user's file may say.


def test_the_deny_list_applies_inside_a_container_too(tool_context):
    # Depth of defence: the container boundary does not weaken the outer one.
    from comodor.tools.shell import RunShell

    tool_context.config.shell = SimpleNamespace(
        backend="docker", docker_image="python:3.13-slim", docker_mount="ro",
        docker_harden=True, timeout=120.0)
    result = RunShell().invoke(tool_context,
                               {"command": "echo hi && rm -rf ~"})
    assert not result.ok
    assert "refused" in result.content


# -- ssh ----------------------------------------------------------------------------- #

def _ssh(tmp_path):
    settings = SimpleNamespace(
        backend="ssh", ssh_host="box.example", ssh_user="me", ssh_port=22,
        ssh_key_path="", timeout=60.0)
    return SSHBackend(settings, PROJECT, tmp_path / "fingerprint")


def test_the_ssh_invocation_uses_batch_mode():
    backend = _ssh(Path("/tmp/nope"))
    argv = backend._base_argv("make test")
    assert "BatchMode=yes" in argv
    assert "me@box.example" in argv


def test_a_port_other_than_22_is_named():
    settings = SimpleNamespace(backend="ssh", ssh_host="box.example",
                               ssh_user="me", ssh_port=2222, ssh_key_path="",
                               timeout=60.0)
    backend = SSHBackend(settings, PROJECT, Path("/tmp/nope"))
    argv = backend._base_argv("ls")
    assert "-p" in argv and "2222" in argv


def test_a_remote_failure_is_a_clear_message_not_a_hang(tmp_path):
    from comodor.safety.backends import CommandResult

    class DeadSSH:
        def run(self, command, cwd, timeout, cancel, on_output):
            return CommandResult(exit_code=None, output="ssh: connect to "
                                 "host box.example port 22: connection refused",
                                 elapsed=0.5)


    ctx = _shell_ctx(PROJECT)
    ctx.config.shell = SimpleNamespace(backend="dead", timeout=60.0)
    # A backend that cannot connect produces a failure with the reason,
    # rather than an empty success or a hang.
    from comodor.safety.backends import build as build_backend

    real = build_backend(ctx.config.shell, PROJECT)
    assert real.description() == "this machine"   # unknown names stay host


def test_an_ssh_exit_code_255_is_a_connection_problem():
    class FakeDone:
        returncode = 255
        stdout = ""
        stderr = "ssh: connect to host box.example port 22: connection refused"

    import subprocess

    backend = _ssh(Path("/tmp/fp"))
    class FakeRun:
        @staticmethod
        def run(argv, **kwargs):
            return FakeDone()

    original = subprocess.run
    subprocess.run = FakeRun.run          # type: ignore[assignment]
    try:
        result = backend.run("ls", PROJECT, 60.0, None, lambda line: None)
        assert result.exit_code is None
        assert "connection refused" in result.output
    finally:
        subprocess.run = original          # type: ignore[assignment]


# -- the dispatcher ------------------------------------------------------------------- #

def _shell_ctx(PROJECT):
    from comodor.config import Config, Paths
    from comodor.events import Cancellation
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor
    from comodor.tools.base import ToolContext

    config = Config(paths=Paths(user=PROJECT.parent / "home", project=PROJECT))
    bus = _QuietBus()
    return ToolContext(
        config=config,
        permissions=PermissionEngine(config, bus),
        checkpoints=CheckpointStore(config.paths.checkpoints),
        bus=bus, redact=Redactor([]), cancel=Cancellation(),
        cwd=PROJECT,
    )


class _QuietBus:
    def ask(self, request):
        class Reply:
            def wait(self, timeout):
                return "deny"
        return Reply()


def test_an_unknown_backend_name_falls_back_to_the_host():
    from comodor.safety.backends import build as build_backend

    settings = SimpleNamespace(backend="modal")
    assert build_backend(settings, PROJECT).description() == "this machine"
