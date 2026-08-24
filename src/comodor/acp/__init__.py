"""Comodor as an agent an editor can drive, over the Agent Client Protocol.

A third interface beside the terminal and the browser, and the smallest of the
three: the agent was never the interface, so this translates the same events
into someone else's protocol rather than reimplementing anything.
"""

from .agent import PROTOCOL_VERSION, AcpSession, ComodorAgent
from .jsonrpc import Connection, RpcError

__all__ = ["ComodorAgent", "AcpSession", "Connection", "RpcError",
           "PROTOCOL_VERSION"]
