"""Receiving media from the channels, and deciding what it is.

A voice note from a phone, a screenshot, a document — all of them arrive as
bytes with an unreliable name. What this module owns is the moment between
"something was downloaded" and "the agent turn sees it": the true type is
read from the bytes themselves, not from the extension a sender chose; the
size is checked before the whole file is held; and the file lands in one
managed directory, never executed, named by content rather than by whatever
the outside world called it.

Files are kept, not deleted, even when nobody can read them. A rejected
image whose path is still offered to the user is recoverable; one quietly
discarded is not.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

#: Media that arrives with no name at all keeps a small one made of what it
#: actually is, so a transcript stays readable.
KIND_WORDS = {"image": "image", "audio": "audio", "video": "video",
              "text": "text", "document": "document"}

#: Refused outright. Not a moral position: video is the one type that is
#: simultaneously large, rarely asked for, and unreadable by anything here.
BLOCKED_KINDS = {"video"}


class MediaError(ValueError):
    """A file that cannot be accepted, said plainly."""


@dataclass
class Ingested:
    """One downloaded file, typed by its own bytes."""

    path: Path
    kind: str                       # image | audio | text | document | video
    mime: str
    size: int
    #: What the sender called it, sanitized. Not part of the filename on disk
    #: — content names it — but kept so a transcript can say what arrived in
    #: the words the sender used.
    original_name: str = ""

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @property
    def is_audio(self) -> bool:
        return self.kind == "audio"

    def describe(self) -> str:
        what = KIND_WORDS.get(self.kind, self.kind)
        if self.original_name and self.original_name != "file":
            return f"{what} {self.original_name!r}, {self.size:,} bytes"
        return f"{what}, {self.size:,} bytes"


# --------------------------------------------------------------------------- #
# signatures
# --------------------------------------------------------------------------- #

#: Magic bytes, longest first. Enough formats to tell a phone's four media
#: types apart from each other and from text; anything else reads as unknown
#: binary and is stored as a document.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image", "image/png"),
    (b"\xff\xd8\xff", "image", "image/jpeg"),
    (b"GIF87a", "image", "image/gif"),
    (b"GIF89a", "image", "image/gif"),
    (b"BM", "image", "image/bmp"),
    (b"RIFF", "image", "image/webp"),           # RIFF....WEBP checked below
    (b"ID3", "audio", "audio/mpeg"),
    (b"\xff\xfb", "audio", "audio/mpeg"),        # bare MPEG audio frame
    (b"\xff\xf3", "audio", "audio/mpeg"),
    (b"\xff\xf2", "audio", "audio/mpeg"),
    (b"OggS", "audio", "audio/ogg"),
    (b"fLaC", "audio", "audio/flac"),
    (b"#!AMR", "audio", "audio/amr"),
    (b"\x00\x00\x00\x18ftypmp4", "video", "video/mp4"),
    (b"\x00\x00\x00\x20ftypmp4", "video", "video/mp4"),
    (b"ftypisom", "video", "video/mp4"),
    (b"ftypiso5", "video", "video/mp4"),
    (b"\x1aE\xdf\xa3", "video", "video/webm"),   # also audio/webm
    (b"%PDF-", "document", "application/pdf"),
    (b"PK\x03\x04", "document", "application/zip"),  # docx lives here too
    (b"\xd0\xcf\x11\xe0", "document", "application/msword"),
    (b"\x7fELF", "document", "application/x-executable"),
    (b"MZ", "document", "application/x-executable"),
)

_TEXT_SAMPLE = 4_096


def sniff(head: bytes) -> tuple[str, str]:
    """(kind, mime) from the first bytes, or ("document", ...) for the unknown."""
    for signature, kind, mime in _SIGNATURES:
        if head.startswith(signature):
            if signature == b"RIFF" and head[8:12] != b"WEBP":
                continue                     # a RIFF that is not a picture
            if signature == b"\x1aE\xdf\xa3" and b"\x42\x82" not in head[:64]:
                continue                     # webm decided by its DocType below
            return kind, mime
    if _looks_like_text(head):
        return "text", "text/plain"
    return "document", "application/octet-stream"


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    sample = head[:_TEXT_SAMPLE]
    if not sample:
        return False
    # Printable-enough. Control characters other than tab/newline/carriage
    # return mean binary, whatever the extension claimed.
    allowed = set(b"\t\n\r\x0b\x0c")
    return all(byte >= 32 or byte in allowed for byte in sample)


def _safe_stem(name: str) -> str:
    """A stem that cannot escape the directory or surprise a filesystem."""
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "").stem)
    stem = stem.strip("._") or "file"
    return stem[:60]


def ingest(data: bytes, *, name: str = "", directory: Path,
           max_mb: float = 25.0) -> Ingested:
    """Type, check, and store one download. Returns where it went.

    The size is checked on the bytes already in hand — the adapters cap the
    download itself, this cap catches everything that slipped past them.
    """
    limit = int(max_mb * 1_000_000)
    if len(data) > limit:
        raise MediaError(
            f"that file is {len(data) / 1_000_000:.1f} MB; the limit here is "
            f"{max_mb:.0f} MB — send a smaller one, or put it in the project "
            "and say where")

    kind, mime = sniff(data[:256])
    if kind in BLOCKED_KINDS:
        raise MediaError(f"{mime} is not read here — text, images, audio and "
                         "documents are")

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:16]
    suffix = _suffix_for(name, mime)
    # Named by content alone: the same file sent twice lands once, whatever
    # each sender called it, and the digest is what the transcript refers to.
    path = directory / f"{digest}{suffix}"
    path.write_bytes(data)
    return Ingested(path=path, kind=kind, mime=mime, size=len(data),
                    original_name=_safe_stem(name))


def _suffix_for(name: str, mime: str) -> str:
    """The extension to keep, preferring the one the bytes justify.

    An unknown binary keeps no extension at all: the one it arrived with is
    exactly the claim the bytes just contradicted, and ".jpg" on an executable
    is how somebody gets it opened.
    """
    known = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
             "image/webp": ".webp", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
             "audio/flac": ".flac", "audio/amr": ".amr",
             "video/mp4": ".mp4", "video/webm": ".webm",
             "application/pdf": ".pdf", "application/zip": ".zip"}
    suffix = known.get(mime, "")
    if suffix:
        return suffix
    if mime == "text/plain":
        original = Path(name or "").suffix.lower()
        if re.fullmatch(r"\.[a-z0-9]{1,8}", original):
            return original
    return ""


def describe_for_transcript(item: Ingested) -> str:
    """One line for the conversation, so what arrived stays visible later."""
    return f"[{item.describe()} — saved to {item.path}]"
