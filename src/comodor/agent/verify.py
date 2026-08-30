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

    @property
    def worth_reporting(self) -> bool:
        return self.ran and not self.passed


def run(command: str, cwd: Path, patience: float = PATIENCE) -> Outcome:
    """Run the project's check and say what happened. Never raises."""
    if not command.strip():
        return Outcome(ran=False, passed=True, output="")

    environment = dict(os.environ)
    # A check that shells out to the agent would be a loop with a bill on it.
    environment["COMODOR_VERIFYING"] = "1"

    try:
        finished = subprocess.run(
            command, shell=True, cwd=str(cwd), env=environment,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=patience)
    except subprocess.TimeoutExpired:
        return Outcome(ran=True, passed=False,
                       output=f"(no result within {patience:.0f}s)")
    except (OSError, ValueError) as problem:
        return Outcome(ran=False, passed=True, output="",
                       unusable=f"{type(problem).__name__}: {problem}")

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
