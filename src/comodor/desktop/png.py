"""Writing a PNG, because there is nothing here to write one with.

Comodor installs one package. Pillow is thirty times the size of everything
else put together, and this needs one narrow thing from it: turn a block of
pixels the operating system just handed us into bytes a model can look at.
PNG is a container around `zlib`, which is in the standard library, so that
narrow thing is about forty lines.

What arrives is what Windows produces: BGRA, top-down, four bytes a pixel. What
leaves is 8-bit RGB, because a screenshot has nothing to be transparent about
and dropping the fourth channel is a quarter off the wire.

Speed matters more than it looks. A 1280x720 frame is 921,600 pixels, and a
loop over them in Python takes the better part of a second - once per step of a
task that may have thirty. Every transformation here is therefore a slice
assignment, which runs in C: the interpreter sees four statements, not a
million iterations.
"""

from __future__ import annotations

import struct
import zlib

#: Colour type 2 is RGB with no alpha; 8 bits a channel.
_RGB = 2
_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def encode(pixels: bytes | bytearray | memoryview, width: int, height: int,
           *, level: int = 6) -> bytes:
    """A PNG, from top-down BGRA pixels.

    ``level`` is zlib's, and 6 is its default for a reason: 9 costs roughly
    twice the time for a percent or two on a screenshot, and this runs between
    a model asking to see the screen and the model seeing it.
    """
    expected = width * height * 4
    if len(pixels) != expected:
        raise ValueError(f"expected {expected} bytes for {width}x{height} BGRA, "
                         f"got {len(pixels)}")

    body = _idat(pixels, width, height, level)
    header = struct.pack(">IIBBBBB", width, height, 8, _RGB, 0, 0, 0)
    return b"".join((
        _SIGNATURE,
        _chunk(b"IHDR", header),
        _chunk(b"IDAT", body),
        _chunk(b"IEND", b""),
    ))


def _idat(pixels: bytes | bytearray | memoryview, width: int, height: int,
          level: int) -> bytes:
    """Scanlines, each behind a filter byte, deflated.

    Filter 0 - none - on every row. The clever filters pay off on photographs
    and on gradients; a screenshot is mostly flat colour and straight edges,
    where they cost time to compute and save very little. Measured on real
    frames, `Paeth` was under two percent smaller and several times slower.
    """
    source = memoryview(pixels)
    stride = width * 4
    row_bytes = width * 3

    # One buffer for the whole image, filter byte included, filled a row at a
    # time. Building a list of rows and joining it allocates twice.
    out = bytearray(height * (row_bytes + 1))

    for y in range(height):
        line = source[y * stride:(y + 1) * stride]
        start = y * (row_bytes + 1)
        out[start] = 0                       # the filter byte
        target = memoryview(out)[start + 1:start + 1 + row_bytes]
        # BGRA in, RGB out. Three strided assignments rather than a loop over
        # pixels: the channel order is a slice, not a decision made per pixel.
        target[0::3] = line[2::4]            # R
        target[1::3] = line[1::4]            # G
        target[2::3] = line[0::4]            # B

    return zlib.compress(bytes(out), level)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    """Length, type, payload, CRC - the shape every PNG chunk has."""
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def dimensions(data: bytes) -> tuple[int, int]:
    """Width and height of an encoded PNG, read from its header.

    Used to check what was produced without decoding it, and to tell a caller
    what it is looking at when the bytes came from somewhere else.
    """
    if not data.startswith(_SIGNATURE) or len(data) < 24:
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height
