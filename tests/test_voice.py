"""Voice: speech in and out, gated the way audio deserves.

The gates are the point, so the tests are mostly about them: nothing runs
while voice is off, nothing is sent to a provider the user has not named,
nothing is sent with a key that is not there — and every closed gate names
itself in the error, so a person can act on it.

The one protocol checked against a real socket is the websocket's binary
frames, because the Edge service speaks its audio that way and a client that
has only ever decoded text frames will not notice until it tries.
"""

from __future__ import annotations

import dataclasses
import socket
import struct
import threading

import pytest

from comodor.config import Config
from comodor.voice import describe
from comodor.voice.stt import VoiceError, transcribe, transcriber


@pytest.fixture
def config(tmp_path):
    return Config(paths=dataclasses.replace(
        Config().paths.ensure(), user=tmp_path / "home",
        project=tmp_path / "proj"))


def a_config(config, *, enabled=True, stt="groq", tts=False):
    config.voice.enabled = enabled
    config.voice.stt_provider = stt
    config.voice.tts_enabled = tts
    return config


# --------------------------------------------------------------------------- #
# the gates
# --------------------------------------------------------------------------- #

def test_voice_off_means_no_transcriber(config):
    a_config(config, enabled=False)
    assert transcriber(config) is None


def test_no_provider_named_means_no_transcriber(config):
    a_config(config, stt="")
    assert transcriber(config) is None


def test_a_named_provider_without_a_key_refuses_and_names_the_variable(
        config, monkeypatch):
    a_config(config)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(VoiceError, match="GROQ_API_KEY"):
        transcriber(config)


def test_an_unknown_provider_is_said_rather_than_guessed(config, monkeypatch):
    a_config(config, stt="elevenlabs")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with pytest.raises(VoiceError, match="elevenlabs"):
        transcriber(config)


def test_transcribe_without_configuration_says_what_is_missing(config):
    config.voice.enabled = False
    with pytest.raises(VoiceError, match="voice.enabled"):
        transcribe("x.wav", config)     # type: ignore[arg-type]


def test_with_a_key_a_transcriber_exists(config, monkeypatch):
    a_config(config)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert callable(transcriber(config))


# --------------------------------------------------------------------------- #
# the status line
# --------------------------------------------------------------------------- #

def test_the_status_of_off_is_off_and_honest(config):
    text = describe(a_config(config, enabled=False))
    assert "off" in text.lower()


def test_the_status_names_a_missing_key(config, monkeypatch):
    a_config(config)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert "GROQ_API_KEY" in describe(config)


def test_the_status_names_the_speech_setup(config):
    a_config(config, stt="", tts=True)
    text = describe(config)
    assert "edge" in text and "FaridNeural" in text


# --------------------------------------------------------------------------- #
# text to speech: the gates, then the protocol against a real socket
# --------------------------------------------------------------------------- #

def test_tts_off_is_an_error_not_silence(config):
    a_config(config, stt="")
    with pytest.raises(VoiceError, match="tts_enabled"):
        from comodor.voice.tts import synthesize
        synthesize("hello", config)


def test_tts_with_voice_disabled_is_an_error(config):
    config.voice.enabled = False
    config.voice.tts_enabled = True
    with pytest.raises(VoiceError, match="voice.enabled"):
        from comodor.voice.tts import synthesize
        synthesize("hello", config)


def test_empty_text_is_refused(config):
    a_config(config, stt="", tts=True)
    with pytest.raises(VoiceError, match="nothing to say"):
        from comodor.voice.tts import synthesize
        synthesize("   ", config)


def test_ssml_escapes_what_a_user_would_send():
    from comodor.voice.tts import _ssml
    out = _ssml('say <tag> & "done"', "SomeVoice")
    assert "&lt;tag&gt;" in out and "&amp;" in out
    assert '<voice name="SomeVoice">' in out


class EdgePeer:
    """The speech service, in the parts the protocol exercises.

    Completes the handshake, records the text frames, answers with a binary
    audio frame, an empty audio part, and a turn.end — the three shapes the
    reader must tell apart.
    """

    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.conn = None
        self.ready = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        self.conn, _ = self.listener.accept()
        header = b""
        while b"\r\n\r\n" not in header:
            header += self.conn.recv(1)
        assert b"Sec-WebSocket-Key" in header
        self.conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\n"
                          b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        self.ready.set()

    def read_one(self) -> str:
        assert self.conn is not None
        first, second = self.conn.recv(2)
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(self.conn.recv(2), "big")
        elif length == 127:
            length = int.from_bytes(self.conn.recv(8), "big")
        assert second & 0x80, "a client must mask its frames"
        mask = self.conn.recv(4)
        body = b""
        while len(body) < length:
            body += self.conn.recv(length - len(body))
        return bytes(b ^ mask[i % 4] for i, b in enumerate(body)).decode()

    def write_frame(self, opcode: int, payload: bytes, final: bool = True,
                    mask: bool = False) -> None:
        assert self.conn is not None
        first = (0x80 if final else 0) | opcode
        second = (0x80 if mask else 0) | (len(payload) & 0x7F)
        self.conn.sendall(struct.pack("!BB", first, second) + payload)

    def answer(self) -> None:
        head = b"X-RequestId:aa\r\nContent-Type:audio/mpeg\r\nPath:audio\r\n\r\n"
        self.write_frame(0x2, head + b"ID3" + b"\x00" * 32)
        self.write_frame(0x2, head)          # the empty audio part ends it

    def stop(self) -> None:
        for sock in (self.conn, self.listener):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass


@pytest.fixture
def edge_peer():
    try:
        peer = EdgePeer()
    except PermissionError:
        pytest.skip("cannot bind a socket in this environment")
    yield peer
    peer.stop()


def test_synthesize_collects_the_audio_and_stops_at_the_end(
        config, edge_peer, monkeypatch):
    a_config(config, stt="", tts=True)
    monkeypatch.setattr("comodor.voice.tts.WSS_URL",
                        f"ws://127.0.0.1:{edge_peer.port}/edge")
    edge_peer.ready.wait(5)

    from comodor.voice.tts import synthesize
    result = synthesize("سلام", config)

    edge_peer.ready.wait(5)
    assert result.startswith(b"ID3"), "the audio bytes, not a header, come back"
    # The two text frames the protocol wants, in order.
    first = edge_peer.read_one()
    second = edge_peer.read_one()
    assert "Path:speech.config" in first
    assert "Path:ssml" in second and "سلام" in second


def test_synthesize_against_a_dead_port_is_an_error_with_a_reason(
        config, monkeypatch):
    a_config(config, stt="", tts=True)
    monkeypatch.setattr("comodor.voice.tts.WSS_URL",
                        "wss://voice.invalid/edge")
    from comodor.voice.tts import synthesize
    with pytest.raises(VoiceError, match="did not connect"):
        synthesize("hello", config)


# --------------------------------------------------------------------------- #
# the websocket itself: binary frames
# --------------------------------------------------------------------------- #

def test_a_binary_frame_comes_back_as_bytes_not_decoded_text(edge_peer):
    """The Edge audio frames are binary; a client that decodes every frame
    as text hands back mojibake exactly when it matters."""
    from comodor.net.ws import WebSocket

    edge_peer.ready.wait(5)
    ws = WebSocket(f"ws://127.0.0.1:{edge_peer.port}/x")
    try:
        ws.send("go")
        edge_peer.read_one()
        frame = ws.receive()
        assert isinstance(frame, bytes) and frame.startswith(b"ID3")
    finally:
        ws.close()
