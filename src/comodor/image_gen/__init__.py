"""Text-to-image, deliberately small.

One tool, one adapter, one daily fuse. Generation costs real money per
call — this is not the place for a model catalogue with routing between
eleven backends; it is the place where a prompt becomes a file on disk
with its provenance written down. The registry here is one function with
a seam for a second adapter, added when there is demand, not in advance.
"""

from __future__ import annotations

from .registry import ImageGenError, generate

__all__ = ["ImageGenError", "generate"]
