"""Plugins: the user's own tools, hooks and commands, loaded beside the core.

Everything about this package is sized to the promise it can actually keep.
A plugin is a Python file the user (or a repository they trusted) put on
disk; it may add tools, which sit in the same registry and pass the same
permission gate as built-ins; it may listen to the same lifecycle events
everything else listens to; it may add a CLI command. It may not reach the
brain, the sessions or the keys except through tools of its own — and those
ask permission, like everything else.
"""

from .api import PluginContext, PluginError
from .manager import PluginManager, PluginState

__all__ = ["PluginContext", "PluginError", "PluginManager", "PluginState",
           "load_for"]


def load_for(config) -> PluginManager:
    """The plugin manager a session should use, given a configuration.

    Both entry points call this, so a plugin applies whether the agent was
    started as an interface or invoked from a script — the same rule the
    skills registry follows, for the same reason.
    """
    manager = PluginManager(
        config.paths,
        trusted_folders=list(getattr(config.safety, "trusted_folders", ())),
    )
    manager.discover()
    return manager
