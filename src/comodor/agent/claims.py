"""Noticing when an answer says the tests pass and nothing ran them.

The one thing a programmer will not forgive is a tool that reports work it did
not do. Slowness is forgiven; a wrong diff is forgiven, because they can see
it. "The tests pass now" when nothing was run is different in kind — every
other claim the tool makes is worth less afterwards.

The system prompt already says not to. This is what happens when it does
anyway: a notice, next to the answer, saying nothing was run. Not a block, and
not an accusation — the user is simply told which of the two situations they
are in, which is the thing they cannot see for themselves.

**The bar for firing is deliberately high**, because a warning that is
sometimes wrong teaches people to ignore the warning. All four have to hold:

1. Files were changed this turn. With nothing changed there is nothing to
   verify and the sentence is almost certainly about something else.
2. No command was run. If anything was, the user can see what it said.
3. The answer states plainly that a suite or a build passes — matched against a
   short list of assertions, not a keyword.
4. The sentence it appears in is not hedged, negated, or an instruction. "Make
   sure the tests pass", "the tests do not pass yet" and "if the tests pass"
   are all the opposite of the claim being looked for.
"""

from __future__ import annotations

import re

#: Tools that could have produced evidence. Anything here means the user has
#: output of their own to read and needs nothing from us.
COMMANDS = frozenset({"run_shell", "run_python"})

#: Tools that change the project, so that there is something to verify.
WRITES = frozenset({"write_file", "edit_file"})

#: Plain assertions that a suite or a build is good. Every one of these is a
#: statement about a thing that was run, which is what makes the absence of a
#: command meaningful.
ASSERTIONS = (
    "tests pass", "tests now pass", "tests are passing", "tests all pass",
    "test suite passes", "the suite passes", "suite is green",
    "suite now passes", "everything passes", "all green",
    "build succeeds", "build passes", "builds successfully",
    "builds cleanly", "compiles cleanly",
)

#: In the same sentence, any of these means it is not a report of what
#: happened: a hypothetical, a condition, or an instruction to the reader.
#: Shared by the positive and negative readings so both agree on what a report
#: is not — "If the tests fail…" and "Make sure tests pass." are neither.
_HEDGE_OR_INSTRUCTION = (
    "if ", "once ", "after ", "when ", "should ", "would ", "will ",
    "make sure", "ensure", "check that", "verify that", "so that",
    "to confirm", "expect", "assume", "presumably", "likely",
)

#: A positive claim additionally excludes a negation or an admission of
#: failure: "the tests do not pass" is not a claim that they pass.
NOT_A_CLAIM = (
    "not ", "n't", "fail", "unable", "cannot", "can not", "still ", "please ",
) + _HEDGE_OR_INSTRUCTION

_SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]?")


def unverified(answer: str, tools_used: list[str]) -> str:
    """The notice to show, or an empty string.

    `tools_used` is every tool name from this turn, in order.
    """
    if not answer:
        return ""
    if any(name in COMMANDS for name in tools_used):
        return ""
    if not any(name in WRITES for name in tools_used):
        return ""

    claim = _find(answer)
    if not claim:
        return ""

    return (f"Nothing was run this turn, so “{claim}” has not been "
            f"checked. Ask it to run the tests, or run them yourself.")


def _find(answer: str) -> str:
    """The first plain assertion in the answer, as it was written."""
    for sentence in _SENTENCE.findall(answer):
        lowered = sentence.lower()
        if not any(phrase in lowered for phrase in ASSERTIONS):
            continue
        if any(word in lowered for word in NOT_A_CLAIM):
            continue
        trimmed = sentence.strip().rstrip(".!?")
        return trimmed if len(trimmed) <= 90 else trimmed[:87] + "…"
    return ""


#: Plain statements that the whole task is finished. The completion gate acts
#: only on one of these (FR-125); an honest partial answer is never blocked.
COMPLETION = (
    "task is complete", "task is done", "task is now complete", "task complete",
    "is now complete", "is complete.", "is done.", "all done", "all complete",
    "everything is done", "everything is complete", "i have completed",
    "i've completed", "i have finished", "i've finished", "work is complete",
    "completed the task", "finished the task", "that's everything",
    "that is everything", "all requests have been addressed",
)


