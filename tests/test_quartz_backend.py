"""The macOS backend, checked against the real CoreGraphics but a fake display.

The backend cannot be unit-tested end to end - `CGDisplayCreateImage` needs a
real screen and a real permission grant - but the hard part is not the screen,
it is the arithmetic: which corner of a display image lands in which corner of
the output buffer, and in which byte order. That part runs here, against real
CoreGraphics, by building images with `CGImageCreate` exactly the way the
display's capture would hand them over and running them through the backend's
own transform. A mistake there would hand the model a screenshot upside down
or in swapped colour channels - a perfectly valid PNG of nothing useful.

The permission refusals are checked as sentences, not just as exception types:
the whole point of them is to say which System Settings page to visit.
"""

from __future__ import annotations

import ctypes
import ctypes.util

import pytest

pytestmark = pytest.mark.skipif(
    ctypes.util.find_library("CoreGraphics") is None,
    reason="CoreGraphics is only on macOS")

from comodor.desktop import quartz  # noqa: E402

_cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
_cf.CFRetain.restype = ctypes.c_void_p
_cf.CFRetain.argtypes = [ctypes.c_void_p]


# --------------------------------------------------------------------------- #
# the key table
# --------------------------------------------------------------------------- #

def test_every_key_the_model_can_name_has_a_mac_equivalent():
    from comodor.desktop import keys

    named = ["return", "tab", "escape", "space", "backspace", "delete",
             "home", "end", "page_up", "page_down", "up", "down", "left",
             "right", "shift", "ctrl", "alt", "super", "capslock",
             "f1", "f12", "kp_0", "kp_enter", "minus", "equal", "comma",
             "period", "slash"]
    for name in named:
        assert keys.code_for(name) in quartz.VK_TO_CG, \
            f"{name} has no Mac keycode"

    for character in "abcdefghijklmnopqrstuvwxyz0123456789":
        assert keys.code_for(character) in quartz.VK_TO_CG, character

    for symbol, code in keys.SYMBOLS.items():
        assert code in quartz.VK_TO_CG, f"symbol {symbol!r}"


def test_a_key_with_no_mac_equivalent_refuses_with_its_code():
    with pytest.raises(quartz.UnknownKeyForPlatform):
        quartz.cg_keycode(0x13)          # Pause: no key on a Mac keyboard


def test_modifiers_map_to_the_mac_keys():
    assert quartz.cg_keycode(0x11) == 0x3B      # ctrl -> kVK_Control
    assert quartz.cg_keycode(0x5B) == 0x37      # super -> kVK_Command
    assert quartz.cg_keycode(0x12) == 0x3A      # alt -> kVK_Option


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #

def test_rect_behaves_like_every_other_backend():
    box = quartz.Rect(10, 20, 100, 50)
    assert box.right == 110 and box.bottom == 70
    assert box.contains(10, 20) and box.contains(109, 69)
    assert not box.contains(110, 20) and not box.contains(9, 20)


# --------------------------------------------------------------------------- #
# the capture transform, against real CoreGraphics
# --------------------------------------------------------------------------- #

BO32L = 2 << 12
PREMUL_FIRST = 2


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


def _display_image(pixels: bytes, width: int, height: int) -> int:
    """A display's image, built the way CGDisplayCreateImage hands it over:
    top-down BGRA bytes behind a CGDataProvider."""
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
    cspace = cg.CGColorSpaceCreateDeviceRGB()
    cg.CGDataProviderCreateWithData.restype = ctypes.c_void_p
    cg.CGDataProviderCreateWithData.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    cg.CGImageCreate.restype = ctypes.c_void_p
    cg.CGImageCreate.argtypes = [
        ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_bool, ctypes.c_int]
    data = (ctypes.c_char * len(pixels)).from_buffer(bytearray(pixels))
    provider = cg.CGDataProviderCreateWithData(
        None, ctypes.addressof(data), len(pixels), None)
    image = cg.CGImageCreate(width, height, 8, 32, width * 4, cspace,
                             PREMUL_FIRST | BO32L, provider, None, False, 0)
    assert image, "the synthetic display image did not build"
    return image


def _pixels_of(rows: list[list[bytes]], width: int) -> bytes:
    return b"".join(bytes(pixel) * width for pixel in rows)


def _classify(value: bytes) -> str:
    blue, green, red = value[0], value[1], value[2]
    if red > 200 and green < 50 and blue < 50:
        return "R"
    if green > 200 and red < 50 and blue < 50:
        return "G"
    if blue > 200 and red < 50 and green < 50:
        return "B"
    return "?"


def _capture_returns(cg_cf, image: int):
    """A fake `_capture_display`. `grab` releases what it is given, so each
    call hands back the image retained once more."""
    def capture(identifier: int) -> int:
        cg_cf.CFRetain(image)
        return image
    return capture


