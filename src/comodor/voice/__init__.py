"""Speech in and out of the machine.

Two directions, each opt-in and each honest about what it costs:

*Text to speech* — `synthesize` — turns an answer into an mp3 with the Edge
service, which needs no key and no install. *Speech to text* — `transcribe` —
sends a recording to a cloud provider, and that is a bigger step than text
leaving the machine: a recording is a copy of a person, not a summary of what
they asked. So transcription never runs unless the user turned voice on,
named a provider, and put its key in the environment. Every gate it waits
behind is named in the error when the gate is closed.

`describe` is the honest status line the `/voice` command and the doctor
show: which provider, which voice, what is missing.
"""

from __future__ import annotations

from ..config import Config
from .stt import VoiceError, transcribe
from .tts import synthesize

__all__ = ["VoiceError", "describe", "synthesize", "transcribe"]


def describe(config: Config) -> str:
    """What voice can do right now, and what it would take to do more."""
    voice = config.voice
    if not voice.enabled:
        return ("Voice is off. Nothing is recorded, sent or synthesised. "
                "Set `voice.enabled = true` in the config to turn it on.")

    lines: list[str] = []
    if voice.stt_provider:
        import os

        key = os.environ.get(voice.stt_key_env, "")
        lines.append(f"Transcription: {voice.stt_provider}, key from "
                     f"`{voice.stt_key_env}` — " +
                     ("key found." if key else
                      "no key in the environment, so transcription will "
                      "refuse rather than send anything unnamed."))
    else:
        lines.append("Transcription: no provider set (`voice.stt_provider`). "
                     "Voice notes are kept on disk and their path offered, "
                     "but nothing is transcribed.")

    if voice.tts_enabled:
        lines.append(f"Speech: {voice.tts_provider}, voice "
                     f"{voice.tts_voice}. Answers in channels that support "
                     "it are also sent as a voice message.")
    else:
        lines.append("Speech: off (`voice.tts_enabled`).")
    return "\n".join(lines)
