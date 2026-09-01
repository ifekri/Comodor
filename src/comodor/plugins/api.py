"""What a plugin may do, and nothing more.

The context handed to a plugin's ``register`` deliberately exposes three
capabilities and nothing else: a tool (which then lives in the same registry
and the same permission gate as every built-in), a hook (a subscription on the
event bus every other listener already shares), and a CLI command. There is no
handle to the brain, the sessions, or the provider keys — a plugin that needs
data of that kind must expose it as a tool, and a tool goes through the same
approval a person would expect of anything else that can act.
"""

from __future__ import annotations

import argparse
import re
from typing import Any, Callable

#: Tool names must survive namespacing, function-call dialects and help text.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
#: Hook names are the bus's kinds, given plugin-friendly aliases. Adding a
#: name here is free; emitting new lifecycle events is a core change.
HOOK_ALIASES: dict[str, str] = {
    "turn:start": "turn_start",
    "turn:end": "turn_end",
    "tool:start": "tool_start",
    "tool:end": "tool_end",
    "tool:output": "tool_output",
    "session:start": "session_start",
    "session:end": "session_end",
}
RISKS = {"safe": "SAFE", "write": "WRITE", "dangerous": "DANGEROUS"}


class PluginError(RuntimeError):
    """A plugin asked for something the context will not do."""


class PluginContext:
    """The one object a plugin's ``register`` receives."""

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name
        self.tools: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Callable[[Any], None]]] = []
        self.commands: list[tuple[str, Callable[[argparse.Namespace], int]]] = []
        self.notes: list[str] = []

    def tool(self, name: str, description: str, parameters: dict[str, Any],
             handler: Callable[..., Any], risk: str = "safe") -> None:
        """Register a tool. It enters the registry like any other, and its
        calls pass the same permission gate — the plugin is a guest there."""
        if not NAME_PATTERN.match(name):
            raise PluginError(f"tool name {name!r} is not usable — lowercase "
                              "letters, digits and underscores, starting "
                              "with a letter")
        if not callable(handler):
            raise PluginError("a tool needs a callable handler")
        if risk.lower() not in RISKS:
            raise PluginError(f"risk {risk!r} is not one of safe, write, dangerous")
        if not isinstance(parameters, dict):
            raise PluginError("parameters must be a JSON schema (a dict)")
        self.tools.append({
            "name": name,
            "description": str(description or "").strip()
                           or f"The {name} tool.",
            "parameters": parameters,
            "handler": handler,
            "risk": RISKS[risk.lower()],
        })

    def on(self, hook: str, callback: Callable[[Any], None]) -> None:
        """Subscribe to a lifecycle event. Aliases like ``turn:end`` map to
        the bus's own kinds; anything else is refused at load, not at run."""
        kind = HOOK_ALIASES.get(hook.strip().lower())
        if kind is None:
            raise PluginError(
                f"unknown hook {hook!r} — known: {', '.join(sorted(HOOK_ALIASES))}")
        if not callable(callback):
            raise PluginError("a hook needs a callable")
        self.hooks.append((kind, callback))

    def command(self, name: str, handler: Callable[[argparse.Namespace], int],
                help: str = "") -> None:
        """Add one CLI subcommand under ``comodor plugin run``. The handler
        receives the parsed namespace and returns an exit code."""
        if not NAME_PATTERN.match(name):
            raise PluginError(f"command name {name!r} is not usable")
        if not callable(handler):
            raise PluginError("a command needs a callable handler")
        self.commands.append((name, handler))
        if help:
            self.notes.append(help)

    def note(self, text: str) -> None:
        """A line the plugin wants visible in ``comodor plugins list``."""
        if text:
            self.notes.append(str(text))
