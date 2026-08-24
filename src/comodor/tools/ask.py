"""Ask the user several multiple-choice questions at once.

The rule this tool exists to enforce is *ask before building, not after*. An
agent that guesses at an ambiguous requirement and writes two hundred lines has
spent the user's time and its own; one that asks four short questions first
spends thirty seconds and gets the requirement right.

It is deliberately one call for the whole set. A tool that asked one question
per call would produce exactly the drip of interruptions this replaces — the
model would ask, get an answer, think of the next thing, ask again — and each
round trip is a fresh interruption to somebody who was doing something else.
Working out the whole set first is more work for the model and much less for
the person answering, which is the right way round.

The tool is SAFE, which has a consequence worth naming: it is available in Plan
mode. Planning is when the ambiguity actually bites, so a planning agent that
could not ask would be the one most in need of it.
"""

from __future__ import annotations

import uuid
from typing import Any

from .. import questions as forms
from ..events import Request
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

#: Long enough that somebody can go and check something before answering,
#: short enough that a form nobody is looking at does not hold a thread for the
#: rest of the day. On timeout the questions come back unanswered, and the
#: model is told to carry on and decide for itself.
WAIT_FOR = 1800.0


class Ask(Tool):
    """Put a short form to the user and wait for it."""

    name = "ask"
    risk = Risk.SAFE
    description = (
        "Ask the user to settle things you cannot settle yourself, as a short "
        "multiple-choice form. Call this ONCE, with every question you have, "
        "before you start building — not one question at a time, and not after "
        "the work is done.\n"
        "\n"
        "Ask when a reasonable person would read the request two different ways "
        "and the two readings lead to materially different work: which "
        "framework, which of two files is meant, whether an existing thing is "
        "replaced or kept alongside, what should happen in a case the request "
        "does not mention.\n"
        "\n"
        "Do not ask about things you can find out. Read the file, search the "
        "project, check what is already installed. Do not ask for permission "
        "to proceed, do not ask the user to confirm your plan back to you, and "
        "do not ask about matters with an obvious default — pick the default "
        "and say that you did.\n"
        "\n"
        "Every option needs a label a person can choose between at a glance, "
        "and a description saying what picking it would mean. A row for the "
        "user to write their own answer is added automatically to every "
        "question — never write one yourself."
    )

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": forms.MAX_QUESTIONS,
                "description": (
                    f"Every question you need answered, at most "
                    f"{forms.MAX_QUESTIONS}. They are shown together as one "
                    f"form."),
                "items": {
                    "type": "object",
                    "required": ["question", "header", "options"],
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": (
                                "The question, in full, ending in a question "
                                "mark. Specific enough to answer without "
                                "re-reading the request."),
                        },
                        "header": {
                            "type": "string",
                            "description": (
                                f"A tab label of two or three words, at most "
                                f"{forms.MAX_HEADER} characters — "
                                f"\"Database\", \"Error handling\"."),
                        },
                        "options": {
                            "type": "array",
                            "minItems": forms.MIN_OPTIONS,
                            "maxItems": forms.MAX_OPTIONS,
                            "description": (
                                "The realistic answers. If you have a "
                                "recommendation put it first and end its "
                                "label with \" (recommended)\"."),
                            "items": {
                                "type": "object",
                                "required": ["label"],
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "The choice itself, a few words.",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": (
                                            "One sentence on what choosing this "
                                            "would mean — the trade-off, not a "
                                            "restatement of the label."),
                                    },
                                },
                            },
                        },
                        "multi": {
                            "type": "boolean",
                            "description": (
                                "True when several answers can hold at once. "
                                "Leave it out for a genuine either/or."),
                        },
                    },
                },
            },
        },
        "required": ["questions"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        raw = args.get("questions")
        count = len(raw) if isinstance(raw, list) else 0
        if count == 1:
            return "asking a question"
        return f"asking {count} questions"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        raw = args.get("questions")
        if not isinstance(raw, list):
            return ""
        lines = []
        for entry in raw:
            if isinstance(entry, dict) and entry.get("question"):
                lines.append(f"• {entry['question']}")
        return "\n".join(lines)

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        try:
            questions = forms.parse(args.get("questions"))
        except forms.MalformedQuestions as problem:
            return ToolResult.failure(str(problem))

        request = Request(
            id=f"ask-{uuid.uuid4().hex[:8]}",
            prompt=questions[0].prompt if len(questions) == 1
            else f"{len(questions)} questions before I start",
            # Empty on purpose. The answer to this is a JSON document, not one
            # of a fixed set, and the interfaces validate a non-empty `options`
            # by membership — which would reject every real answer.
            options=[],
            detail="",
            kind="questions",
            meta={"questions": forms.encode(questions)},
        )

        asked = ctx.bus.ask(request)
        answers = forms.decode_answers(asked.wait(WAIT_FOR))

        if answers is None:
            # Cancelled, or nobody was there. Either way the model should get
            # on with it rather than ask again — a second form to somebody who
            # just dismissed the first is the behaviour that makes a feature
            # like this hated.
            return ToolResult.success(
                "The user closed the form without answering. Do not ask again. "
                "Choose sensible defaults, carry on, and say plainly which "
                "decisions you made for them.",
                display="Questions dismissed.",
                answered=False)

        summary = forms.summarise(questions, answers)
        given = sum(1 for answer in answers if answer.given)
        shown = "\n".join(
            f"{answer.header}: {answer.text}" for answer in answers if answer.given)
        return ToolResult.success(
            summary,
            display=shown or "Every question skipped.",
            answered=True, given=given, asked=len(questions))
