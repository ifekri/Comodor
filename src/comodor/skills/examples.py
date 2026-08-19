"""The starter skills written on first run.

An empty folder teaches nobody the format. These three are short, genuinely
useful, and between them show every field a skill header can carry — a plain
skill, one restricted to read-only tools, and one that always applies.
"""

from __future__ import annotations

from pathlib import Path

README = """\
# Skills

A skill is a procedure you write once and Comodor follows whenever it fits.
Drop a Markdown file in this folder:

```markdown
---
name: review
description: Review a change for correctness before it is committed
triggers: [review, diff, pull request]
---

Read the full diff before commenting.

Look for, in this order:
1. Correctness — off-by-one, unhandled errors, wrong branch taken.
2. Anything that silently swallows a failure.
3. Tests that assert the implementation rather than the behaviour.

Report only what you would genuinely block a merge for.
```

**Header fields**

| field | meaning |
|---|---|
| `name` | required; how you refer to the skill |
| `description` | what it is for — this is what the matcher reads |
| `triggers` | extra words that should select it |
| `tools` | restrict which tools may run while it applies |
| `always` | `true` to apply it to every request |
| `enabled` | `false` to keep the file but switch it off |

**Where they live**

- `~/.comodor/skills/` — yours, in every project
- `<project>/.comodor/skills/` — the project's, committable, wins on a name clash

Comodor picks the ones matching your request and puts them in the prompt. Run
`/skills` to see what loaded, and which ones applied.
"""

REVIEW = """\
---
name: review
description: Review a change for correctness before it is committed
triggers: [review, diff, pull request, pr, critique]
tools: [read_file, grep, glob, list_dir, run_shell]
---

Read the whole change before saying anything about it.

Look for, in this order:

1. **Correctness** — off-by-one errors, unhandled failure paths, the wrong
   branch taken, a condition that is inverted.
2. **Silent failures** — an exception swallowed, an error return ignored, a
   fallback that hides the problem it was meant to report.
3. **Tests that assert the implementation** rather than the behaviour, and so
   will break on any refactor without catching a real bug.

Report only what would genuinely block a merge. A review that lists twenty
nitpicks buries the one thing that mattered.

For each finding give the file and line, what breaks, and the smallest change
that fixes it.
"""

EXPLAIN = """\
---
name: explain
description: Explain how part of this codebase works, by reading it
triggers: [explain, how does, walk me through, understand, trace]
tools: [read_file, grep, glob, list_dir]
---

Answer from the code, not from what the names suggest.

Find the real entry point first, then follow the path the data actually takes.
Name the files and line numbers as you go, so the explanation can be checked.

Structure it as:

- **What it does** — one or two sentences.
- **The path** — the sequence of calls, with `file.py:line` for each hop.
- **The parts that surprise** — anything a reader would get wrong by guessing.

If something is unclear from the code alone, say so rather than filling the gap
with a plausible guess.
"""

COMMITS = """\
---
name: commit-style
description: How commit messages should be written in this project
triggers: [commit, message, git]
always: false
---

Write the subject line as an instruction: "Add the health endpoint", not
"Added" or "Adding". Keep it under 72 characters and do not end it with a full
stop.

Leave a blank line, then explain **why** the change was needed. The diff already
says what changed; the message is the only place the reason survives.

Do not list the files you touched. Do not describe the change as "various fixes"
or "improvements".
"""

FILES: dict[str, str] = {
    "README.md": README,
    "review.md": REVIEW,
    "explain.md": EXPLAIN,
    "commit-style.md": COMMITS,
}


def install(directory: Path, overwrite: bool = False) -> list[Path]:
    """Write the starter skills. Returns the files created."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name, content in FILES.items():
        target = directory / name
        if target.exists() and not overwrite:
            continue
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written
