"""The vision tool and the image budget behind it.

The acceptance from the spec: an image the user has reaches the model
through the same budget and wire format an attached screenshot rides;
oversized images are scaled, not refused; a model without vision is never
shown the tool; and the transcript keeps a path and a hash rather than a
base64 blob, so fifty images do not bloat the session file.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from comodor.vision import (
    MOST_EDGE,
    ImageError,
    budget,
    dimensions,
    from_source,
    note_for,
    sniff,
)

# --------------------------------------------------------------------------- #
# fixtures: real PNG bytes, built here so the decoder is exercised honestly
# --------------------------------------------------------------------------- #

def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

def make_png(width: int, height: int, fill: tuple = (10, 20, 30)) -> bytes:
    row = bytes(fill) * width
    body = bytearray(height * (width * 3 + 1))
    for y in range(height):
        start = y * (width * 3 + 1)
        body[start] = 0
        body[start + 1:start + 1 + width * 3] = row
    return b"".join((
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        _chunk(b"IDAT", zlib.compress(bytes(body))),
        _chunk(b"IEND", b""),
    ))

def make_bmp(width: int, height: int) -> bytes:
    row_size = (width * 3 + 3) & ~3
    pixels = bytes(width * height * 3)
    return (b"BM" + struct.pack("<IHHI", 14 + 40 + row_size * height, 0, 0,
                                14 + 40)
            + struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0,
                          len(pixels), 0, 0, 0, 0) + pixels)

def make_jpeg(width: int, height: int) -> bytes:
    """A header only — enough for the measurer, not a real image."""
    return (b"\xff\xd8\xff" + b"\xff\xc0" + struct.pack(">H", 17)
            + bytes([8]) + struct.pack(">HH", height, width)
            + bytes([3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11]) + b"\x00" * 20)

# --------------------------------------------------------------------------- #
# sniff and measure
# --------------------------------------------------------------------------- #

def test_formats_are_named_from_the_leading_bytes():
    assert sniff(make_png(4, 4)) == "png"
    assert sniff(make_bmp(4, 4)) == "bmp"
    assert sniff(make_jpeg(4, 4)) == "jpeg"
    with pytest.raises(ImageError):
        sniff(b"plain text, not an image")

def test_dimensions_come_from_the_headers():
    assert dimensions(make_png(64, 48), "png") == (64, 48)
    assert dimensions(make_bmp(30, 20), "bmp") == (30, 20)
    assert dimensions(make_jpeg(800, 600), "jpeg") == (800, 600)

# --------------------------------------------------------------------------- #
# the budget
# --------------------------------------------------------------------------- #

def test_a_small_image_passes_through_untouched():
    png = make_png(100, 80)
    data, fmt, resized, note = budget(png, "png")
    assert data is png and not resized and not note

def test_an_oversized_image_is_scaled_to_the_edge_and_re_encoded():
    png = make_png(MOST_EDGE + 400, 900)
    data, fmt, resized, note = budget(png, "png")
    assert resized and fmt == "png"
    # The edge is capped; the other side keeps the aspect ratio.
    assert dimensions(data, "png") == (MOST_EDGE, 717)

def test_a_jpeg_over_budget_is_sent_as_it_is_with_an_honest_note():
    jpeg = make_jpeg(2000, 2000)
    data, fmt, resized, note = budget(jpeg, "jpeg")
    assert not resized and data is jpeg
    assert "cannot be resized" in note

def test_the_transcript_keeps_a_note_not_a_payload():
    png = make_png(100, 80)
    note = note_for("diagram.png", png, False)
    assert "diagram.png" in note and "sha256:" in note
    assert "b'" not in note and "base64" not in note

def test_rgb_round_trip_preserves_the_pixels():
    png = make_png(16, 16, fill=(200, 100, 50))
    from comodor.vision import _decode_rgb

    rows = _decode_rgb(png, "png")
    assert rows[0:3] == bytes((200, 100, 50))
    assert len(rows) == 16 * 16 * 3

# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #

def test_a_local_file_is_read(tmp_path):
    png = make_png(10, 10)
    path = tmp_path / "shot.png"
    path.write_bytes(png)
    data, fmt = from_source(str(path))
    assert data == png and fmt == "png"

def test_a_missing_file_is_an_image_error_not_a_crash(tmp_path):
    with pytest.raises(ImageError):
        from_source(str(tmp_path / "nope.png"))

# --------------------------------------------------------------------------- #
# the tool, gated by capability
# --------------------------------------------------------------------------- #

def test_the_tool_is_only_advertised_for_a_vision_model(config):
    from comodor.tools.registry import ToolRegistry

    config.model = "gpt-4o"                 # known, vision-capable in the registry
    with_vision = ToolRegistry(config=config)
    config.model = "gpt-3.5-turbo"          # known, not vision-capable
    without = ToolRegistry(config=config)
    assert ("vision" in with_vision) != ("vision" in without), \
        "the tool must follow the model's capability, not nothing"

def test_the_tool_returns_the_image_and_a_note(tools, tool_context, workspace):
    png = make_png(20, 20)
    (workspace / "diagram.png").write_bytes(png)
    from comodor.tools.vision import Vision

    result = Vision().run(tool_context, source="diagram.png")
    assert result.ok
    assert result.meta["image"]
    assert "[the image follows]" in result.content
    import base64

    assert base64.b64decode(result.meta["image"]) == png

def test_the_url_path_refuses_internal_addresses(tools, tool_context):
    from comodor.tools.vision import Vision

    result = Vision().run(tool_context, source="http://127.0.0.1:8080/x.png")
    assert not result.ok
    assert "refused" in result.content

def test_an_unreadable_source_is_an_error_not_an_exception(tools,
                                                           tool_context):
    from comodor.tools.vision import Vision

    result = Vision().run(tool_context, source="definitely-missing.png")
    assert not result.ok