def test_a_whole_display_comes_back_top_down_in_bgra(monkeypatch):
    """The acceptance the whole capture path turns on: red band at the screen's
    top, blue at the bottom, and the red pixel's bytes are B-G-R in that
    order - what png.encode expects."""
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    cg.CGContextDrawImage.restype = None
    cg.CGContextDrawImage.argtypes = [ctypes.c_void_p, CGRect, ctypes.c_void_p]
    cg.CGBitmapContextCreate.restype = ctypes.c_void_p
    cg.CGBitmapContextCreate.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint32]
    cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
    cg.CGColorSpaceCreateDeviceRGB()

    # A 16x24-pixel display at scale 2: three bands of eight rows each,
    # red / green / blue.
    red, green, blue = b"\x00\x00\xff\xff", b"\x00\xff\x00\xff", \
        b"\xff\x00\x00\xff"
    pixels = b"".join((band * 16) * 8 for band in [red, green, blue])
    image = _display_image(pixels, 16, 24)

    monkeypatch.setattr(quartz, "_screen_recording_ok", lambda: True)
    # Reuse the backend's own dest-rect maths, with real CG doing the draw,
    # because _capture_display needs a screen this sandbox does not have.
    display = quartz._Display(
        1, CGRect(CGPoint(0, 0), CGSize(8, 12)), 2)
    monkeypatch.setattr(quartz, "_displays", lambda: [display])
    monkeypatch.setattr(quartz, "_capture_display", _capture_returns(_cf, image))

    out = quartz.grab(quartz.Rect(0, 0, 16, 24), 4, 6)

    assert len(out) == 4 * 6 * 4
    bands = [_classify(out[y * 16:(y + 1) * 16]) for y in range(6)]
    assert bands == ["R", "R", "G", "G", "B", "B"]
    first_pixel = out[0:4]
    assert first_pixel == red, "the pixel layout must be BGRA, top-down"


def test_a_crop_takes_the_region_asked_for(monkeypatch):
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    cg.CGContextDrawImage.restype = None
    cg.CGContextDrawImage.argtypes = [ctypes.c_void_p, CGRect, ctypes.c_void_p]
    cg.CGBitmapContextCreate.restype = ctypes.c_void_p
    cg.CGBitmapContextCreate.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint32]
    cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
    cg.CGColorSpaceCreateDeviceRGB()

    red, green, blue = b"\x00\x00\xff\xff", b"\x00\xff\x00\xff", \
        b"\xff\x00\x00\xff"
    pixels = b"".join((band * 16) * 8 for band in [red, green, blue])
    image = _display_image(pixels, 16, 24)

    display = quartz._Display(
        1, CGRect(CGPoint(0, 0), CGSize(8, 12)), 2)
    monkeypatch.setattr(quartz, "_displays", lambda: [display])
    monkeypatch.setattr(quartz, "_capture_display", _capture_returns(_cf, image))

    # The bottom band only: screen pixels y 16..24.
    out = quartz.grab(quartz.Rect(0, 16, 16, 8), 4, 2)
    assert [_classify(out[y * 16:(y + 1) * 16]) for y in range(2)] == ["B", "B"]

    # The middle band: green all the way down.
    out = quartz.grab(quartz.Rect(0, 8, 16, 8), 4, 2)
    assert [_classify(out[y * 16:(y + 1) * 16]) for y in range(2)] == ["G", "G"]

    # The top band: red.
    out = quartz.grab(quartz.Rect(0, 0, 16, 8), 4, 2)
    assert [_classify(out[y * 16:(y + 1) * 16]) for y in range(2)] == ["R", "R"]


# --------------------------------------------------------------------------- #
# permission sentences
# --------------------------------------------------------------------------- #

def test_input_without_accessibility_says_which_settings_page(monkeypatch):
    monkeypatch.setattr(quartz, "_accessibility_ok", lambda: False)
    with pytest.raises(PermissionError) as error:
        quartz.move_to(5, 5)
    message = str(error.value)
    assert "System Settings" in message
    assert "Accessibility" in message
    assert "Nothing was sent" in message


def test_screenshot_without_screen_recording_says_which_settings_page(
        monkeypatch):
    monkeypatch.setattr(quartz, "_screen_recording_ok", lambda: False)
    with pytest.raises(PermissionError) as error:
        quartz._capture_display(1)
    message = str(error.value)
    assert "System Settings" in message
    assert "Screen Recording" in message
    assert "No pixels were read" in message


def test_missing_permissions_names_both_when_both_are_missing(monkeypatch):
    monkeypatch.setattr(quartz, "_screen_recording_ok", lambda: False)
    monkeypatch.setattr(quartz, "_accessibility_ok", lambda: False)
    assert quartz.missing_permissions() == ["Screen Recording", "Accessibility"]


def test_permissions_granted_raise_nothing(monkeypatch):
    monkeypatch.setattr(quartz, "_screen_recording_ok", lambda: True)
    monkeypatch.setattr(quartz, "_accessibility_ok", lambda: True)
    assert quartz.missing_permissions() == []


# --------------------------------------------------------------------------- #
# the scroll convention
# --------------------------------------------------------------------------- #

def test_horizontal_scroll_negates_the_sign(monkeypatch):
    """CoreGraphics scrolls left for positive; this package says positive is
    right. The backend converts, so the model never learns the difference."""
    sent = {}

    class _Fake:
        def __init__(self, *args, **kwargs):
            sent["args"] = args
            sent["kwargs"] = kwargs

    monkeypatch.setattr(quartz, "_need_input", lambda: None)
    monkeypatch.setattr(quartz.cg, "CGEventCreateScrollWheelEvent",
                        lambda *args, **kwargs: _Fake(*args, **kwargs) or 1)
    monkeypatch.setattr(quartz.cf, "CFRelease", lambda ref: None)
    monkeypatch.setattr(quartz.cg, "CGEventPost", lambda *args: None)

    quartz.wheel(3, horizontal=True)
    # (None, unit, wheel axes, vertical amount, horizontal amount): the
    # horizontal axis carries -3, negated to match this package's convention.
    assert sent["args"][3] == 0
    assert sent["args"][4] == -3
    assert sent["args"][2] == 2

    quartz.wheel(3)
    assert sent["args"][3] == 3 and sent["args"][4] == 0
