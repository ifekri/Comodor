"""Speech to text, by a cloud provider the user named.

Whisper over an HTTP form is the whole protocol: one POST with the recording
and a model name, one JSON answer with the text. Groq and OpenAI both serve
the same shape, so one adapter covers both and only the endpoint differs.

The gates here are deliberate, not incidental:

* Nothing is sent unless `voice.enabled` is true. Audio off is the default
  and every entry point re-checks it, so a config loaded mid-run cannot
  switch transcription on behind a turn's back.
* Nothing is sent to a provider the user has not named. The empty
  `stt_provider` default means "no transcription", not "pick one".
* Nothing is sent with a key that is not there. A missing key refuses with
  the variable's name in the message — an error the user can act on, not a
  401 from somewhere far away.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from ..config import Config

#: Endpoint and model per provider. Both speak the Whisper API shape.
PROVIDERS: dict[str, tuple[str, str]] = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions",
             "whisper-large-v3"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions",
               "whisper-1"),
}

#: A recording is sent once and the answer is short; nothing here needs the
#: minute-scale patience a long model call does.
TIMEOUT = (10.0, 120.0)


class VoiceError(RuntimeError):
    """A voice request that cannot be made, said plainly."""


def transcriber(config: Config) -> Callable[[Path], str] | None:
    """The callable the media router wants, or None when there is none.

    Returns None — not a raising callable — for every "this is off" case,
    because the router's contract is that None means the capability is
    absent and the note it shows the user says exactly that. A configured
    provider whose gate is closed raises, so a silent fallback never
    pretends a note was transcribed.
    """
    voice = config.voice
    if not voice.enabled or not voice.stt_provider:
        return None
    if voice.stt_provider not in PROVIDERS:
        raise VoiceError(
            f"unknown transcription provider {voice.stt_provider!r} — "
            f"known ones: {', '.join(sorted(PROVIDERS))}")

    key = os.environ.get(voice.stt_key_env, "")
    if not key:
        raise VoiceError(
            f"transcription needs a key in the `{voice.stt_key_env}` "
            "environment variable; none was found, so the recording was "
            "not sent anywhere")

    from ..net import http

    url, model = PROVIDERS[voice.stt_provider]
    session = http.Session()

    def run(path: Path) -> str:
        response = session.post(
            url,
            files={"file": (path.name, path.read_bytes(),
                            "audio/mpeg")},
            data={"model": model, "response_format": "json"},
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
        if not response.ok:
            detail = response.text[:200].strip()
            raise VoiceError(
                f"{voice.stt_provider} answered {response.status_code}: "
                f"{detail or 'no detail given'}")
        return str((response.json() or {}).get("text") or "").strip()

    return run


def transcribe(path: Path, config: Config) -> str:
    """One recording, transcribed. The convenience form of `transcriber`."""
    run = transcriber(config)
    if run is None:
        raise VoiceError(
            "transcription is not configured — set `voice.enabled = true` "
            "and name a `voice.stt_provider`")
    return run(path)
