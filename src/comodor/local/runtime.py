"""Running a downloaded model, without the agent waiting on it.

The design question is where inference happens, and there is one professional
answer that everything credible converges on — Ollama, LM Studio, llama.cpp,
vLLM all do the same thing. **Inference runs in a separate process that speaks
an OpenAI-compatible HTTP API, and the model stays loaded in it between
requests.**

Three reasons, all of which are about the agent staying responsive.

*The GIL.* Generation is a long CPU-bound loop. Run it in this process and
every other thread — the interface repainting, the event bus, a tool finishing
— waits behind it. In another process it is another core's problem.

*Loading is expensive and must happen once.* Reading four gigabytes off disk
and laying it out takes seconds to tens of seconds. A design that loads per
request pays that every turn; a resident server pays it once and then answers
in milliseconds.

*A crash stays over there.* An out-of-memory kill on a 14B model on a 16 GB
machine ends the server, not the session — the agent sees a connection error,
says so, and the transcript survives.

The consequence for Comodor is that there is almost no new code. A local server
on `http://127.0.0.1:PORT/v1` is an OpenAI-compatible endpoint, so
:class:`OpenAICompatProvider` drives it unchanged. This module's whole job is
to make sure something is listening on that port.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..net import http
from .catalogue import Model

#: Names the llama.cpp server goes by. `llama-server` is current; `server` was
#: what the same binary was called before the rename, and people who built it
#: themselves a while ago still have that.
BINARIES = ("llama-server", "llama-server.exe", "server", "server.exe")

#: Where a binary tends to be when it was not put on PATH.
#:
#: The WinGet entry is here because `winget install llama.cpp` — which is what
#: Comodor itself suggests — unpacks into a package directory whose name
#: carries a hash, and puts a shim in `Links` only for the executables the
#: manifest declares. `llama-server.exe` was not one of them, so following our
#: own advice produced a binary this function could not see.
LIKELY = (
    Path.home() / ".local" / "bin",
    Path.home() / "llama.cpp" / "build" / "bin",
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
    Path("C:/Program Files/llama.cpp"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
)

#: Directories whose children are searched as well, one level down. WinGet puts
#: each package in its own folder under here and the folder name is not
#: predictable, so the parent is what can be named.
LIKELY_PARENTS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
)

#: How long to wait for a model to finish loading before giving up. A 14B model
#: off a spinning disk genuinely can take this long, and a timeout that fires
#: early looks exactly like a broken install.
LOAD_TIMEOUT = 300.0

#: How long the server may sit idle before it is shut down and its memory
#: returned. Long enough to survive somebody thinking between questions.
IDLE_FOR = 900.0


class RuntimeMissing(RuntimeError):
    """There is nothing on this machine that can run a GGUF."""


class RuntimeFailed(RuntimeError):
    """The server was started and did not come up."""


def find_binary(extra: Path | None = None) -> Path | None:
    """The llama.cpp server binary, wherever it is.

    PATH is checked the way a shell would, then the places people actually put
    it. A `curl | sh` install writes to `~/.local/bin`, which is not on PATH in
    a non-interactive shell — the same trap the project's own installer script
    documents.
    """
    if extra and extra.is_file() and os.access(extra, os.X_OK):
        return extra
    for name in BINARIES:
        found = shutil.which(name)
        if found:
            return Path(found)
    for folder in LIKELY:
        for name in BINARIES:
            candidate = folder / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate

    for parent in LIKELY_PARENTS:
        if not parent.is_dir():
            continue
        try:
            children = sorted(parent.iterdir())
        except OSError:
            continue
        for folder in children:
            if not folder.is_dir():
                continue
            for name in BINARIES:
                candidate = folder / name
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return candidate
    return None


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class Server:
    """One llama.cpp server, holding one model."""

    model: Model
    weights: Path
    binary: Path
    port: int
    process: subprocess.Popen
    started: float
    last_used: float

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def touch(self) -> None:
        self.last_used = time.monotonic()

    @property
    def idle_for(self) -> float:
        return time.monotonic() - self.last_used

    def stop(self, patience: float = 10.0) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=patience)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


class Runner:
    """Starts servers and keeps at most one alive.

    One, not several: each holds its whole model in memory, and two 7B models
    resident at once is how a 16 GB machine starts swapping. Asking for a
    different model stops the one that is running first.
    """

    def __init__(self, binary: Path | None = None) -> None:
        self._binary = binary
        self._server: Server | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> Server | None:
        with self._lock:
            if self._server is not None and not self._server.alive:
                self._server = None
            return self._server

    def serve(self, model: Model, weights: Path, *, context: int | None = None,
              threads: int | None = None, gpu_layers: int = -1) -> Server:
        """Make sure this model is loaded and answering, and say where."""
        with self._lock:
            current = self._server
            if current is not None and current.alive:
                if current.weights == weights:
                    current.touch()
                    return current
                # A different model. Its memory has to go back before the next
                # one asks for its own.
                current.stop()
                self._server = None

            binary = self._binary or find_binary()
            if binary is None:
                raise RuntimeMissing(
                    "no llama.cpp server found. Install one and make sure "
                    "`llama-server` is on PATH — `brew install llama.cpp`, or a "
                    "build from github.com/ggml-org/llama.cpp. Comodor will "
                    "also use Ollama or LM Studio if either is already running.")
            if not weights.is_file():
                raise RuntimeFailed(f"the weights are not at {weights}")

            port = free_port()
            command = [
                str(binary),
                "--model", str(weights),
                "--host", "127.0.0.1",
                "--port", str(port),
                # Offload everything the graphics card will take. On a machine
                # with no usable GPU llama.cpp ignores this rather than failing,
                # so it does not need to be conditional.
                "--n-gpu-layers", str(gpu_layers),
                # Answer while generating rather than in one lump at the end.
                "--flash-attn", "auto",
            ]
            if context:
                command += ["--ctx-size", str(context)]
            elif model.context:
                command += ["--ctx-size", str(model.context)]
            if threads:
                command += ["--threads", str(threads)]

            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                # Its own group, so a Ctrl-C in the terminal interrupts the
                # agent rather than killing the model out from under it.
                start_new_session=(os.name != "nt"),
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                               if os.name == "nt" else 0),
            )

            now = time.monotonic()
            server = Server(model=model, weights=weights, binary=binary,
                            port=port, process=process, started=now,
                            last_used=now)
            try:
                _wait_until_ready(server)
            except Exception:
                server.stop()
                raise
            self._server = server
            return server

    def stop(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.stop()
                self._server = None

    def stop_if_idle(self, after: float = IDLE_FOR) -> bool:
        """Give the memory back when nobody has asked anything for a while."""
        with self._lock:
            server = self._server
            if server is None or not server.alive:
                self._server = None
                return False
            if server.idle_for < after:
                return False
            server.stop()
            self._server = None
            return True


def _wait_until_ready(server: Server, timeout: float = LOAD_TIMEOUT) -> None:
    """Block until the server answers, or explain why it never will."""
    deadline = time.monotonic() + timeout
    health = f"http://127.0.0.1:{server.port}/health"

    while time.monotonic() < deadline:
        if not server.alive:
            raise RuntimeFailed(_why_it_died(server))
        try:
            response = http.get(health, timeout=(2.0, 5.0))
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.4)

    raise RuntimeFailed(
        f"{server.model.name} did not finish loading within "
        f"{int(timeout)}s. It may be too large for this machine.")


def _why_it_died(server: Server) -> str:
    """The server's own last words, rather than a return code.

    llama.cpp says something useful on the way out — the file is not a GGUF,
    the allocation failed, the quantisation is unsupported — and a caller shown
    only "exited 1" has nothing to act on.
    """
    said = ""
    try:
        if server.process.stderr is not None:
            said = server.process.stderr.read(4000).decode("utf-8", "replace")
    except Exception:
        pass

    lines = [line for line in said.splitlines() if line.strip()]
    tail = lines[-1] if lines else ""
    code = server.process.poll()

    if "out of memory" in said.lower() or "failed to allocate" in said.lower():
        needs = (f" It wants about {server.model.needs_ram_gb:g} GB."
                 if server.model.needs_ram_gb else "")
        return (f"{server.model.name} ran out of memory while loading.{needs} "
                f"Try a smaller model.")
    if "unknown model architecture" in said.lower() or "not a gguf" in said.lower():
        return (f"{server.weights.name} is not a model this llama.cpp can read. "
                f"The binary may be older than the file.")
    if tail:
        return f"the model server stopped: {tail}"
    return f"the model server exited with status {code}"
