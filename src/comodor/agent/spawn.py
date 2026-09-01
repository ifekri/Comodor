"""Building a delegate, which the tool layer must not know how to do.

The `delegate` tool needs a whole second agent — a gateway, a tool registry, a
permission engine, a conversation — and a tool has none of those and should not
learn. So it is handed a callable and knows only that calling it returns
something with a ``run``.

What a delegate does *not* inherit is as deliberate as what it does:

* **No brain.** It does not recall lessons and it does not reflect afterwards.
  A delegate's episode is half a task seen out of context, and reflecting on it
  teaches the brain about a fragment. The parent's own turn is the episode
  worth learning from, and it still is one.
* **No delegating.** One level deep. A tree of agents is a way to spend an
  afternoon's budget in ninety seconds, and nothing else in the design stops it.
* **No history search.** It cannot see this conversation; letting it search
  every past one instead is a strange kind of amnesia.
* **The parent's cancellation.** Escape stops the whole thing, not the outer
  loop while a delegate keeps working somewhere with a shell open.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..events import Cancellation, EventBus
from ..paths import Paths
from ..safety import PermissionEngine, make_assessor
from ..tools import ToolRegistry


def spawner(config: Any, gateway: Any, bus: EventBus, skills: Any = None,
            mcp: Any = None) -> Any:
    """Return the callable the `delegate` tool is constructed with."""

    def spawn(cwd: Path, mode: str = "plan", max_steps: int = 8,
              max_seconds: float = 300.0,
              cancel: Cancellation | None = None) -> Any:
        from .context import Conversation
        from .loop import AgentLoop

        settings = copy.deepcopy(config)
        settings.paths = replace(settings.paths, project=Path(cwd)) \
            if isinstance(settings.paths, Paths) else settings.paths
        settings.agent.mode = mode
        settings.agent.max_steps = max_steps
        settings.agent.max_seconds = max_seconds
        settings.agent.loop = True
        # Its answer is prose for another agent to read, not a report for a
        # person, so it does not need the parent's output allowance.
        settings.agent.max_output_tokens = min(settings.agent.max_output_tokens, 4096)

        tools = ToolRegistry(skills=skills, mcp=mcp)
        permissions = PermissionEngine(settings, bus)
        permissions.assess = make_assessor(settings, gateway)
        loop = AgentLoop(settings, gateway, tools, bus,
                         permissions, Conversation(),
                         memory=None, skills=skills)
        if cancel is not None:
            loop.cancel = cancel
        return loop

    return spawn
