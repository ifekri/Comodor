"""Comodor — a self-improving terminal coding agent.

The package is layered so each piece can be used on its own:

    comodor.net        zero-dependency HTTP + SSE transport
    comodor.providers  LLM backends and the health-aware model gateway
    comodor.agent      the reason/act loop, context budgeting, prompts
    comodor.tools      the capabilities the agent can invoke
    comodor.safety     permissions, checkpoints, secret redaction
    comodor.learning   the persistent brain that makes it better over time
    comodor.session    conversation persistence and export
    comodor.application  the verbs a client asks for, and the session journal
    comodor.protocol   what the core and a client say to each other
    comodor.transport  `comodor core --stdio`, and the launcher for the interface
    comodor.tui        the packaged terminal interface (OpenTUI, run by Bun)
    comodor.terminal   what the commands need from a terminal: printing, a picker
"""

# Written by the build from the git tag - see [tool.hatch.version] in
# pyproject.toml. Read from a generated file rather than from package metadata
# because `importlib.metadata.version` costs a few milliseconds of import time
# on every start, and this is a program that measures its startup.
try:
    from ._version import __version__
except ImportError:                       # a source tree that was never built
    __version__ = "0.0.0+source"

APP_NAME = "Comodor"

__all__ = ["__version__", "APP_NAME"]
