"""Comodor — a self-improving terminal coding agent.

The package is layered so each piece can be used on its own:

    comodor.net        zero-dependency HTTP + SSE transport
    comodor.providers  LLM backends and the health-aware model gateway
    comodor.agent      the reason/act loop, context budgeting, prompts
    comodor.tools      the capabilities the agent can invoke
    comodor.safety     permissions, checkpoints, secret redaction
    comodor.learning   the persistent brain that makes it better over time
    comodor.session    conversation persistence and export
    comodor.ui         the Rich terminal interface
"""

__version__ = "0.1.0"
APP_NAME = "Comodor"

__all__ = ["__version__", "APP_NAME"]
