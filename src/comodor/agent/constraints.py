"""What the user said not to do, put back in front of the model.

Every failure the benchmark finds in the `careful` category has the same shape.
The user says "do not invent the coordinates" or "only `importer.py`", the model
reads it, works for twenty steps, and by the time it is about to write a file
that instruction is four thousand tokens up the context behind everything it
has read since. It does the forbidden thing, and it is not being defiant — the
sentence is simply no longer where it is looking.

So the prohibitions are pulled out of the request once and shown again at the
moment they apply: on the tool result of a write, which is the last thing the
model reads before deciding what to do next.

Three things this deliberately is not.

*It is not a judgement.* Nothing here decides whether a write violates
anything — that would need to understand the constraint, and a wrong refusal is
far worse than a forgotten one. It restates what the user said and leaves the
model to apply it.

*It is not a model call.* Patterns over the request text, run once per turn.
An extraction step that costs a request would be spending money to save money.

*It is not the system prompt.* That must stay byte-identical across turns or
the provider's cached prefix stops matching, which was measured at 99% and is
worth more than anything this could add.

What it costs: about thirty tokens, on write results, in turns where the user
actually stated a prohibition. Most turns have none and pay nothing.
"""

from __future__ import annotations

import re

#: Tools that change something. Named here as well as in `staleness` because
#: this asks a different question of the same set: not "did this invalidate a
#: read" but "is the moment for a reminder past".
WRITERS = frozenset({"write_file", "edit_file"})

#: How many to carry. A request with nine prohibitions in it is a request whose
#: author will not be helped by seeing all nine again on every write, and the
#: first few are where people put the ones they mean.
MOST = 3

#: Longer than this and it is a paragraph rather than a rule. Restating a
#: paragraph at the point of action is noise, and noise is what makes a
#: reminder ignorable.
#:
#: Two hundred rather than a tighter number because a real one was lost at 160:
#: "the old names must not be left anywhere in the project - not in an import,
#: not in an alias kept for compatibility, not in a comment" is 163 characters
#: and is exactly the kind of rule this exists to carry.
LONGEST = 200

#: The shapes an instruction not to do something takes. Deliberately narrow:
#: a false positive here puts an irrelevant sentence in front of the model on
#: every write, which is worse than missing one.
FORBIDDING = re.compile(
    r"\b("
    r"do not\b|don't\b|never\b|"
    r"must not\b|cannot\b|can't\b|"
    r"without (?:changing|editing|touching|modifying|creating|adding)\b|"
    r"leave .{0,30}\balone\b|"
    r"nothing (?:else|other than)\b|"
    r"only\b(?=[^.!?]{0,60}\b(?:file|files|change|changes|edit|touch|in scope)\b)"
    r")",
    re.IGNORECASE)

#: Said *about* a prohibition rather than stating one. "I did not change the
#: tests" is a report; "do not change the tests" is a rule.
REPORTING = re.compile(
    r"^\s*(?:i|we|it|they|he|she)\b|"
    r"\b(?:i|we) (?:did|have|had|will|would|could|am|are)\b",
    re.IGNORECASE)

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")

#: A line that begins a point of its own rather than continuing the one above.
_ITEM = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s")


def unwrap(text: str) -> str:
    """Join lines that a hard wrap split, and leave the rest alone.

    Requests are written in a terminal and wrapped at eighty columns, so a
    sentence routinely spans three lines. Splitting on newlines cut "do not
    write a stand-in table" after "stand-in", and half a rule restated at the
    point of action is worse than none — it reads as though something was lost,
    which it was.

    A blank line, and a line that starts a bullet or a number, still separate.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        if out and out[-1] and not _ITEM.match(line) \
                and not out[-1].endswith((".", "!", "?", ":")):
            out[-1] = f"{out[-1]} {stripped}"
        else:
            out.append(stripped)
    return "\n".join(out)


def prohibitions(request: str) -> list[str]:
    """The sentences in a request that tell the agent not to do something.

    Order is the order they were written in: the first thing somebody thinks
    to forbid is usually the thing they care most about.
    """
    if not request:
        return []

    found: list[str] = []
    for sentence in _SENTENCE.findall(unwrap(request)):
        trimmed = " ".join(sentence.split())
        if not trimmed or len(trimmed) > LONGEST:
            continue
        if not FORBIDDING.search(trimmed):
            continue
        if REPORTING.search(trimmed):
            continue
        if trimmed not in found:
            found.append(trimmed)
        if len(found) >= MOST:
            break
    return found


def reminder(rules: list[str]) -> str:
    """The line appended to a write, or nothing.

    Phrased as a quotation rather than an accusation. The model has not done
    anything wrong by the time it reads this — it is about to decide what to do
    next, and this is what it was told.
    """
    if not rules:
        return ""
    if len(rules) == 1:
        return f"You were asked: {rules[0]}"
    joined = "\n".join(f"  - {rule}" for rule in rules)
    return "You were asked:\n" + joined
