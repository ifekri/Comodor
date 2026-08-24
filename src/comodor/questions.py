"""Questions the agent asks before it commits to an answer.

A request that is ambiguous has two bad endings. The agent picks a reading and
builds the wrong thing, which costs the user a review cycle and some trust; or
the agent asks in prose, one question at a time, and the user spends four turns
answering things that could have been settled in one screen.

This is the third ending. The agent works out everything it is unsure about
*first*, then asks all of it at once, as a short multiple-choice form. The user
answers by pressing arrow keys or clicking, and the whole set comes back in one
message.

The shapes live here, apart from both the tool and the two interfaces, because
three separate pieces of code have to agree on them exactly: the tool that
validates what the model sent, the terminal overlay, and the browser. A field
renamed in one place and not the others is a bug that only shows up in front of
a user, mid-question.

Two rules are enforced here rather than left to the model.

*There is always a way out.* Every question gets a final row the user can type
their own answer into, appended by this module. The model never authors it and
cannot remove it, because the whole point of the row is that it covers what the
model failed to think of.

*Nothing is answered on the user's behalf.* An unanswered question comes back
unanswered, and a cancelled form comes back cancelled. Neither is quietly
turned into a default, because a default here is the agent inventing a
requirement and then building to it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

#: More than this and it stops being a quick form and becomes an interview.
#: The agent that needs six answers should ask for the four that matter and
#: infer the rest from them.
MAX_QUESTIONS = 4

#: Options the model may offer per question. The write-your-own row is not one
#: of these — it is machinery, added afterwards, and it does not use up a slot
#: the model could have spent on a real suggestion.
MAX_OPTIONS = 4

#: Below two there is no choice to make, and a one-option question is really a
#: statement the model should have made in its answer.
MIN_OPTIONS = 2

#: The label on the row that is always added.
WRITE_YOUR_OWN = "Something else"

#: A tab needs to fit several-across in a narrow terminal panel.
MAX_HEADER = 18


class MalformedQuestions(ValueError):
    """What the model sent cannot be shown to anybody.

    Raised with a sentence that says which question and what was wrong with it,
    because that message goes straight back to the model as a tool error and is
    the only thing it has to correct itself with.
    """


# --------------------------------------------------------------------------- #
# the shapes
# --------------------------------------------------------------------------- #


@dataclass
class Option:
    """One row the user can pick."""

    label: str
    description: str = ""
    #: True for the appended write-your-own row, which is rendered differently
    #: and carries typed text instead of a fixed label.
    free: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Question:
    """One question, and the ways it can be answered."""

    prompt: str
    header: str
    options: list[Option]
    multi: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"prompt": self.prompt, "header": self.header,
                "multi": self.multi,
                "options": [option.to_json() for option in self.options]}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Question":
        return cls(prompt=str(data.get("prompt", "")),
                   header=str(data.get("header", "")),
                   multi=bool(data.get("multi", False)),
                   options=[Option(label=str(entry.get("label", "")),
                                   description=str(entry.get("description", "")),
                                   free=bool(entry.get("free", False)))
                            for entry in data.get("options", [])])


@dataclass
class Answer:
    """What came back for one question."""

    header: str
    prompt: str
    chosen: list[str] = field(default_factory=list)
    #: What the user typed into the write-your-own row, if they used it.
    written: str = ""

    @property
    def given(self) -> bool:
        return bool(self.chosen) or bool(self.written.strip())

    @property
    def text(self) -> str:
        """The answer as one line, for the model to read."""
        parts = list(self.chosen)
        if self.written.strip():
            parts.append(self.written.strip())
        return ", ".join(parts)


# --------------------------------------------------------------------------- #
# validating what the model sent
# --------------------------------------------------------------------------- #


def parse(raw: Any) -> list[Question]:
    """Turn the tool's arguments into questions, or say exactly what is wrong.

    Strict on the things that would produce a broken form — no options, one
    option, a missing prompt — and forgiving on the things that do not: a
    header that is too long is trimmed, a plain string where an option object
    was expected is accepted as a label. Models get the shape slightly wrong
    routinely, and a refusal that could have been a trim is a wasted turn.
    """
    if not isinstance(raw, list):
        raise MalformedQuestions(
            "`questions` must be a list of question objects")
    if not raw:
        raise MalformedQuestions(
            "`questions` was empty — ask at least one question, or do not call "
            "this tool")
    if len(raw) > MAX_QUESTIONS:
        raise MalformedQuestions(
            f"{len(raw)} questions is too many; ask the {MAX_QUESTIONS} that "
            f"matter most and infer the rest from the answers")

    questions: list[Question] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw, start=1):
        questions.append(_one(entry, index, seen))
    return questions


def _one(entry: Any, index: int, seen: set[str]) -> Question:
    where = f"question {index}"
    if not isinstance(entry, dict):
        raise MalformedQuestions(f"{where} is not an object")

    prompt = str(entry.get("question") or entry.get("prompt") or "").strip()
    if not prompt:
        raise MalformedQuestions(f"{where} has no `question` text")

    options = _options(entry.get("options"), where)

    header = str(entry.get("header") or "").strip()
    if not header:
        # Falling back to the prompt keeps the form usable rather than
        # refusing over a label. Truncated at a word so the tab reads as words.
        header = _shorten(prompt, MAX_HEADER)
    header = _shorten(header, MAX_HEADER)

    # Two tabs with the same name are two tabs the user cannot tell apart.
    original, suffix = header, 2
    while header.lower() in seen:
        header = f"{_shorten(original, MAX_HEADER - 2)} {suffix}"
        suffix += 1
    seen.add(header.lower())

    return Question(prompt=prompt, header=header, options=options,
                    multi=bool(entry.get("multi") or entry.get("multiSelect")))


def _options(raw: Any, where: str) -> list[Option]:
    if not isinstance(raw, list):
        raise MalformedQuestions(f"{where} has no `options` list")

    options: list[Option] = []
    for entry in raw:
        if isinstance(entry, str):
            label = entry.strip()
            description = ""
        elif isinstance(entry, dict):
            label = str(entry.get("label") or entry.get("value") or "").strip()
            description = str(entry.get("description") or "").strip()
        else:
            continue
        if not label:
            continue
        # A model that offers its own escape hatch would give the user two of
        # them, one of which does not work.
        if _is_an_escape_hatch(label):
            continue
        options.append(Option(label=label, description=description))

    if len(options) < MIN_OPTIONS:
        raise MalformedQuestions(
            f"{where} needs at least {MIN_OPTIONS} options; with fewer there is "
            f"no choice to make")
    if len(options) > MAX_OPTIONS:
        raise MalformedQuestions(
            f"{where} has {len(options)} options and the limit is {MAX_OPTIONS}; "
            f"a list longer than that is a menu, not a question")

    options.append(Option(label=WRITE_YOUR_OWN, free=True))
    return options


def _is_an_escape_hatch(label: str) -> bool:
    plain = label.lower().strip(" .…!?")
    return plain in {
        "other", "others", "something else", "write your own", "custom",
        "none of these", "none of the above", "let me write", "i'll write",
        "i will write my own", "type my own", "my own answer",
    }


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(" ,;:")


# --------------------------------------------------------------------------- #
# crossing the wire
# --------------------------------------------------------------------------- #
#
# The request/answer channel between the agent thread and whichever interface
# is attached carries strings. That is the right shape for a permission prompt,
# which answers "allow" or "deny", and the wrong one here — so a form goes over
# it as JSON and comes back as JSON.
#
# Everything below treats malformed input as "cancelled" rather than raising.
# By the time an answer is being read the user has already walked away from the
# form, and an exception on that path would strand the agent thread that is
# blocked waiting for it.


def encode(questions: list[Question]) -> list[dict[str, Any]]:
    """The form, as something JSON-serialisable to hand to an interface."""
    return [question.to_json() for question in questions]


def decode(data: Any) -> list[Question]:
    """The form, back from an interface."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    if not isinstance(data, list):
        return []
    return [Question.from_json(entry) for entry in data
            if isinstance(entry, dict)]


