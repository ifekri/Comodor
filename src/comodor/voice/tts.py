"""Text to speech, over the Edge service.

The Edge endpoint needs no key and no install — which is why it is the
default and the only provider in v1. Its protocol is not REST: one websocket,
one speech.config frame, one SSML frame, then a stream of binary frames whose
text headers mark which parts are audio. Comodor's own WebSocket client is
framing-complete for this (it already reassembles fragments and answers
pings); it only needed to hand binary frames back as bytes rather than try
to decode them as text.

Speech is off unless `voice.tts_enabled` is true, and the whole module is
inert unless `voice.enabled` is true. `synthesize` checks both itself, so a
caller that forgets to gate gets an error, not a recording leaving the
machine.
"""

from __future__ import annotations

import datetime
import uuid

from ..config import Config
from .stt import VoiceError

WSS_URL = ("wss://speech.platform.bing.com/consumer/speech/synthesize/"
           "readaloud/edge/v1?TrustedClientToken="
           "6A5AA1D4EAFF4E9FB37E23D68491D6F4")

#: What the service expects a client to look like.
HEADERS = {
    "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/130.0.0.0 Safari/537.36"),
}

#: Silence for this long while connecting means the service is not there.
CONNECT_TIMEOUT = 15.0

#: The audio format requested in the speech.config frame.
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"


def _ssml(text: str, voice: str) -> str:
    escaped = (text.replace("&", "&amp;").replace("<", "&lt;")
               .replace(">", "&gt;"))
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xml:lang="en-US">'
        f'<voice name="{voice}">{escaped}</voice></speak>')


def _speech_config() -> str:
    """The first frame: what format the audio should come back in."""
    return (
        "X-RequestId:" + uuid.uuid4().hex.upper() + "\r\n"
        "Content-Type:application/json; charset=utf-8\r\n"
        "Path:speech.config\r\n\r\n"
        '{"context":{"synthesis":{"audio":{"metadataoptions":{'
        '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
        f'"outputFormat":"{OUTPUT_FORMAT}"}}}}')


def _ssml_frame(text: str, voice: str) -> str:
    """The second frame: what to say."""
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (UTC)")
    return (
        "X-RequestId:" + uuid.uuid4().hex.upper() + "\r\n"
        "Content-Type:application/ssml+xml\r\n"
        f"X-Timestamp:{timestamp}\r\n"
        "Path:ssml\r\n\r\n" + _ssml(text, voice))


def synthesize(text: str, config: Config) -> bytes:
    """One answer, as mp3 bytes.

    Raises `VoiceError` with the reason whenever it cannot — voice off, TTS
    off, the service unreachable or refusing — rather than returning
    something that only looks like audio.
    """
    voice = config.voice
    if not voice.enabled:
        raise VoiceError(
            "voice is disabled (`voice.enabled = false`); nothing was "
            "synthesised")
    if not voice.tts_enabled:
        raise VoiceError(
            "speech is disabled (`voice.tts_enabled = false`); nothing was "
            "synthesised")
    if not text.strip():
        raise VoiceError("there is nothing to say")

    from ..net.ws import WebSocket, WebSocketError

    try:
        socket = WebSocket(WSS_URL, timeout=CONNECT_TIMEOUT, headers=HEADERS)
    except WebSocketError as error:
        raise VoiceError(f"the speech service did not connect: {error}") \
            from None

    audio = bytearray()
    try:
        socket.send(_speech_config())
        socket.send(_ssml_frame(text, voice.tts_voice))

        while True:
            frame = socket.receive()
            if isinstance(frame, bytes):
                # A binary frame is a text header, a blank line, then either
                # audio or nothing. The header's last line names the part.
                head, _, body = frame.partition(b"\r\n\r\n")
                if head.rstrip().endswith(b"Path:audio") and body:
                    audio += body
                elif not body and audio:
                    break           # an empty audio part closes the turn
            elif "Path:turn.end" in frame:
                break
    except WebSocketError as error:
        if not audio:
            raise VoiceError(
                f"the speech service stopped before sending audio: {error}") \
                from None
        # A stream cut after real audio arrived still holds usable sound.
    finally:
        socket.close()

    if not audio:
        raise VoiceError("the speech service sent no audio")
    return bytes(audio)
