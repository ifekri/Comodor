"""What an ingested file becomes in the conversation.

The routing rule is short, and everything else here is the edge cases around
it: an image goes straight to a model that has vision and becomes a readable
file for one that does not; a voice note becomes its transcript or a line
saying there was one; text and documents are summarised where they lie, with
the path in the conversation so the agent can go back and read the whole of
it with tools.

Nothing here deletes anything. A file the turn cannot use is still on disk,
still named in the conversation, and still readable next turn by whoever —
or whatever model — comes along.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..providers.profile import Profile
from .ingest import Ingested


@dataclass
class Routed:
    """What to feed the turn for one received file.

    ``text`` joins the user's message; ``images`` rides the message the way
    an attached screenshot does; ``note`` is the honest line for what could
    not be done. All three may be filled.
    """

    text: str = ""
    images: list[str] = field(default_factory=list)
    note: str = ""
    #: The path as the model should refer to it. Always set, even when the
    #: content reached the model directly, so a follow-up ("zoom into the top
    #: left") has something to act on.
    path: Path | None = None


def route(item: Ingested, profile: Profile | None,
          voice_to_text=None) -> Routed:
    """Decide what one file becomes.

    ``voice_to_text`` is a callable(path) -> str | None, injected because
    transcription belongs to whoever can do it; None means the capability is
    simply absent and the answer says so.
    """
    if item.is_image:
        return _route_image(item, profile)
    if item.is_audio:
        return _route_audio(item, voice_to_text)
    return _route_readable(item)


def _route_image(item: Ingested, profile: Profile | None) -> Routed:
    can_see = bool(profile and profile.vision)
    if not can_see:
        return Routed(
            text=(f"An image was sent ({item.describe()}, saved to "
                  f"{item.path}) but the current model cannot look at "
                  "images. Read the file with tools if that helps, or say "
                  "which model could."),
            path=item.path)
    import base64

    encoded = base64.b64encode(item.path.read_bytes()).decode("ascii")
    return Routed(images=[encoded],
                  text=f"[image: {item.path.name}]",
                  path=item.path)


def _route_audio(item: Ingested, voice_to_text) -> Routed:
    if voice_to_text is None:
        return Routed(
            text=(f"A voice note was sent ({item.describe()}, saved to "
                  f"{item.path}) but transcription is not set up. Its path "
                  "is kept; a model with audio support could be given it."),
            path=item.path)
    try:
        transcript = voice_to_text(item.path)
    except Exception as problem:
        return Routed(
            text=(f"A voice note was sent ({item.path.name}) but "
                  f"transcription failed: {problem}"),
            path=item.path)
    if not transcript:
        return Routed(text="[a voice note arrived, and it was silent]",
                      path=item.path)
    return Routed(text=f"[voice note] {transcript}", path=item.path)


def _route_readable(item: Ingested) -> Routed:
    """Text and documents: name them and let the agent read them.

    Reading the whole of a PDF into the message would spend the context on a
    file the user may only want one number from. The path plus a nudge is
    cheaper and works identically for every format a reader tool supports.
    """
    return Routed(
        text=(f"A file was sent: {item.path.name} ({item.describe()}). "
              f"Read it from {item.path} with your file tools if it is "
              "relevant."),
        path=item.path)
