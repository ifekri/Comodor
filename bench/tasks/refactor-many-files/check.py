"""A rename across twelve real modules, so the resend cost is the task.

Every module defines and calls `legacy_handler`. Doing the work correctly means
reading and editing all twelve, and every edit that is re-sent with its file's
contents is the cost this scenario exists to measure (SC-011).

The judge is the repository transformation and nothing else. It checks the
filesystem the work happened in: the exact twelve modules are present, the old
identifier is gone, each module defines and calls the new one, and every file
still parses. It never reads `attempt.text` — a completion answer that says
"renamed legacy_handler to handle" is a correct answer, and treating the old
symbol's *mention* as evidence it survived is the false negative this judge was
corrected for (an earlier version failed three correct runs on exactly that).
"""

from __future__ import annotations

from bench import judge
from bench.task import Verdict

CATEGORY = "refactor"
MAX_STEPS = 60
TIMEOUT = 600.0

#: The name that must be gone, and the one that must be everywhere instead.
OLD = "legacy_handler"
NEW = "handle"

#: The exact set of modules the task must transform. Asserting the set, rather
#: than counting whatever `*.py` happens to be there, is what proves no target
#: was skipped and no module was added to stand in for one.
EXPECTED = tuple(f"m{number:02d}.py" for number in range(1, 13))


def check(attempt):
    service = attempt.workspace / "service"
    present = {path.name for path in service.glob("*.py")} if service.is_dir() else set()
    missing = [name for name in EXPECTED if name not in present]
    if missing:
        return Verdict.no(f"service/ is missing {', '.join(missing)}")

    # The old identifier is gone from every source file, not merely renamed in
    # some of them.
    gone = judge.absent(attempt.workspace, OLD)
    if not gone.passed:
        return gone

    # Each intended target was actually transformed: it defines the new handler
    # and calls it. Requiring the new name is what stops "delete everything so
    # both symbols disappear" from passing.
    for name in EXPECTED:
        try:
            text = (service / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return Verdict.no(f"service/{name} is gone")
        if f"def {NEW}(" not in text:
            return Verdict.no(f"service/{name} does not define the renamed handler")
        if f"{NEW}(" not in text:
            return Verdict.no(f"service/{name} never calls the renamed handler")

    return judge.parses(attempt.workspace,
                        *[f"service/{name}" for name in EXPECTED])
