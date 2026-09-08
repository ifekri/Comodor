"""What each mode allows, in one place.

Mode was already enforced — the tool registry hid the tools a mode may not
use, and the permission engine refused by risk tier — but the rule itself was
written twice, in two shapes, in two files. Two copies of a security rule is
one rule and one thing that will disagree with it later, and the disagreement
is invisible: both files look correct on their own.

So the rule is data now, and both call sites read this table.

    ACT    everything, subject to permissions
    PLAN   read-only inspection tools; no writes, no shell, no external change
    ASK    conversation and questions; no tools at all
    CHAT   conversation only

**`ASK` gets no tools.** It is the mode for talking about code, and the line
between it and `PLAN` is exactly which one may go and look. `PLAN` is the
mode that inspects — read files, search, gather context — and produces a plan
it may not carry out. `ASK` answers from the conversation. Giving `ASK` the
read tools would have made the two the same mode with different labels, which
is the failure a mode is supposed to prevent.

`ASK` and `CHAT` therefore have the same capabilities and different intent:
ask is what a person picks today, chat predates it. They stay apart because
the model is told different things in each, and folding them together would
silently change what an existing `chat` session does.

**An unrecognised mode denies everything.** Not `ACT`. A mode name arrives
from a config file a person edits, a channel message, an API body — and
`"paln"` earning full write and shell access because it failed to match is
the shape of authorization bug that is discovered afterwards. `policy_for`
raises on an explicit unknown so it is caught where the value enters, and the
two enforcement points fall back to `DENIED` rather than to anything else.

**This is not the security boundary on its own.** It is the statement of the
policy; the boundary is that `ToolRegistry.invoke` and `PermissionEngine`
consult it before anything runs, so a client that sends a method directly is
refused by the same table that hides the button.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

#: The canonical names, in the order a person cycles them.
ACT = "act"
PLAN = "plan"
ASK = "ask"
CHAT = "chat"

ORDER: tuple[str, ...] = (ACT, PLAN, ASK)
ALL: tuple[str, ...] = (ACT, PLAN, ASK, CHAT)


@dataclass(frozen=True)
class ModePolicy:
    """What one mode permits.

    Frozen because a policy that can be edited at runtime is a policy that can
    be edited by whatever is running under it.
    """

    name: str
    may_read: bool
    may_use_read_tools: bool
    may_use_mutating_tools: bool
    may_execute_shell: bool
    may_mutate_files: bool
    may_mutate_external_services: bool
    may_ask_questions: bool
    #: Shown to a person when the mode is why something did not happen.
    refusal: str

    @property
    def may_use_any_tool(self) -> bool:
        return self.may_use_read_tools or self.may_use_mutating_tools


_POLICIES: dict[str, ModePolicy] = {
    ACT: ModePolicy(
        name=ACT,
        may_read=True,
        may_use_read_tools=True,
        may_use_mutating_tools=True,
        may_execute_shell=True,
        may_mutate_files=True,
        may_mutate_external_services=True,
        may_ask_questions=True,
        refusal="",
    ),
    PLAN: ModePolicy(
        name=PLAN,
        may_read=True,
        may_use_read_tools=True,
        may_use_mutating_tools=False,
        may_execute_shell=False,
        may_mutate_files=False,
        may_mutate_external_services=False,
        may_ask_questions=True,
        refusal=("Plan mode is read-only, so this step was skipped. "
                 "Switch to Act mode to let it run."),
    ),
    ASK: ModePolicy(
        name=ASK,
        # It may read what the conversation already carries. What it may not
        # do is go and fetch more — that is Plan's job, and the difference is
        # the only thing that makes them two modes.
        may_read=True,
        may_use_read_tools=False,
        may_use_mutating_tools=False,
        may_execute_shell=False,
        may_mutate_files=False,
        may_mutate_external_services=False,
        may_ask_questions=True,
        refusal=("Ask mode is for talking it through, so no tool was run. "
                 "Switch to Plan to let it look, or Act to let it work."),
    ),
    CHAT: ModePolicy(
        name=CHAT,
        may_read=True,
        may_use_read_tools=False,
        may_use_mutating_tools=False,
        may_execute_shell=False,
        may_mutate_files=False,
        may_mutate_external_services=False,
        may_ask_questions=True,
        refusal="Chat mode has tools switched off — press F3 to switch to Act.",
    ),
}


#: What an unrecognised mode gets. Everything refused, and the name said back
#: so the message is actionable rather than mysterious.
DENIED = ModePolicy(
    name="",
    may_read=False,
    may_use_read_tools=False,
    may_use_mutating_tools=False,
    may_execute_shell=False,
    may_mutate_files=False,
    may_mutate_external_services=False,
    may_ask_questions=False,
    refusal="",
)

#: What Comodor runs as when nothing says otherwise.
DEFAULT = ACT


class UnknownMode(ValueError):
    """A mode name that is not one of the four.

    Raised where a value enters — a config file, a channel message, an API
    body — so it is refused with the name in the message rather than turned
    into a privilege level by a lookup that missed.
    """

    def __init__(self, mode: str) -> None:
        super().__init__(
            f"{mode!r} is not a mode; expected one of {', '.join(ALL)}")
        self.mode = mode


def policy_for(mode: str | None) -> ModePolicy:
    """The policy for a mode name.

    Absent — `None` or empty — is the documented default. An explicit name
    that is not one of the four raises, because the alternative is a typo
    quietly acquiring whatever the fallback happened to be. `"paln"` earning
    write and shell access because it failed to match is exactly the shape of
    authorization bug that is found after it has been used.

    Callers on the enforcement path want `enforced` instead, which cannot
    raise and denies everything for a name it does not know.
    """
    if mode is None or str(mode).strip() == "":
        return _POLICIES[DEFAULT]
    # Stripped as well as lowered: a trailing space in a config file is
    # a typo in the whitespace, not a different mode.
    found = _POLICIES.get(str(mode).strip().lower())
    if found is None:
        raise UnknownMode(str(mode))
    return found


def enforced(mode: str | None) -> ModePolicy:
    """The policy to *enforce*, which never raises and never fails open.

    The two places that gate a tool call cannot throw — one builds the list
    the model is shown, the other runs before every invocation, and an
    exception in either turns a bad config value into a crash mid-task. So
    they fail closed: an unrecognised mode is a mode that may do nothing, and
    the refusal names it.
    """
    try:
        return policy_for(mode)
    except UnknownMode:
        return replace(
            DENIED,
            name=str(mode),
            refusal=(f"{mode!r} is not a mode Comodor knows, so nothing was "
                     f"run. Set one of {', '.join(ALL)}."),
        )


def known(mode: str | None) -> bool:
    return str(mode or "").strip().lower() in _POLICIES


def cycle(mode: str | None, back: bool = False) -> str:
    """The next mode a person gets by pressing the key.

    `chat` is not in the cycle — it predates `ask` and reaching it by repeated
    presses would surprise somebody who only knows the three. It stays
    reachable by name.
    """
    current = str(mode or ACT).lower()
    if current not in ORDER:
        return ORDER[0]
    step = -1 if back else 1
    return ORDER[(ORDER.index(current) + step) % len(ORDER)]
