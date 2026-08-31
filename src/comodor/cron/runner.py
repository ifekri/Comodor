"""Running one job: a fresh agent turn, no conversation behind it.

A cron run is built the same way `comodor run` builds one — the same loop,
the same tool registry, the same permission engine refusing by default
because nobody is at the keyboard. The differences are the ones a schedule
forces: the model is fixed at fire time (a job silently drifting to whatever
model is current would run at an unknown cost on an unknown quality), the
memory engine is left out so scheduled runs do not pollute the interactive
brain, and a question form the model puts up is answered "cancelled" at
once, since there is nobody to answer it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agent import AgentLoop, Conversation
from ..agent.spawn import spawner
from ..events import EventBus, Kind
from ..mcp import MCPManager
from ..providers.gateway import Gateway
from ..questions import CANCELLED
from ..safety import PermissionEngine, make_assessor
from ..skills import load_for as load_skills
from ..tools import ToolRegistry


@dataclass
class RunOutcome:
    """What one scheduled run did, in the shape the ledger wants."""

    ok: bool
    answer: str = ""
    error: str = ""
    tool_calls: int = 0
    steps: int = 0
    #: Model actually used, recorded so drift is visible in the history.
    model: str = ""
    #: What the run reached for, for the ledger's "was this sane" check.
    tools_used: list[str] = field(default_factory=list)


def run_job(config, job) -> RunOutcome:
    """One fire of one job, from a fresh agent with nothing behind it."""
    bus = EventBus()

    #: The model is pinned here, once, before anything else looks at it:
    #: fail closed rather than fall back. A pinned model that is not set up
    #: means the job was created on a machine that has since lost it, and
    #: running on a different one is a decision the user never made.
    pinned = job.model or config.cron.model or config.active_model()
    entry = config.providers.get(_provider_for(config, pinned))
    if pinned and (entry is None or entry.model != pinned):
        return RunOutcome(ok=False, error=(
            f"the pinned model {pinned!r} is not available; the run was "
            "refused rather than moved to another model"))
    if entry is not None:
        config.model, config.provider = entry.model, entry.name

    gateway = Gateway(config)
    permissions = PermissionEngine(config, bus)
    # A scheduled run has nobody at the keyboard: a smart verdict of "ask" —
    # or an assessor that cannot run — refuses through the headless branch
    # below, exactly as an unanswered prompt would.
    permissions.assess = make_assessor(config, gateway)
    # No learning engine on purpose: a scheduled run has no person behind it
    # whose corrections could be learned, and lessons proposed by a job would
    # write themselves into sessions the user never saw.
    skills = load_skills(config)
    mcp = MCPManager(config.mcp.servers) if config.mcp.enabled else None
    tools = ToolRegistry(skills=skills, mcp=mcp, config=config,
                         spawn=spawner(config, gateway, bus, skills=skills,
                                       mcp=mcp))
    agent = AgentLoop(config, gateway, tools, bus, permissions,
                      Conversation(), None, skills=skills)

    used: list[str] = []

    def observe(event) -> None:
        if event.kind is Kind.TOOL_START:
            used.append(str(event.get("name", "")))
        elif event.kind is Kind.REQUEST:
            request = event.get("request")
            if request is not None and request.kind == "questions":
                request.answer(CANCELLED)

    unsubscribe = bus.subscribe(observe)
    try:
        result = agent.run(job.prompt)
    finally:
        unsubscribe()
        tools.close()

    return RunOutcome(ok=result.ok, answer=result.text,
                      error=result.error or "", tool_calls=result.tool_calls,
                      steps=result.steps, model=config.active_model(),
                      tools_used=used)


def _provider_for(config, model: str) -> str:
    """Which configured provider serves this model, blank when none does."""
    if not model:
        return config.provider
    for name, entry in config.providers.items():
        if entry.model == model:
            return name
    return ""
