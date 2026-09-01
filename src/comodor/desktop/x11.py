"""The Linux backend, for X11. Every ctypes binding lives here.

One file per platform, beside `win32.py` and `quartz.py`, with the same handful
of functions. The X11 part is honest about what it is: Xlib to look, XTest to
touch, and a Wayland session gets a refusal rather than a half that does not
work. Wayland has no protocol for one client to drive another's input, by
design - a backend that pretended otherwise would be a security hole wearing
this package's name.

X11 calls cannot be type-checked against a live server at import time here, so
argtypes are set before use and the display itself is opened lazily: importing
this module on a machine with no display must not fail, it must simply refuse
when asked to work.

Pixels and pixels. X has no points-vs-pixels split like macOS and no DPI
declarations like Windows - XGetImage hands back exactly the pixels the
monitor shows, and every coordinate is one of those. That makes this the
simplest of the three backends.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from dataclasses import dataclass

if sys.platform.startswith("win"):               # pragma: no cover - sanity
    raise ImportError("comodor.desktop.x11 is for X11, not Windows")

X11 = ctypes.util.find_library("X11")
XTST = ctypes.util.find_library("Xtst")

#: Set once, at import: whether the machine even has the libraries. A Linux
#: box without libXtst can look but not touch, and the message says which.
AVAILABLE = bool(X11)
CAN_TYPE = bool(X11 and XTST)

if X11:
    xlib = ctypes.CDLL(X11)
    xtst = ctypes.CDLL(XTST) if XTST else None

    ZPIXMAP = 2
    PROP_MODE_REPLACE = 0

    # -- bindings ----------------------------------------------------------- #

    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XCloseDisplay.restype = ctypes.c_int
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xlib.XDefaultScreen.restype = ctypes.c_int
    xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
    xlib.XScreenCount.restype = ctypes.c_int
    xlib.XScreenCount.argtypes = [ctypes.c_void_p]
    xlib.XRootWindow.restype = ctypes.c_ulong
    xlib.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XDefaultDepthOfScreen.restype = ctypes.c_int
    xlib.XDefaultDepthOfScreen.argtypes = [ctypes.c_void_p]
    xlib.XGetGeometry.restype = ctypes.c_int
    xlib.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                  ctypes.POINTER(ctypes.c_ulong),
                                  ctypes.POINTER(ctypes.c_int),
                                  ctypes.POINTER(ctypes.c_int),
                                  ctypes.POINTER(ctypes.c_uint),
                                  ctypes.POINTER(ctypes.c_uint),
                                  ctypes.POINTER(ctypes.c_uint),
                                  ctypes.POINTER(ctypes.c_uint)]
    xlib.XGetImage.restype = ctypes.c_void_p
    xlib.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                               ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                               ctypes.c_ulong, ctypes.c_int]
    xlib.XDestroyImage.restype = ctypes.c_int
    xlib.XDestroyImage.argtypes = [ctypes.c_void_p]
    xlib.XQueryPointer.restype = ctypes.c_int
    xlib.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                   ctypes.POINTER(ctypes.c_ulong),
                                   ctypes.POINTER(ctypes.c_ulong),
                                   ctypes.POINTER(ctypes.c_int),
                                   ctypes.POINTER(ctypes.c_int),
                                   ctypes.POINTER(ctypes.c_int),
                                   ctypes.POINTER(ctypes.c_int),
                                   ctypes.POINTER(ctypes.c_uint)]
    xlib.XGetInputFocus.restype = ctypes.c_int
    xlib.XGetInputFocus.argtypes = [ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_ulong),
                                    ctypes.POINTER(ctypes.c_int)]
    xlib.XFetchName.restype = ctypes.c_int
    xlib.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                ctypes.POINTER(ctypes.c_char_p)]
    xlib.XFree.restype = ctypes.c_int
    xlib.XFree.argtypes = [ctypes.c_void_p]
    xlib.XFlush.restype = ctypes.c_int
    xlib.XFlush.argtypes = [ctypes.c_void_p]

    if xtst:
        xtst.XTestFakeKeyEvent.restype = ctypes.c_int
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                           ctypes.c_bool, ctypes.c_ulong]
        xtst.XTestFakeButtonEvent.restype = ctypes.c_int
        xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                              ctypes.c_bool, ctypes.c_ulong]
        xtst.XTestFakeMotionEvent.restype = ctypes.c_int
        xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                              ctypes.c_int, ctypes.c_int,
                                              ctypes.c_ulong]


class NotAvailable(RuntimeError):
    """X11 is not here - neither the libraries nor the display."""


# --------------------------------------------------------------------------- #
# the one display connection
# --------------------------------------------------------------------------- #

#: Xlib wants one connection per thread in principle; this package drives the
#: screen from the agent's thread only, so one connection, opened on first use
#: and held, is honest and simple. The lock guards only its creation.
_connection: int | None = None
_connection_failed: str | None = None


def _display() -> int:
    """The X connection, opened once. Raises with a sentence, not an X error."""
    global _connection, _connection_failed
    if not AVAILABLE:
        raise NotAvailable(
            "Comodor could not find the X11 libraries (libX11) on this "
            "machine. Install them, or run Comodor's desktop tool on an "
            "X11 session.")
    if _connection is not None:
        return _connection
    if _connection_failed is not None:
        raise NotAvailable(_connection_failed)
    handle = xlib.XOpenDisplay(None)
    if not handle:
        _connection_failed = (
            "Comodor could not open a connection to the X server. Is a "
            "display running, and is DISPLAY set? On Wayland the answer is "
            "no by design: Wayland does not let one program drive another's "
            "input, so run Comodor's desktop tool in an X11 session "
            "(or XWayland) instead.")
        raise NotAvailable(_connection_failed)
    _connection = handle
    return handle


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass
class _Screen:
    root: ctypes.c_ulong
    rect: Rect


def _screens() -> list[_Screen]:
    d = _display()
    out = []
    for index in range(xlib.XScreenCount(d)):
        root = xlib.XRootWindow(d, index)
        width = ctypes.c_uint(0)
        height = ctypes.c_uint(0)
        # Only the size is needed; X often answers without the rest.
        if xlib.XGetGeometry(d, root, None, None, None,
                             ctypes.byref(width), ctypes.byref(height),
                             None, None):
            out.append(_Screen(root, Rect(0, 0, width.value, height.value)))
    if not out:
        raise NotAvailable("the X server reports no screens")
    return out


def virtual_screen() -> Rect:
    """Every screen, as one rectangle.

    Classic X has no global coordinate space across screens - each screen is
    its own root window with its own (0, 0). The union below is therefore the
    union of boxes that all start at the origin, which for the single-screen
    setups X11 actually runs is exactly the one screen, and for the rare
    Zaphod multi-screen is still every pixel.
    """
    boxes = [screen.rect for screen in _screens()]
    left = min(box.left for box in boxes)
    top = min(box.top for box in boxes)
    right = max(box.right for box in boxes)
    bottom = max(box.bottom for box in boxes)
    return Rect(left, top, right - left, bottom - top)


def monitors() -> list[Rect]:
    return [screen.rect for screen in _screens()]


def active_monitor() -> Rect:
    """The screen holding the window with input focus.

    Classic X gives each screen its own root window and (0, 0), so "which
    screen" is a question only a multi-screen Xinerama setup can answer, and
    it answers it through the screen the focused window's coordinates fall on.
    Single-screen - the overwhelming case - is simply that screen.
    """
    d = _display()
    focus = ctypes.c_ulong(0)
    _revert = ctypes.c_int(0)
    if xlib.XGetInputFocus(d, ctypes.byref(focus), ctypes.byref(_revert)) \
            and focus.value:
        for screen in _screens():
            if screen.root == focus.value:
                return screen.rect
    return monitors()[0]


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #


def grab(area: Rect, width: int, height: int) -> bytes:
    """A region of the screen, as top-down BGRA, scaled to ``width`` x ``height``.

    XGetImage returns the exact pixels asked for, so unlike the other backends
    the scaling happens here, in Python - one pass of slice assignments in the
    same shape `png.py` uses. It runs once per screenshot, not once per pixel.
    """
    d = _display()
    screen = _screens()[0]
    left = max(0, area.left)
    top = max(0, area.top)
    wide = min(area.width, screen.rect.right - left)
    high = min(area.height, screen.rect.bottom - top)
    if wide < 1 or high < 1:
        raise ValueError(f"the region {area} is not on any screen")

    image = xlib.XGetImage(d, screen.root, left, top, wide, high,
                           ctypes.c_ulong(~0), ZPIXMAP)
    if not image:
        raise OSError(f"XGetImage failed for {wide}x{high} at ({left}, {top})")
    try:
        depth = xlib.XDefaultDepthOfScreen(d)
        return _to_bgra(image, wide, high, depth, width, height)
    finally:
        xlib.XDestroyImage(image)


def _to_bgra(image: int, src_w: int, src_h: int, depth: int,
             dst_w: int, dst_h: int) -> bytes:
    """XImage bytes (BGRX at depth 24, ZPixmap) to top-down BGRA, scaled to
    the destination size."""
    class _XImage(ctypes.Structure):
        _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int),
                    ("xoffset", ctypes.c_int), ("format", ctypes.c_int),
                    ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int),
                    ("bitmap_unit", ctypes.c_int),
                    ("bitmap_bit_order", ctypes.c_int),
                    ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int),
                    ("bytes_per_line", ctypes.c_int),
                    ("bits_per_pixel", ctypes.c_int)]

    view = ctypes.cast(image, ctypes.POINTER(_XImage)).contents
    bpp = view.bits_per_pixel // 8
    if bpp < 3:
        raise OSError(f"the screen is {view.bits_per_pixel}-bit deep; "
                      "Comodor needs a 24- or 32-bit visual")
    source = ctypes.string_at(view.data,
                              view.bytes_per_line * view.height)

    row_bytes = dst_w * 4
    out = bytearray(dst_h * row_bytes)
    for dy in range(dst_h):
        src_row = dy * src_h // dst_h
        line = source[src_row * view.bytes_per_line:
                      (src_row + 1) * view.bytes_per_line]
        target = memoryview(out)[dy * row_bytes:(dy + 1) * row_bytes]
        for dx in range(dst_w):
            px = (dx * src_w // dst_w) * bpp
            # BGRX in memory (little-endian ZPixmap): B, G, R, spare.
            target[dx * 4 + 0] = line[px + 0]        # B
            target[dx * 4 + 1] = line[px + 1]        # G
            target[dx * 4 + 2] = line[px + 2]        # R
            target[dx * 4 + 3] = 0xFF                # A
    return bytes(out)


# --------------------------------------------------------------------------- #
# pointer
# --------------------------------------------------------------------------- #


def cursor() -> tuple[int, int]:
    d = _display()
    screen = _screens()[0]
    root = child = ctypes.c_ulong(0)
    rx = ry = wx = wy = ctypes.c_int(0)
    mask = ctypes.c_uint(0)
    if not xlib.XQueryPointer(d, screen.root, ctypes.byref(root),
                              ctypes.byref(child), ctypes.byref(rx),
                              ctypes.byref(ry), ctypes.byref(wx),
                              ctypes.byref(wy), ctypes.byref(mask)):
        return 0, 0
    return rx.value, ry.value


def move_to(x: int, y: int) -> None:
    _input_or_refuse()
    d = _display()
    if not xtst.XTestFakeMotionEvent(d, -1, x, y, 0):
        raise OSError("XTestFakeMotionEvent failed")
    xlib.XFlush(d)


_BUTTONS = {"left": 1, "middle": 2, "right": 3}


def button(which: str, *, down: bool) -> None:
    _input_or_refuse()
    number = _BUTTONS.get(which)
    if number is None:
        raise ValueError(f"unknown button {which!r}")
    d = _display()
    if not xtst.XTestFakeButtonEvent(d, number, down, 0):
        raise OSError("XTestFakeButtonEvent failed")
    xlib.XFlush(d)


def wheel(clicks: int, *, horizontal: bool = False) -> None:
    """Scroll by clicking buttons 4/5 (vertical) or 6/7 (horizontal).

    The core protocol has no scroll event; every wheel X11 has ever seen is
    emulated as button presses, and XTest can press them like any other.
    """
    _input_or_refuse()
    d = _display()
    forward = clicks >= 0
    number = (7 if forward else 6) if horizontal else (5 if forward else 4)
    for _ in range(abs(clicks)):
        if not xtst.XTestFakeButtonEvent(d, number, True, 0) \
                or not xtst.XTestFakeButtonEvent(d, number, False, 0):
            raise OSError("XTestFakeButtonEvent failed for the wheel")
    xlib.XFlush(d)


# --------------------------------------------------------------------------- #
# keyboard
# --------------------------------------------------------------------------- #


class UnknownKeyForPlatform(ValueError):
    """A key with no keysym here."""


def _input_or_refuse() -> None:
    if not CAN_TYPE:
        raise NotAvailable(
            "Comodor found libX11 but not libXtst, which is what sends input "
            "on X11. Install the Xtst library and the desktop tool will be "
            "able to act, not only look.")
    _display()


def key(code: int, *, down: bool, extended: bool = False) -> None:
    """Press or release one key, from the Windows virtual key code `keys.py`
    produces. The extended flag is a Windows idea; keysyms name one key each,
    so it is accepted and ignored."""
    _input_or_refuse()
    d = _display()
    keysym = VK_TO_KEYSYM.get(code)
    if keysym is None:
        raise UnknownKeyForPlatform(
            f"key code {code:#04x} has no X11 keysym in Comodor's table")
    keycode = _keycode_for_keysym(d, keysym)
    if not keycode:
        raise UnknownKeyForPlatform(
            f"the X server has no key for keysym {keysym:#x}")
    if not xtst.XTestFakeKeyEvent(d, keycode, down, 0):
        raise OSError("XTestFakeKeyEvent failed")
    xlib.XFlush(d)


def unicode_char(character: str) -> None:
    """Type one character by finding its keysym and key code.

    X11 has keysyms for every Unicode code point (0x1000000 + code point), and
    XKeysymToKeycode maps one to a physical key with the current modifier
    state taken into account only for the primary symbol - so characters the
    layout has no key for are typed through their keysym if the server knows
    one, and refused otherwise, rather than typing a lookalike.
    """
    _input_or_refuse()
    code_point = ord(character)
    keysym = 0x01000000 + code_point if code_point > 0xFF else \
        _LATIN1_KEYSYM.get(character, code_point)
    d = _display()
    keycode = _keycode_for_keysym(d, keysym)
    if not keycode:
        raise UnknownKeyForPlatform(
            f"the X server has no key for character {character!r}")
    if not xtst.XTestFakeKeyEvent(d, keycode, True, 0) \
            or not xtst.XTestFakeKeyEvent(d, keycode, False, 0):
        raise OSError("XTestFakeKeyEvent failed")
    xlib.XFlush(d)


#: ASCII characters whose Latin-1 code point is not their keysym: the control
#: range, where X uses its own names rather than the byte value.
_LATIN1_KEYSYM = {
    "\t": 0xFF09, "\n": 0xFF0D, "\r": 0xFF0D, "\x1b": 0xFF1B, "\x08": 0xFF08,
    "\x7f": 0xFFFF,
}


def _keycode_for_keysym(d: int, keysym: int) -> int:
    return xlib.XKeysymToKeycode(d, ctypes.c_ulong(keysym))


#: Windows virtual key code -> X11 keysym. The same table shape as
#: `quartz.py`'s, for the same reason: the rest of this package names keys by
#: Windows code, because that is what `keys.py` produces.
VK_TO_KEYSYM: dict[int, int] = {
    0x0D: 0xFF0D,        # Return
    0x09: 0xFF09,        # Tab
    0x1B: 0xFF1B,        # Escape
    0x20: 0x0020,        # Space
    0x08: 0xFF08,        # Backspace
    0x2E: 0xFFFF,        # Delete
    0x2D: 0xFF63,        # Insert
    0x24: 0xFF50,        # Home
    0x23: 0xFF57,        # End
    0x21: 0xFF55,        # PageUp
    0x22: 0xFF56,        # PageDown

    0x26: 0xFF52, 0x28: 0xFF54, 0x25: 0xFF51, 0x27: 0xFF53,     # arrows

    0x10: 0xFFE1,        # Shift
    0x11: 0xFFE3,        # Ctrl
    0x12: 0xFFE9,        # Alt
    0x5B: 0xFFEB,        # Super
    0x14: 0xFFE5,        # CapsLock
    0x90: 0xFF7F,        # NumLock
    0x91: 0xFF14,        # ScrollLock
    0x13: 0xFF13,        # Pause
    0x2C: 0xFF61,        # PrintScreen
    0x2F: 0x002F,        # slash (with the punctuation it types)

    0xBD: 0x002D,        # - _
    0xBB: 0x003D,        # = +
    0xDB: 0x005B,        # [ {
    0xDD: 0x005D,        # ] }
    0xBA: 0x003B,        # ; :
    0xDE: 0x0027,        # ' "
    0xC0: 0x0060,        # ` ~
    0xDC: 0x005C,        # \ |
    0xBC: 0x002C,        # , <
    0xBE: 0x002E,        # . >
    0xBF: 0x002F,        # / ?

    0x6B: 0xFFAB, 0x6D: 0xFFAD, 0x6A: 0xFFAA, 0x6F: 0xFFAF, 0x6E: 0xFFAE,
    # kp enter has no keysym of its own here; Return's already covers it.
}
VK_TO_KEYSYM.update(dict(zip(range(0x70, 0x7C), range(0xFFBE, 0xFFCA),
                             strict=True)))
VK_TO_KEYSYM.update(dict(zip(range(0x30, 0x3A), range(0x30, 0x3A),
                             strict=True)))
VK_TO_KEYSYM.update({
    0x41: 0x61, 0x42: 0x62, 0x43: 0x63, 0x44: 0x64, 0x45: 0x65, 0x46: 0x66,
    0x47: 0x67, 0x48: 0x68, 0x49: 0x69, 0x4A: 0x6A, 0x4B: 0x6B, 0x4C: 0x6C,
    0x4D: 0x6D, 0x4E: 0x6E, 0x4F: 0x6F, 0x50: 0x70, 0x51: 0x71, 0x52: 0x72,
    0x53: 0x73, 0x54: 0x74, 0x55: 0x75, 0x56: 0x76, 0x57: 0x77, 0x58: 0x78,
    0x59: 0x79, 0x5A: 0x7A,
})
VK_TO_KEYSYM.update(dict(zip(range(0x60, 0x6A), range(0xFFB0, 0xFFBA),
                             strict=True)))


# --------------------------------------------------------------------------- #
# what is on screen
# --------------------------------------------------------------------------- #


def foreground_title() -> str:
    """The title of the window with input focus, for the deny-list."""
    d = _display()
    focus = ctypes.c_ulong(0)
    _revert = ctypes.c_int(0)
    if not xlib.XGetInputFocus(d, ctypes.byref(focus), ctypes.byref(_revert)) \
            or not focus.value or focus.value == 1:     # 1 = PointerRoot
        return ""
    name = ctypes.c_char_p()
    if not xlib.XFetchName(d, focus.value, ctypes.byref(name)):
        return ""
    try:
        return (name.value or b"").decode("utf-8", "replace")
    finally:
        xlib.XFree(name)


def screen_is_locked() -> bool:
    """Whether the session is locked.

    There is no protocol question to ask - screen locking is a property of
    whatever locker the desktop runs, not of X. The honest answer here is the
    cheap one: XScreenSaver's extension reports idle time, not lock state, and
    guessing would either stop a legitimate session or drive a lock screen.
    The guard's deny-list and the corner still apply; this returns False and
    says so in a comment rather than pretending to know.
    """
    return False
