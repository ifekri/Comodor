"""LLM backends and the gateway that routes between them."""

from .base import (
    Completion,
    EventType,
    Message,
    Provider,
    ProviderError,
    Role,
    StreamEvent,
    ToolCall,
    ToolSpec,
    Usage,
    collapse,
)
from .gateway import Gateway, build_provider
from .registry import ModelInfo, context_window, estimate_cost, lookup

__all__ = [
    "Completion", "EventType", "Message", "Provider", "ProviderError", "Role",
    "StreamEvent", "ToolCall", "ToolSpec", "Usage", "collapse",
    "Gateway", "build_provider",
    "ModelInfo", "context_window", "estimate_cost", "lookup",
]
