"""Where a command runs: this machine, a container, or another box.

`run_shell` ran on the host and nowhere else. That is the right default and
stays it, but two jobs have always asked for a choice:

* "prove this works in a clean container" — the host has cached wheels,
  global state and a shell history the container does not;
* "work on the box I ssh into" — a project that lives on a server.

So the shell tool asks a backend, and the backend is three adapters behind
one interface. The interface is the one `RunShell.run` already has: give it a
command and a working directory, get streamed output and an exit code.

Two things the adapters do not get to change:

* **The deny list applies everywhere.** Depth of defence is a habit, not an
  ornament: `rm -rf /` inside a container is still refused before the
  container is built, because the container's boundary is not a reason to
  weaken the outer one.
* **A hardened container is the only container that auto-approves.** If
  `docker_harden` is off, the request is not refused — it is shown to the
  human like any DANGEROUS call, with the difference said plainly.

SSH uses TOFU (trust on first use): the first connection records the host
key's fingerprint, later ones must match, and a changed fingerprint is
refused loudly rather than re-trusted. BatchMode keeps a dead password
prompt from hanging the turn; a connection that cannot be made fails
quickly and says so.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

#: Flags every hardened container gets. Copied from the compose file that
#: ships this project, which is the same judgement applied to the agent
#: itself: give it nothing it does not need.
HARDEN_FLAGS: tuple[str, ...] = (
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges:true",
    "--pids-limit=256",
    "--read-only",
    "--tmpfs=/tmp:rw,size=64m,mode=1777",
    "--tmpfs=/run:rw,size=16m,mode=755",
)

#: Where the host's docker socket is mounted when a command wants docker
#: inside the container. Default: nowhere. The socket is the host's root;
#: handing it to a container defeats every other flag above.
#: (Not mounted. The comment is the policy.)


@dataclass
class CommandResult:
    """What one command produced, in the shape `RunShell` already speaks."""

    exit_code: int | None = None
    output: str = ""
    elapsed: float = 0.0
    cancelled: bool = False
    timed_out: bool = False


class HostBackend:
    """The machine itself, which is what `RunShell` did before this module."""

    def __init__(self, kill_tree: Callable[[subprocess.Popen], None]) -> None:
        self._kill_tree = kill_tree

    def description(self) -> str:
        return "this machine"

    def run(self, command: str, cwd: Path, timeout: float, cancel: Any,
            on_output: Callable[[str], None]) -> CommandResult:
        popen_kwargs: dict[str, Any] = {
            "cwd": str(cwd), "shell": True,
            "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
            "text": True, "encoding": "utf-8", "errors": "replace",
            "bufsize": 1,
        }
        if subprocess.os.name != "nt":
            popen_kwargs["start_new_session"] = True   # so we can kill the group
        started = time.monotonic()
        try:
            process = subprocess.Popen(command, **popen_kwargs)
        except OSError as exc:
            return CommandResult(exit_code=None, output=str(exc), timed_out=False)

        chunks: list[str] = []
        finished = threading.Event()

        def collect() -> None:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    chunks.append(line)
                    on_output(line.rstrip("\n"))
            except Exception:
                pass
            finally:
                finished.set()

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        cancelled = timed_out = False
        while True:
            if process.poll() is not None:
                break
            if cancel is not None and cancel.cancelled:
                cancelled = True
                self._kill_tree(process)
                break
            if time.monotonic() - started > timeout:
                timed_out = True
                self._kill_tree(process)
                break
            time.sleep(0.05)
        finished.wait(timeout=2.0)
        reader.join(timeout=1.0)
        return CommandResult(
            exit_code=process.poll(), output="".join(chunks),
            elapsed=time.monotonic() - started,
            cancelled=cancelled, timed_out=timed_out)


class DockerBackend:
    """A `docker run --rm` per command, hardened unless told not to be.

    One container per command, not one long-lived one: a command that leaves
    a daemon running must not outlive its call, and `--rm` is what makes that
    true without bookkeeping. The project is mounted read-only unless the
    user chose read-write.
    """

    def __init__(self, settings: Any, project: Path) -> None:
        self.settings = settings
        self.project = project

    def description(self) -> str:
        image = getattr(self.settings, "docker_image", "")
        return f"docker ({image})"

    def command_for(self, command: str, cwd: Path, timeout: float) -> list[str]:
        """The docker invocation, flags and all. Everything visible, so a
        test can assert the hardening is present on every call."""
        argv = ["docker", "run", "--rm"]
        if getattr(self.settings, "docker_harden", True):
            argv.extend(HARDEN_FLAGS)
        mount = getattr(self.settings, "docker_mount", "ro")
        if mount:
            argv.append(f"-v={self.project}:/workspace:{mount}")
        inside = cwd.relative_to(self.project) \
            if cwd.is_relative_to(self.project) else Path(".")
        workdir = f"/workspace/{inside}"
        argv.extend(["--workdir", workdir, "-e", "HOME=/tmp"])
        argv.append(getattr(self.settings, "docker_image", "python:3.13-slim"))
        argv.append("timeout")
        argv.append(f"{max(1.0, timeout):.0f}")
        argv.extend(["sh", "-c", command])
        return argv

    def run(self, command: str, cwd: Path, timeout: float, cancel: Any,
            on_output: Callable[[str], None]) -> CommandResult:
        argv = self.command_for(command, cwd, timeout)
        started = time.monotonic()
        try:
            done = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=max(2.0, timeout + 15.0),
            )
        except FileNotFoundError:
            return CommandResult(
                exit_code=None,
                output="docker is not installed, or not on this PATH — "
                       "set shell.backend = host to run on this machine",
                elapsed=time.monotonic() - started)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                exit_code=None,
                output=(exc.stdout or "") + (exc.stderr or ""),
                elapsed=time.monotonic() - started, timed_out=True)
        if cancel is not None and cancel.cancelled:
            return CommandResult(exit_code=done.returncode,
                                 output=(done.stdout or "") + (done.stderr or ""),
                                 elapsed=time.monotonic() - started,
                                 cancelled=True)
        return CommandResult(
            exit_code=done.returncode,
            output=(done.stdout or "") + (done.stderr or ""),
            elapsed=time.monotonic() - started)


class SSHBackend:
    """A command on another machine, with the host key pinned on first use.

    TOFU is stored in the project's own directory rather than the user's
    ~/.ssh/known_hosts, for the same reason approvals are session-scoped:
    trusting a new machine is a per-project decision.
    """

    def __init__(self, settings: Any, project: Path, fingerprints: Path) -> None:
        self.settings = settings
        self.fingerprints = fingerprints

    def description(self) -> str:
        return (f"ssh {getattr(self.settings, 'ssh_user', '')}"
                f"@{getattr(self.settings, 'ssh_host', '')}")

    # -- the known host ---------------------------------------------------- #

    def _recorded(self) -> str:
        try:
            return self.fingerprints.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _record(self, fingerprint: str) -> None:
        self.fingerprints.parent.mkdir(parents=True, exist_ok=True)
        self.fingerprints.write_text(fingerprint + "\n", encoding="utf-8")

    def _base_argv(self, command: str) -> list[str]:
        argv = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.fingerprints}",
        ]
        key = getattr(self.settings, "ssh_key_path", "")
        if key:
            argv.extend(["-i", str(Path(key).expanduser())])
        port = int(getattr(self.settings, "ssh_port", 22) or 22)
        if port != 22:
            argv.extend(["-p", str(port)])
        host = f"{getattr(self.settings, 'ssh_user', '')}@" \
            f"{getattr(self.settings, 'ssh_host', '')}"
        argv.append(host)
        argv.append(command)
        return argv

    def run(self, command: str, cwd: Path, timeout: float, cancel: Any,
            on_output: Callable[[str], None]) -> CommandResult:
        started = time.monotonic()
        try:
            done = subprocess.run(
                self._base_argv(command),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=max(2.0, timeout),
            )
        except FileNotFoundError:
            return CommandResult(
                exit_code=None,
                output="ssh is not on this PATH — set shell.backend = host",
                elapsed=time.monotonic() - started)
        except subprocess.TimeoutExpired:
            return CommandResult(
                exit_code=None, output="the remote command did not finish in "
                                       f"{timeout:.0f}s and was killed",
                elapsed=time.monotonic() - started, timed_out=True)
        output = ((done.stdout or "") + (done.stderr or "")).strip()
        code = done.returncode
        if code == 255:
            # ssh's own failure code: a refused key, an unknown host, a dead
            # network. The stderr already says which.
            return CommandResult(
                exit_code=None, output=output,
                elapsed=time.monotonic() - started)
        return CommandResult(exit_code=code, output=output,
                             elapsed=time.monotonic() - started)


def build(settings: Any, project: Path) -> Any:
    """The backend `shell.backend` names, or None for the host (which
    `RunShell` runs itself — the host path here exists for tests and for a
    future dispatcher that owns the loop)."""
    name = (getattr(settings, "backend", "host") or "host").strip().lower()
    if name == "docker":
        return DockerBackend(settings, project)
    if name == "ssh":
        fingerprints = project / ".comodor" / "ssh_host_fingerprint"
        return SSHBackend(settings, project, fingerprints)
    return HostBackend(_host_kill_tree)


def _host_kill_tree(process: subprocess.Popen) -> None:
    """Terminate a process and its children, by platform."""
    import os

    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(process.pid), 9)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
