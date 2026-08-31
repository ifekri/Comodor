"""Inbound media: sniffing, the caps, and the routing decision.

The fixtures are tiny real files, built in place: a PNG is a signature and a
few bytes, an "mp3" is the MPEG frame sync. The lying-file case — extension
.jpg, contents something else entirely — is the whole reason the type comes
from the bytes and not from the name.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from comodor.media.ingest import Ingested, MediaError, ingest, sniff
from comodor.media.route import route
from comodor.providers.profile import Profile

# --------------------------------------------------------------------------- #
# sniffing
# --------------------------------------------------------------------------- #


def test_a_png_is_an_image_by_its_bytes():
    kind, mime = sniff(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    assert kind == "image" and mime == "image/png"


def test_a_jpeg_is_an_image():
    kind, mime = sniff(b"\xff\xd8\xff\xe0" + b"0" * 16)
    assert kind == "image" and mime == "image/jpeg"


def test_mpeg_audio_is_audio():
    kind, mime = sniff(b"\xff\xfb\x90\x00" + b"0" * 16)
    assert kind == "audio"


def test_a_pdf_is_a_document():
    kind, mime = sniff(b"%PDF-1.7\n" + b"0" * 32)
    assert kind == "document" and mime == "application/pdf"


def test_readme_style_text_is_text():
    kind, mime = sniff(b"# The project\n\nAll about it.\n")
    assert kind == "text" and mime == "text/plain"


def test_binary_garbage_is_a_document_not_a_guess():
    kind, _ = sniff(bytes(range(64)))
    assert kind == "document"


# --------------------------------------------------------------------------- #
# the cap
# --------------------------------------------------------------------------- #


@pytest.fixture
def media_dir(tmp_path) -> Path:
    return tmp_path / "media"


def test_an_oversized_file_is_refused_not_downloaded(media_dir):
    with pytest.raises(MediaError) as problem:
        ingest(b"x" * 60, name="big.bin", directory=media_dir, max_mb=0.00005)
    assert "limit" in str(problem.value)


def test_video_is_refused_with_a_reason(media_dir):
    # A real mp4 header, small. Refused for being video, not for being big.
    with pytest.raises(MediaError) as problem:
        ingest(b"\x00\x00\x00\x18ftypmp4" + b"0" * 64, name="clip.mp4",
               directory=media_dir)
    assert "video" in str(problem.value)


# --------------------------------------------------------------------------- #
# the lying file
# --------------------------------------------------------------------------- #


def test_an_executable_named_jpg_is_stored_as_a_document(media_dir):
    # MZ is the Windows executable signature. The extension says jpg; the
    # bytes say otherwise, and the bytes win.
    item = ingest(b"MZ\x90\x00" + b"0" * 64, name="photo.jpg",
                  directory=media_dir)
    assert item.kind == "document"
    assert item.path.suffix != ".jpg"


def test_the_name_cannot_escape_the_directory(media_dir):
    item = ingest(b"hello", name="../../.env", directory=media_dir)
    assert media_dir in item.path.parents
    assert ".." not in item.path.name


def test_the_same_bytes_land_under_one_name(media_dir):
    first = ingest(b"identical", name="a.txt", directory=media_dir)
    second = ingest(b"identical", name="b.txt", directory=media_dir)
    assert first.path == second.path


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #


VISION = Profile(model="m", context=100_000, source="registry", vision=True)
BLIND = Profile(model="m", context=100_000, source="registry", vision=False)


def _image(media_dir: Path) -> Ingested:
    return ingest(b"\x89PNG\r\n\x1a\n" + b"0" * 16, name="shot.png",
                  directory=media_dir)


def test_an_image_to_a_vision_model_rides_the_message(media_dir):
    item = _image(media_dir)
    routed = route(item, VISION)
    assert routed.images, "the image should be attached"
    assert base64.b64decode(routed.images[0]) == item.path.read_bytes()


def test_an_image_to_a_blind_model_becomes_a_readable_file(media_dir):
    item = _image(media_dir)
    routed = route(item, BLIND)
    assert routed.images == []
    assert str(item.path) in routed.text
    assert "cannot" in routed.text


def test_a_voice_note_without_transcription_says_so(media_dir):
    item = ingest(b"\xff\xfb\x90\x00" + b"0" * 32, name="note.mp3",
                  directory=media_dir)
    routed = route(item, VISION, voice_to_text=None)
    assert routed.text.startswith("A voice note was sent")
    assert str(item.path) in routed.text


def test_a_voice_note_becomes_its_transcript(media_dir):
    item = ingest(b"\xff\xfb\x90\x00" + b"0" * 32, name="note.mp3",
                  directory=media_dir)
    routed = route(item, VISION,
                   voice_to_text=lambda _path: "ship the release")
    assert routed.text == "[voice note] ship the release"


def test_a_document_is_named_and_left_whole(media_dir):
    item = ingest(b"%PDF-1.7\n" + b"0" * 64, name="spec.pdf",
                  directory=media_dir)
    routed = route(item, VISION)
    assert routed.images == []
    assert str(item.path) in routed.text
    assert item.path.exists()
