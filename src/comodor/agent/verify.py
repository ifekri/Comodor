"""Running the project's own check when the agent says it is finished.

The system prompt asks the model to run the tests after a change. Asking is not
getting: the benchmark found a task reported as complete by a model that had
run nothing, and that is the ordinary case rather than the exceptional one.

`agent.verify_command` closes it. Whatever the project's own check is — `pytest
-q`, `npm test`, `cargo check`, `make` — it runs once at the end of a turn that
changed a file, and a failure is handed back with one turn to fix it. "Done"
then means "done, and the project still works", which is a different claim and
the one people actually want.

Four rules, and each is a way this could be worse than nothing.

*Only when something changed.* A turn that read files and answered a question
has nothing to verify, and running a suite for it is a minute of somebody's
time for no information.

*Once, then hand it back.* Not a loop. A model that cannot fix the failure on
its first try will not fix it on its fifth, and the user is better off being
told plainly than watching it spend their money.

*Bounded.* A command with no ceiling can hang a turn forever, which is worse
than a failing check.

*It never becomes the error.* If the command cannot be run at all — not found,
no shell, no permission — that is said once and the turn ends as it would have.
A verifier that turns a finished task into a failure is a verifier people
switch off.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: How long the project's own check may take before it is given up on. Long
#: enough for a real suite, short enough that a hung command is reported rather
#: than waited on.
PATIENCE = 600.0

#: How much of the output travels back to the model. A failing suite can print
#: megabytes, and the useful part is at the end.
MOST = 6000


@dataclass(frozen=True)
class Outcome:
    """What the project's own check said."""

    ran: bool
    passed: bool
    output: str
    #: Set when the command could not be run at all, as opposed to failing.
    unusable: str = ""

def _end_the_group(child: "subprocess.Popen") -> None:
    """Kill the check and everything it started. Never raises.

    `pytest` starting workers, `npm` starting a bundler: killing only the
    shell leaves those behind, running against the user's project after the
    turn that started them has been abandoned.
    """
    try:
        if hasattr(os, "killpg"):
            group = os.getpgid(child.pid)
            # Only a group the check has to itself. `start_new_session` above
            # gives it one, but if that ever stops happening the child shares
            # ours, and killing that group would end the agent along with the
            # command it was running. The signal cannot be taken back, so the
            # condition is checked rather than trusted.
            if group != os.getpgid(0):
                os.killpg(group, signal.SIGKILL)
                return
    except (OSError, AttributeError, ProcessLookupError):
        pass
    try:
        # Windows: taskkill walks the tree, which Popen.kill does not.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(child.pid)],
                       capture_output=True, timeout=10)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        child.kill()
    except OSError:
        pass


def run(command: str, cwd: Path, patience: float = PATIENCE) -> Outcome:
    """Run the project's check and say what happened. Never raises."""
    if not command.strip():
        return Outcome(ran=False, passed=True, output="")

    environment = dict(os.environ)
    # A check that shells out to the agent would be a loop with a bill on it.
    environment["COMODOR_VERIFYING"] = "1"

    # `shell=True` means the process started here is a shell, and the check is
    # its child. Killing the shell on a timeout leaves that child running and
    # holding the pipes open, so the read below goes on blocking — `patience`
    # was a ceiling on nothing, and the message said "no result within 2s"
    # after waiting twenty. The whole group has to go, which needs the platform
    # to have been told to make one.
    # Written out rather than gathered into a dict and splatted: this argument
    # is the difference between ending the check and ending the agent, and it
    # should be readable as such at the call — by a person, and by anything
    # checking that every `Popen` beside a `killpg` has one.
    try:
        child = subprocess.Popen(
            command, shell=True, cwd=str(cwd), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
            start_new_session=(os.name != "nt"),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                           if os.name == "nt" else 0))
    except (OSError, ValueError) as problem:
        return Outcome(ran=False, passed=True, output="",
                       unusable=f"{type(problem).__name__}: {problem}")

    try:
        finished_out, finished_err = child.communicate(timeout=patience)
    except subprocess.TimeoutExpired:
        _end_the_group(child)
        # Drained after the group is gone, so nothing is still writing into a
        # pipe nobody will read. It cannot block now: every writer is dead.
        try:
            child.communicate(timeout=10)
        except Exception:
            pass
        return Outcome(ran=True, passed=False,
                       output=f"(no result within {patience:.0f}s)")
    except (OSError, ValueError) as problem:
        _end_the_group(child)
        return Outcome(ran=False, passed=True, output="",
                       unusable=f"{type(problem).__name__}: {problem}")

    finished = subprocess.CompletedProcess(
        command, child.returncode, finished_out, finished_err)
    output = ((finished.stdout or "") + (finished.stderr or "")).strip()
    if len(output) > MOST:
        output = "…\n" + output[-MOST:]
    return Outcome(ran=True, passed=finished.returncode == 0, output=output)


def as_correction(command: str, outcome: Outcome) -> str:
    """What the model is told when the project's check fails.

    Phrased as a fact and a request, not as an accusation. The model is not
    being told it lied — it is being shown the output of something it did not
    run, which is exactly the information it was missing.
    """
    return (
        f"`{command}` fails after your changes:\n\n"
        f"{outcome.output}\n\n"
        f"Fix the cause. If the failure is not something your change caused, "
        f"say so plainly and leave it alone — do not change unrelated code to "
        f"make a command pass."
    )
