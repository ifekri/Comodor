"""What each mode allows, in one place.

Mode was already enforced — the tool registry hid the tools a mode may not
use, and the permission engine refused by risk tier — but the rule itself was
written twice, in two shapes, in two files. Two copies of a security rule is
one rule and one thing that will disagree with it later, and the disagreement
is invisible: both files look correct on their own.

So the rule is data now, and both call sites read this table.

    ACT    everything, subject to permissions
    PLAN   read, and read-only tools; no writes, no shell, no external change
    ASK    conversation and questions; no tools at all
    CHAT   conversation only

`ASK` and `CHAT` differ in intent rather than in capability today: ask is the
mode a person picks to talk about the code, chat the one that predates it.
They are kept apart because the model is told different things in each, and
folding them together would silently change what a `chat` session does.

**This is not the security boundary on its own.** It is the statement of the
policy; the boundary is that `ToolRegistry.invoke` and `PermissionEngine`
consult it before anything runs, so a client that sends a method directly is
refused by the same table that hides the button.
"""

from __future__ import annotations

from dataclasses import dataclass

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
        may_read=True,
        may_use_read_tools=True,
        may_use_mutating_tools=False,
        may_execute_shell=False,
        may_mutate_files=False,
        may_mutate_external_services=False,
        may_ask_questions=True,
        refusal=("Ask mode is read-only, so this step was skipped. "
                 "Switch to Act mode to let it run."),
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


def policy_for(mode: str | None) -> ModePolicy:
    """The policy for a mode name, defaulting to Act.

    Unknown names fall back to Act rather than to the strictest mode on
    purpose: the value comes from a config file a person edits, and a typo
    that silently disables every tool looks like the agent is broken, while a
    typo that behaves as normal is noticed the moment someone reads the mode
    line. The set of names is small, closed and validated where it enters —
    `session.set_mode` refuses anything not in `ALL`.
    """
    return _POLICIES.get(str(mode or ACT).lower(), _POLICIES[ACT])


def known(mode: str | None) -> bool:
    return str(mode or "").lower() in _POLICIES


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