def claims_completion(answer: str) -> bool:
    """Whether the answer explicitly claims the task is complete.

    The same high bar as the unverified-claim notice: a hedged, negated or
    instructional sentence is not a claim. The completion gate blocks only a
    claim that its evidence contradicts — never incompleteness itself
    (FR-125, FR-126).
    """
    for sentence in _SENTENCE.findall(answer or ""):
        lowered = sentence.lower()
        if not any(phrase in lowered for phrase in COMPLETION):
            continue
        if any(word in lowered for word in NOT_A_CLAIM):
            continue
        return True
    return False


# --------------------------------------------------------------------------- #
# the validation-reporting obligation (FR-036, FR-125)
# --------------------------------------------------------------------------- #

#: A request to be told a check's outcome: a reporting verb aimed at a
#: whether/if/the/what clause. The words between them do not matter — "tell me
#: plainly at the end whether the suite passes" is the same request as "tell me
#: whether the suite passes" — because the sentence as a whole is the request.
_REPORT_CUE = re.compile(
    r"(?i)\b(?:tell\s+me|let\s+me\s+know|inform\s+me|report)\b"
    r"[^.?!]*?\b(?:whether|if|the|what)\b")

#: "say" and "state" report only when they head a whether/if clause; "say the
#: word" and "state of the tests" are not requests for a result.
_REPORT_SAY = re.compile(r"(?i)\b(?:say|state)\b[^.?!]*?\b(?:whether|if)\b")

#: What such a report is about.
_VALIDATION_SUBJECT = re.compile(
    r"(?i)\b(test|tests|suite|build|check|checks|lint|validation|result|"
    r"green|passes|passing|succeeds|fails|failing)\b")


def requests_validation_status(request: str) -> bool:
    """Whether the user asked, explicitly, to be told how a check ended.

    A narrow reading: in one sentence, a reporting verb aimed at a whether/if/
    the/what clause and a validation subject. "Run the tests" and "fix the
    build" ask for work, not a report; a false negative here is better than
    inventing an obligation.
    """
    for sentence in _SENTENCE.findall(request or ""):
        lowered = sentence.lower()
        if not _VALIDATION_SUBJECT.search(lowered):
            continue
        if _REPORT_CUE.search(lowered) or _REPORT_SAY.search(lowered):
            return True
    return False


def claims_validation_pass(answer: str) -> bool:
    """Whether the answer plainly asserts that a check passed.

    The same high bar as `unverified`: a hedged, negated or instructional
    sentence is not a claim about what happened.
    """
    return bool(_find(answer))


#: Plain statements that a check failed or is not passing.
FAILURES = (
    "tests fail", "tests still fail", "tests are failing", "tests failed",
    "test fails", "test failed", "the test fails", "suite does not pass",
    "suite doesn't pass", "suite is not green", "suite is still red",
    "suite still does not pass", "suite still fails", "build fails",
    "build failed", "build does not pass", "check failed", "checks failed",
    "validation failed", "validation fails", "pytest failed", "pytest fails",
    "not passing", "does not pass", "doesn't pass", "cannot pass",
    "can't pass", "unable to pass", "not green", "remains red", "still red",
    "still fails", "could not make", "suite is red", "tests are red",
    "does not currently pass", "cannot make the suite pass",
)

#: In the same sentence, these mean it is not a report of what happened: the
#: shared hedges and instructions, plus an instruction not to say it at all.
_NOT_A_FAILURE = _HEDGE_OR_INSTRUCTION + ("do not", "don't", "never ")


def reports_validation_failure(answer: str) -> bool:
    """Whether the answer plainly says a check failed or is not passing."""
    for sentence in _SENTENCE.findall(answer or ""):
        lowered = sentence.lower()
        if not any(phrase in lowered for phrase in FAILURES):
            continue
        if any(word in lowered for word in _NOT_A_FAILURE):
            continue
        return True
    return False


#: Plain statements that no result was obtained.
UNKNOWNS = (
    "did not run", "did not obtain", "could not run", "could not obtain",
    "cannot say", "can't say", "cannot determine", "could not determine",
    "not verified", "unverified", "no test result", "no validation result",
    "was not run", "not been run", "have not run", "haven't run",
    "did not verify", "unable to verify", "not able to verify",
)


def reports_validation_unknown(answer: str) -> bool:
    """Whether the answer plainly says the check's outcome is not known."""
    lowered = " ".join((answer or "").lower().split())
    return any(phrase in lowered for phrase in UNKNOWNS)
