"""A six-task sequence in one project, judged on the SC-021 window comparison.

The same visible work is asked for six times — add one setting, and say which
environment it applies to. The environment is a material decision the
repository cannot settle, so a good agent asks; once the answer is settled it
is not asked again. The project's quoting style is a preference the person
holds, not something the code states, so the harness corrects a double-quoted
key to a single-quoted one the way a person would, and the next task's own
correction detector learns it.

Only the *user side* is automated. The scripted interaction drives the real ask
tool, ledger and loop; corrections are real file edits the real detector reads.
Nothing is written into the brain directly.

The verdict is the SC-021 comparison itself, and an incomparable run is invalid
rather than passing:
  * clarifications in tasks 4-6 are fewer than in 1-3, and
  * corrections in tasks 4-6 are fewer than in 1-3, and
  * no task's success regresses.
Repository rediscovery and token counts are diagnostics only and never
substitute for the two primary metrics.
"""

from __future__ import annotations

from bench.task import Verdict

CATEGORY = "careful"
MAX_STEPS = 20
TIMEOUT = 300.0
WRITES = True

#: The setting values, one per task.
VALUES = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")

#: What the person answers when asked which environment, and the one thing all
#: six tasks share beyond their shape.
ENVIRONMENT = "staging"


def _step(index: int) -> dict:
    key = f"K{index + 1}"
    return {
        "prompt": (f"Add the setting {key} with value {VALUES[index]} to "
                   f"items.py, and record which environment it applies to."),
        "interaction": ({"action": "answer", "value": ENVIRONMENT},),
        "expect": {"path": "items.py", "marker": key},
    }


SEQUENCE = [_step(index) for index in range(6)]


def correct(index: int, attempt, workspace) -> bool:
    """The person's edit after a task: this project single-quotes setting keys.

    Applied only when the key was written double-quoted, so a task that already
    matches — because the learned convention is in force — needs no edit and
    counts as no correction.
    """
    target = workspace / "items.py"
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return False
    key = f"K{index + 1}"
    if f'"{key}"' not in text:
        return False
    target.write_text(text.replace(f'"{key}"', f"'{key}'"), encoding="utf-8")
    return True


def check_sequence(result) -> Verdict:
    if not result.comparable:
        return Verdict.no("the six tasks are not comparable — the run is invalid")

    windows = result.windows()
    initial, learned = windows["initial"], windows["learned"]

    if learned["clarifications"] >= initial["clarifications"]:
        return Verdict.no(
            f"mandatory clarifications did not fall: {initial['clarifications']} "
            f"in tasks 1-3, {learned['clarifications']} in tasks 4-6")
    if learned["corrections"] >= initial["corrections"]:
        return Verdict.no(
            f"user corrections did not fall: {initial['corrections']} in tasks "
            f"1-3, {learned['corrections']} in tasks 4-6")
    if learned["success"] < initial["success"]:
        return Verdict.no(
            f"task success regressed: {initial['success']} of 3 in tasks 1-3, "
            f"{learned['success']} of 3 in tasks 4-6")
    return Verdict.ok(
        f"clarifications {initial['clarifications']}->{learned['clarifications']}, "
        f"corrections {initial['corrections']}->{learned['corrections']}, "
        f"success {initial['success']}->{learned['success']} of 3")
