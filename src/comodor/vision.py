"""Preparing an image for a model: read, measure, budget, remember.

The providers take base64 JPEG or PNG and will happily accept megabytes of
either — which then rides in the context every turn after. The budget here
is the honest answer: an image that already fits passes through untouched,
and an oversized one is scaled down and re-encoded as PNG, which stdlib can
do properly (zlib inflate/deflate) where JPEG would mean hand-writing a
whole codec. What cannot be decoded here is sent as it is, with a note
saying so — never silently.

The transcript keeps the source path and a hash rather than the payload,
so a fifty-image session does not become a fifty-megabyte JSONL.
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

#: The largest edge the dialects accept without downscaling surprises.
MOST_EDGE = 1568
#: The budget for one image's encoded bytes.
MOST_BYTES = 1_000_000
#: How many images one turn may carry.
MOST_PER_TURN = 4

MAGIC = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG": "png",
    b"GIF8": "gif",
    b"BM": "bmp",
}

class ImageError(ValueError):
    """The image cannot be used — named, so the model can tell the user."""

def sniff(data: bytes) -> str:
    """The format name from the leading bytes, or a refusal."""
    for magic, name in MAGIC.items():
        if data.startswith(magic):
            return name
    raise ImageError("not a recognised image (jpeg, png, gif or bmp expected)")

def from_source(source: str) -> tuple[bytes, str]:
    """The bytes and format of a local path or an http(s) URL.

    URLs are fetched through the plain session layer — the SSRF guard has
    already been applied by the caller, the only place that knows whether
    the model or the user steered here.
    """
    if source.lower().startswith(("http://", "https://")):
        from .net import http

        response = http.get(source, timeout=(10.0, 30.0))
        if not response.ok:
            raise ImageError(f"could not fetch {source}: answered "
                             f"{response.status_code}")
        data = response.content
    else:
        path = Path(source).expanduser()
        try:
            data = path.read_bytes()
        except OSError as problem:
            raise ImageError(f"could not read {source}: {problem}") from None
    if not data:
        raise ImageError(f"{source} is empty")
    if len(data) > 25_000_000:
        raise ImageError(f"{source} is over 25 MB — too large to use")
    return data, sniff(data)

def dimensions(data: bytes, fmt: str) -> tuple[int, int]:
    """Width and height, from the headers — no decoding library involved."""
    if fmt == "png":
        if data[12:16] != b"IHDR":
            raise ImageError("the png is malformed — no IHDR")
        return struct.unpack(">II", data[16:24])
    if fmt == "gif":
        return struct.unpack("<HH", data[6:10])
    if fmt == "bmp":
        return struct.unpack("<ii", data[18:26])
    if fmt == "jpeg":
        return _jpeg_dimensions(data)
    raise ImageError(f"cannot measure a {fmt} image")

def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:                   # fill byte, not a marker
            index += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = struct.unpack(">H", data[index + 2:index + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return width, height
        index += 2 + length
    raise ImageError("the jpeg is malformed — no frame header found")

# -- the budget ------------------------------------------------------------ #

def budget(data: bytes, fmt: str) -> tuple[bytes, str, bool, str]:
    """The image as the dialect wants it.

    Returns (bytes, format, resized, note). A small enough JPEG or PNG goes
    through untouched. Anything bigger is scaled once — a box average, no
    pixels invented — and re-encoded as PNG. A format that cannot be
    decoded here (jpeg, gif) is returned unchanged with a note saying the
    budget was met by luck rather than work; the caller shows that.
    """
    width, height = dimensions(data, fmt)
    if len(data) <= MOST_BYTES and max(width, height) <= MOST_EDGE:
        return data, fmt, False, ""

    if fmt not in ("png", "bmp"):
        return data, fmt, False, (
            f"larger than the {MOST_BYTES // 1_000_000} MB image budget but "
            "cannot be resized here; sent as it is")

    rows = _decode_rgb(data, fmt)
    source_w, source_h = width, height
    edge = max(width, height)
    if edge > MOST_EDGE:
        scale = MOST_EDGE / edge
        width = max(1, int(width * scale))
        height = max(1, int(height * scale))
    scaled = _box_average(rows, source_w, source_h, width, height)
    encoded = to_png(scaled, width, height)
    if len(encoded) <= MOST_BYTES:
        return encoded, "png", True, ""
    # PNG is not the last word on compression; the user's image was simply
    # hard to shrink. Honest note, honest size.
    return encoded, "png", True, (
        f"still {len(encoded) // 1024} KB after resizing; sent as PNG")

# -- decode: PNG and BMP, the two stdlib can do honestly ------------------- #

def _decode_rgb(data: bytes, fmt: str) -> bytes:
    if fmt == "bmp":
        return _decode_bmp(data)
    return _decode_png(data)

def _decode_png(data: bytes) -> bytes:
    """PNG to RGB rows. Truecolour only — palettes mean a full decoder."""
    width, height = struct.unpack(">II", data[16:24])
    bit_depth, colour = data[24], data[25]
    if bit_depth != 8 or colour not in (2, 6):          # RGB or RGBA
        raise ImageError("only 8-bit truecolour PNGs can be resized here")
    channels = 3 if colour == 2 else 4
    pieces: list[bytes] = []
    index = 8
    while index + 8 <= len(data):
        length = struct.unpack(">I", data[index:index + 4])[0]
        kind = data[index + 4:index + 8]
        if kind == b"IDAT":
            pieces.append(data[index + 8:index + 8 + length])
        index += 12 + length
        if kind == b"IEND":
            break
    if not pieces:
        raise ImageError("the png has no image data")
    try:
        raw = zlib.decompress(b"".join(pieces))
    except zlib.error as problem:
        raise ImageError(f"the png is corrupt: {problem}") from None

    stride = width * channels
    rows = bytearray(width * height * 3)
    previous = bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        if base + stride + 1 > len(raw):
            raise ImageError("the png is truncated")
        filter_kind = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        _unfilter(line, previous, filter_kind, channels)
        target = y * width * 3
        for x in range(width):
            rows[target + x * 3:target + x * 3 + 3] = \
                line[x * channels:x * channels + 3]
        previous = line
    return bytes(rows)

def _unfilter(line: bytearray, previous: bytearray, kind: int,
              channels: int) -> None:
    stride = len(line)
    if kind == 0:
        return
    if kind == 1:                        # Sub
        for i in range(channels, stride):
            line[i] = (line[i] + line[i - channels]) & 0xFF
    elif kind == 2:                      # Up
        for i in range(stride):
            line[i] = (line[i] + previous[i]) & 0xFF
    elif kind == 3:                      # Average
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            line[i] = (line[i] + (left + previous[i]) // 2) & 0xFF
    elif kind == 4:                      # Paeth
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            line[i] = (line[i] + predictor) & 0xFF
    else:
        raise ImageError(f"the png uses filter type {kind}, which is invalid")

def _decode_bmp(data: bytes) -> bytes:
    offset = struct.unpack("<I", data[10:14])[0]
    width, height = struct.unpack("<ii", data[18:26])
    bpp = struct.unpack("<H", data[28:30])[0]
    if bpp != 24:
        raise ImageError("only 24-bit BMPs can be resized here")
    rows = bytearray(abs(height) * width * 3)
    row_size = (width * 3 + 3) & ~3
    flip = height > 0
    for y in range(abs(height)):
        source = offset + y * row_size
        row = data[source:source + width * 3]
        target = (abs(height) - 1 - y) if flip else y
        for x in range(width):
            block = row[x * 3:x * 3 + 3].ljust(3, b"\0")
            rows[target * width * 3 + x * 3:target * width * 3 + x * 3 + 3] = \
                bytes(reversed(block))
    return bytes(rows)

# -- resize and encode ------------------------------------------------------ #

def _box_average(rows: bytes, source_w: int, source_h: int,
                 width: int, height: int) -> bytes:
    """New pixels by averaging each output pixel over the input box it covers.

    Averaging rather than nearest-neighbour, on purpose: a decimated
    screenshot drops exactly the thin lines a diagram is made of, and the
    model then describes a diagram that was never there.
    """
    if (source_w, source_h) == (width, height):
        return rows
    out = bytearray(width * height * 3)
    x_ratio, y_ratio = source_w / width, source_h / height
    for y in range(height):
        y0 = int(y * y_ratio)
        y1 = max(y0 + 1, int((y + 1) * y_ratio))
        for x in range(width):
            x0 = int(x * x_ratio)
            x1 = max(x0 + 1, int((x + 1) * x_ratio))
            r = g = b = count = 0
            for sy in range(y0, min(y1, source_h)):
                base = sy * source_w * 3
                for sx in range(x0, min(x1, source_w)):
                    index = base + sx * 3
                    r += rows[index]
                    g += rows[index + 1]
                    b += rows[index + 2]
                    count += 1
            target = (y * width + x) * 3
            out[target] = r // count
            out[target + 1] = g // count
            out[target + 2] = b // count
    return bytes(out)

def to_png(pixels: bytes, width: int, height: int) -> bytes:
    """Wrap top-down RGB rows as a truecolour PNG.

    Not the desktop encoder — that one takes BGRA frames, because a
    screenshot arrives that way, and would need padding to be handed RGB.
    Twelve lines here beat a conversion pass there.
    """
    stride = width * 3
    body = bytearray(height * (stride + 1))
    for y in range(height):
        start = y * (stride + 1)
        body[start] = 0                       # filter: none
        body[start + 1:start + 1 + stride] = pixels[y * stride:(y + 1) * stride]
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"".join((
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", header),
        _chunk(b"IDAT", zlib.compress(bytes(body), 6)),
        _chunk(b"IEND", b""),
    ))

def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

# -- the transcript's memory of an image ------------------------------------ #

def fingerprint(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()[:16]

def note_for(path: str, data: bytes, resized: bool) -> str:
    """The line the transcript keeps instead of the payload."""
    size = f"{len(data) / 1024:.0f} KB"
    shape = "resized to fit the image budget" if resized else "used as sent"
    return f"[image: {path} · {size} · {shape} · sha256:{fingerprint(data)}]"

def encode_for_model(data: bytes) -> str:
    """Base64, as the adapters expect. Call once, at the wire."""
    return base64.b64encode(data).decode("ascii")
