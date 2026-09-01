"""The X11 backend, where a display is not available to a test.

The library may or may not be on the machine running the tests - and even
where it is, a CI container has no X server. What can be checked everywhere is
the part that does not need a connection: the key table against `keys.py` (the
same acceptance as the other backends), the pixel conversion for `png.encode`,
and the shape of the refusals - a machine without X says so in a sentence
rather than raising an Xlib error number.
"""

from __future__ import annotations

import pytest

from comodor.desktop import x11

# --------------------------------------------------------------------------- #
# the key table
# --------------------------------------------------------------------------- #

def test_every_key_the_model_can_name_has_a_keysym():
    from comodor.desktop import keys

    named = ["return", "tab", "escape", "space", "backspace", "delete",
             "insert", "home", "end", "page_up", "page_down", "up", "down",
             "left", "right", "shift", "ctrl", "alt", "super", "capslock",
             "numlock", "scrolllock", "pause", "print",
             "f1", "f12", "kp_0", "kp_9", "kp_add", "kp_divide", "minus",
             "equal", "comma", "period", "slash"]
    for name in named:
        assert keys.code_for(name) in x11.VK_TO_KEYSYM, \
            f"{name} has no keysym"

    for character in "abcdefghijklmnopqrstuvwxyz0123456789":
        assert keys.code_for(character) in x11.VK_TO_KEYSYM, character

    for symbol, code in keys.SYMBOLS.items():
        assert code in x11.VK_TO_KEYSYM, f"symbol {symbol!r}"


def test_modifier_codes_map_to_the_left_hand_keysyms():
    assert x11.VK_TO_KEYSYM[0x11] == 0xFFE3          # ctrl
    assert x11.VK_TO_KEYSYM[0x5B] == 0xFFEB          # super
    assert x11.VK_TO_KEYSYM[0x12] == 0xFFE9          # alt


def test_f_keys_are_contiguous_from_f1():
    for index in range(1, 13):
        assert x11.VK_TO_KEYSYM[0x70 + index - 1] == 0xFFBE + index - 1


# --------------------------------------------------------------------------- #
# the pixel conversion
# --------------------------------------------------------------------------- #

def test_bgrx_pixels_come_out_bgra_top_down():
    """png.encode consumes top-down BGRA; X hands over BGRX. The conversion
    also scales, so a 4x2 source through a 2x1 destination must read the one
    pixel it samples from the top-left."""
    class _FakeImage:
        pass

    # Build the raw structure _to_bgra reads: width, height, xoffset, format,
    # data, byte_order, bitmap_unit, bitmap_bit_order, bitmap_pad, depth,
    # bytes_per_line, bits_per_pixel.
    import ctypes

    class _XImage(ctypes.Structure):
        _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int),
                    ("xoffset", ctypes.c_int), ("format", ctypes.c_int),
                    ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int),
                    ("bitmap_unit", ctypes.c_int),
                    ("bitmap_bit_order", ctypes.c_int),
                    ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int),
                    ("bytes_per_line", ctypes.c_int),
                    ("bits_per_pixel", ctypes.c_int)]

    # One pixel of BGRX, in memory order B, G, R, spare: pure blue is
    # ff 00 00, pure red is 00 00 ff. A second row of black so scaling has
    # somewhere else to look.
    row0 = bytes([0xFF, 0x00, 0x00, 0x00,          # blue
                  0x00, 0x00, 0xFF, 0x00,          # red
                  0x00, 0xFF, 0x00, 0x00,          # green
                  0xFF, 0xFF, 0xFF, 0x00])         # white
    row1 = b"\x00\x00\x00\x00" * 4
    source = row0 + row1
    holder = (ctypes.c_char * len(source)).from_buffer(bytearray(source))

    view = _XImage(width=4, height=2, xoffset=0, format=2,
                   data=ctypes.addressof(holder), byte_order=0,
                   bitmap_unit=32, bitmap_bit_order=0, bitmap_pad=32,
                   depth=24, bytes_per_line=16, bits_per_pixel=32)
    image = ctypes.addressof(view)

    out = x11._to_bgra(image, 4, 2, 24, 2, 1)

    assert len(out) == 2 * 4
    # Two destination pixels from the top row: BGRX blue (ff 00 00 00) becomes
    # BGRA blue (ff 00 00 ff); the second samples the top row's green.
    assert out == bytes([0xFF, 0x00, 0x00, 0xFF,
                         0x00, 0xFF, 0x00, 0xFF])


# --------------------------------------------------------------------------- #
# the refusals
# --------------------------------------------------------------------------- #

def test_everything_refuses_with_a_sentence_when_x_is_not_there(monkeypatch):
    monkeypatch.setattr(x11, "AVAILABLE", False)
    monkeypatch.setattr(x11, "CAN_TYPE", False)
    with pytest.raises(x11.NotAvailable) as error:
        x11.grab(x11.Rect(0, 0, 8, 8), 4, 4)
    assert "libX11" in str(error.value)


@pytest.mark.skipif(not x11.AVAILABLE, reason="needs the X11 libraries")
def test_looking_without_xtst_says_so_and_typing_is_refused_too(monkeypatch):
    monkeypatch.setattr(x11, "CAN_TYPE", False)

    class _Fake:
        def __init__(self, *args, **kwargs):
            self.value = 1

    fake_display = 0x1234
    monkeypatch.setattr(x11, "_display", lambda: fake_display)
    monkeypatch.setattr(x11, "_screens", lambda: [
        x11._Screen(1, x11.Rect(0, 0, 100, 100))])
    monkeypatch.setattr(x11.xlib, "XGetImage", lambda *args: _Fake())
    monkeypatch.setattr(x11.xlib, "XDestroyImage", lambda *args: None)
    monkeypatch.setattr(x11.xlib, "XDefaultDepthOfScreen", lambda *a: 24)
    # Bypass the struct read: what matters here is who may call, not pixels.
    monkeypatch.setattr(x11, "_to_bgra", lambda *a, **k: b"\x00" * 16)

    # Capture works without Xtst: looking is not touching.
    assert x11.grab(x11.Rect(0, 0, 100, 100), 4, 4) == b"\x00" * 16

    # Input does not.
    with pytest.raises(x11.NotAvailable) as error:
        x11.move_to(5, 5)
    assert "libXtst" in str(error.value)


def test_screen_is_locked_is_honestly_false():
    """X has no lock-state question to ask; the answer is False, said rather
    than guessed at."""
    assert x11.screen_is_locked() is False


@pytest.mark.skipif(not x11.AVAILABLE, reason="needs the X11 libraries")
def test_wayland_style_failure_names_wayland(monkeypatch):
    """The refusal every Linux user without X will actually hit: no display to
    open, and the message has to say Wayland by name."""
    monkeypatch.setattr(x11, "_connection", None)
    monkeypatch.setattr(x11, "_connection_failed", None)
    monkeypatch.setattr(x11.xlib, "XOpenDisplay", lambda name: None)

    with pytest.raises(x11.NotAvailable) as error:
        x11.cursor()
    assert "Wayland" in str(error.value)
    assert "X11" in str(error.value)
