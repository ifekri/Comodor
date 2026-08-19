"""Transport layer: a zero-dependency HTTP client plus an SSE reader.

``http`` is a self-contained stdlib implementation of the requests API — no
third-party HTTP stack is pulled in, which keeps Comodor installable anywhere.
``sse`` turns its streaming responses into server-sent-event frames, which is
how every LLM provider delivers tokens.
"""

from . import http, sse

__all__ = ["http", "sse"]
