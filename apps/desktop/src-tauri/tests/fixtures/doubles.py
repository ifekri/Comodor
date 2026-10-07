"""Core doubles for the desktop's tests: Cores that misbehave on purpose.

Test-only. Each speaks just enough protocol v2 to reach the misbehaviour it
exists for, and nothing here touches a network.

    python doubles.py <behaviour> core --stdio

The application appends `core --stdio`; it is accepted and ignored.

Behaviours:

- `exit-immediately` — writes a reason on stderr and exits before the handshake.
- `bad-line` — completes the handshake, then writes one line that is not a
  protocol message on stdout.
- `version-mismatch` — answers `client.hello` claiming protocol version 3.
- `version-refused` — answers `client.hello` with `unsupported_version`, naming
  `supported: [3]`.
- `ignore-stop` — completes the handshake, starts one child process, then
  ignores `shutdown` and stdin EOF; only a forced stop ends it and its child.
- `stderr-flood` — writes more than 200 lines and 64 KiB to stderr, then
  completes the handshake and serves like a real Core.
- `crash-on-send` — a real scripted Core that exits abruptly on the first
  model call of the first `session.send`.
- `sequenced` — one behaviour per launch, from the JSON list in
  `COMODOR_TEST_SEQUENCE` (`crash-on-send`, `complete-turn`, or
  `scripted:<scenario>`), advancing a counter kept beside that file. The
  counter is replaced atomically, so each launch takes the next entry exactly
  once, in order.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTOCOL = 2


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def read_hello() -> dict:
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    return json.loads(line)


def answer_hello(request: dict, version: int = PROTOCOL) -> None:
    send({"version": PROTOCOL, "type": "response", "id": request.get("id"),
          "result": {"protocol_version": version,
                     "core": {"name": "comodor-core", "version": "double"},
                     "capabilities": ["streaming", "questions", "permissions"]}})


def scripted(scenario: str) -> None:
    """Become the scripted Core for this scenario, in this process."""
    argv = [sys.executable, str(HERE / "scripted_core.py"), scenario, "core", "--stdio"]
    if sys.platform == "win32":
        # No exec on Windows that keeps the same process; run it as a child on
        # the same standard streams and leave with its status. The child is
        # inside the application's job object like this process.
        sys.exit(subprocess.call(argv))
    os.execv(sys.executable, argv)


def next_in_sequence() -> str:
    sequence_path = Path(os.environ["COMODOR_TEST_SEQUENCE"])
    entries = json.loads(sequence_path.read_text(encoding="utf-8"))
    counter = sequence_path.with_suffix(".counter")
    at = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    if at >= len(entries):
        raise SystemExit(f"sequence exhausted after {len(entries)} launches")
    staging = counter.with_suffix(".counter.tmp")
    staging.write_text(str(at + 1), encoding="utf-8")
    os.replace(staging, counter)
    return str(entries[at])


def main() -> None:
    behaviour = sys.argv[1] if len(sys.argv) > 1 else ""
    if behaviour == "sequenced":
        behaviour = next_in_sequence()
        print(f"doubles: sequenced launch is {behaviour}", file=sys.stderr, flush=True)

    if behaviour == "complete-turn":
        scripted("complete-turn")
    elif behaviour.startswith("scripted:"):
        scripted(behaviour.split(":", 1)[1])
    elif behaviour == "crash-on-send":
        scripted("crash-on-send")
    elif behaviour == "exit-immediately":
        print("doubles: this Core refuses to start", file=sys.stderr, flush=True)
        sys.exit(3)
    elif behaviour == "bad-line":
        answer_hello(read_hello())
        sys.stdout.write("this is not a protocol message\n")
        sys.stdout.flush()
        threading.Event().wait()
    elif behaviour == "version-mismatch":
        answer_hello(read_hello(), version=3)
        threading.Event().wait()
    elif behaviour == "version-refused":
        request = read_hello()
        send({"version": PROTOCOL, "type": "error", "id": request.get("id"),
              "error": {"code": "unsupported_version",
                        "message": "this core speaks protocol 3",
                        "data": {"supported": [3]}}})
        threading.Event().wait()
    elif behaviour == "ignore-stop":
        answer_hello(read_hello())
        child = subprocess.Popen(
            [sys.executable, "-c", "import threading; threading.Event().wait()"])
        pid_file = os.environ.get("COMODOR_TEST_CHILD_PID_FILE")
        if pid_file:
            Path(pid_file).write_text(str(child.pid), encoding="utf-8")
        # Every further line, `shutdown` included, is read and ignored; EOF is
        # ignored too. Only a forced stop ends this process and its child.
        while sys.stdin.readline():
            pass
        threading.Event().wait()
    elif behaviour == "stderr-flood":
        for n in range(400):
            sys.stderr.write(f"doubles: diagnostic line {n:04d} " + "x" * 200 + "\n")
        sys.stderr.flush()
        scripted("echo")
    else:
        raise SystemExit(f"doubles: unknown behaviour {behaviour!r}")


if __name__ == "__main__":
    main()
