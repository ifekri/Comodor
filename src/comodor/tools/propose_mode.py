"""Suggest a mode change, and let the user accept or decline in place.

Each restricted mode reaches a moment when its work is done but the task is
not: a plan that the user clearly wants carried out, a question that turns out
to be a request for changes. The guidance in the mode prompt says to name the
switch rather than stall — this tool is how the naming becomes an action the
user can take with one press instead of finding the mode control themselves.

It is deliberately a *suggestion* with the current mode as an explicit option,
not a mode selector. Choosing a mode is a decision about what the next message
is allowed to do, and that decision belongs to the person; the tool's job is to
put it in front of them at the moment it matters, framed by what the agent
wants to do next.

The request rides the same `Request` channel as a permission prompt, so every
interface — terminal overlay, web page, Telegram, WhatsApp, Slack, ACP — shows
it with no per-interface code beyond what permission prompts already use.
"""

from __future__ import annotations

import uuid
from typing import Any

from ..events import Request
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

#: Long enough to read what is proposed, short enough that a prompt nobody is
#: watching does not hold the turn half a day. On timeout nothing changes —
#: the model is told to continue in the current mode.
WAIT_FOR = 600.0

#: The modes a suggestion may propose. Chat is left out: nothing the agent does
#: in a working mode leads naturally to "stop using tools", and a suggestion
#: toward it would almost always be the model trying to end the conversation.
PROPOSABLE = ("act", "plan", "ask")


class ProposeMode(Tool):
    """Offer the user a mode switch at the point the work calls for one."""

    name = "propose_mode"
    risk = Risk.SAFE
    description = (
        "Offer to switch modes, as a prompt the user answers with one press. "
        "Use it when the work you are doing has reached the edge of what the "
        "current mode allows and the next step clearly belongs to another "
        "mode: a plan that is finished and ready to build (plan -> act), or a "
        "question that turns out to be a request for changes (ask -> act).\n"
        "\n"
        "Say what you would do once switched — the user is deciding whether to "
        "hand you the tools, so the reason has to be there in the prompt.\n"
        "\n"
        "Do not use it to ask permission to finish the current task, and do "
        "not repeat a suggestion the user already declined. One offer per "
        "moment; if they keep the current mode, carry on within it."
    )

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "target_mode": {
                "type": "string",
                "enum": list(PROPOSABLE),
                "description": (
                    "The mode you are suggesting. Omit it only to ask which "
                    "mode they want without steering."),
            },
            "reason": {
                "type": "string",
                "description": (
                    "What you would do once switched, in one sentence. "
                    "\"The plan is complete — I'd start with the migration "
                    "script.\" Not a restatement of the mode names."),
            },
        },
        "required": ["reason"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        target = str(args.get("target_mode") or "").strip().lower()
        if target:
            return f"proposing switch to {target} mode"
        return "proposing a mode change"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        return str(args.get("reason") or "").strip()

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        target = str(args.get("target_mode") or "").strip().lower()
        if target and target not in PROPOSABLE:
            return ToolResult.failure(
                f"{target!r} is not a mode that can be proposed. "
                f"One of: {', '.join(PROPOSABLE)}.")

        reason = " ".join(str(args.get("reason") or "").split())
        if not reason:
            return ToolResult.failure(
                "a `reason` is required — say what you would do once switched")

        current = (ctx.config.agent.mode or "act").lower()
        if target and target == current:
            return ToolResult.success(
                f"Already in {current} mode. Carry on with the task.")

        options = _options_for(current, target)
        prompt = (f"Switch to {target} mode?"
                  if target else "Which mode should I work in?")

        request = Request(
            id=f"mode-{uuid.uuid4().hex[:8]}",
            prompt=f"{prompt} {reason}".strip(),
            options=options,
            kind="mode",
            meta={"current": current, "target": target},
        )
        answered = ctx.bus.ask(request).wait(WAIT_FOR)

        if answered in PROPOSABLE:
            ctx.config.agent.mode = answered
            return ToolResult.success(
                f"The user switched you to {answered} mode. Continue there.",
                display=f"Mode: {answered}",
                mode=answered)
        if answered == "deny":
            return ToolResult.success(
                "The user kept the current mode. Do not propose this again — "
                "continue within it.",
                display="Kept the current mode",
                mode=current)
        # Cancelled, timed out, or an answer the interface could not make
        # sense of. Continue as things are rather than treating silence as
        # either a yes or a second chance to ask.
        return ToolResult.success(
            "No answer — continue in the current mode.",
            display="No change",
            mode=current)


def _options_for(current: str, target: str) -> list[str]:
    """The choices, most likely first, current mode never absent.

    The proposal leads. The current mode is offered last so declining is
    always one press, and the third slot is the remaining working mode for
    the "actually, the other one" case. The interface falls back to the last
    option on timeout or dismissal, which is why the current mode must be
    last: silence means "no change", never a switch.
    """
    others = [mode for mode in PROPOSABLE if mode not in (target, current)]
    options: list[str] = []
    if target:
        options.append(target)
    options += others
    options.append(current)
    return options
