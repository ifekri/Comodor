"""A measure of whether Comodor is any good at the job, rather than whether its
parts are wired together.

The test suite answers "does the Telegram keyboard serialise correctly". Nothing
answered "does it fix the bug", which meant every change to the system prompt,
the tool descriptions or the loop was a guess with a story attached. This is the
answer to that: real tasks, in real repositories, judged by a program.

Three rules hold the numbers up, and each one is a way this kind of benchmark
usually goes wrong.

*The judge is a program, never a model.* Every check is an assertion somebody
else can re-run and get the same answer from: the suite goes green, the file
parses, the old name is gone from every file. An LLM judge is a second source of
noise, and one a stranger cannot reproduce — which defeats the point of
publishing the result.

*Every run is isolated.* A fresh copy of the task's repository in a temporary
directory, its own `COMODOR_HOME`, and the learning engine switched off. Without
that last one the second run differs from the first by design, and nothing here
would be reproducible.

*A task is reported as a rate, not a verdict.* Agents are not deterministic.
Three attempts, reported `3/3` or `1/3`, because a single run dressed up as
"it passes" is exactly the invented number this project does not ship.
"""

from __future__ import annotations

from .task import Task, Verdict, load_tasks

__all__ = ["Task", "Verdict", "load_tasks"]
