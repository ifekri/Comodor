"""A real browser, driven with nothing but the standard library."""

from .cdp import BrowserError, Session
from .launch import Browser
from .page import Element, Page, Snapshot

__all__ = ["Browser", "BrowserError", "Element", "Page", "Session", "Snapshot"]