#: What an interface sends back when the user closed the form without
#: finishing it. Distinct from an empty answer set, which would be
#: indistinguishable from a form nobody has touched yet.
CANCELLED = "cancelled"


def encode_answers(answers: list[Answer]) -> str:
    return json.dumps([asdict(answer) for answer in answers],
                      ensure_ascii=False)


def decode_answers(raw: str) -> list[Answer] | None:
    """The answers, or ``None`` for a form that was cancelled or never filled.

    ``None`` and ``[]`` mean different things and the caller acts on the
    difference: nothing came back at all, versus a form that came back with
    every question deliberately skipped.
    """
    if not raw or raw in (CANCELLED, "no", "deny"):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None

    answers: list[Answer] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        chosen = entry.get("chosen")
        answers.append(Answer(
            header=str(entry.get("header", "")),
            prompt=str(entry.get("prompt", "")),
            chosen=[str(item) for item in chosen] if isinstance(chosen, list) else [],
            written=str(entry.get("written", "")),
        ))
    return answers


# --------------------------------------------------------------------------- #
# what the model reads
# --------------------------------------------------------------------------- #


def summarise(questions: list[Question], answers: list[Answer]) -> str:
    """The answers, written out for the model.

    Question and answer are kept together. The model asked these several turns
    of thinking ago, and a bare list of values — "TypeScript, PostgreSQL, no" —
    is one it has to re-derive the meaning of.

    A question the user skipped is reported as skipped, explicitly. Left out of
    the list it reads as an oversight, and the model fills the gap with an
    assumption; named as skipped it reads as what it is, which is the user
    declining to constrain that decision.
    """
    by_header = {answer.header: answer for answer in answers}
    lines: list[str] = []
    skipped: list[str] = []

    for question in questions:
        answer = by_header.get(question.header)
        if answer is None or not answer.given:
            skipped.append(question.prompt)
            continue
        lines.append(f"{question.prompt}\n  -> {answer.text}")

    parts: list[str] = []
    if lines:
        parts.append("The user answered:\n\n" + "\n".join(lines))
    if skipped:
        parts.append(
            "Left unanswered, so the user has not constrained these — decide "
            "them yourself and say which way you went:\n"
            + "\n".join(f"  - {prompt}" for prompt in skipped))
    if not parts:
        return "The user skipped every question."
    return "\n\n".join(parts)
