"""The macOS backend. Every ctypes binding for the Mac lives here.

One file per platform, beside `win32.py`, with the same handful of functions -
nothing above this module knows what a CGEvent is.

Two things macOS does differently from Windows, and the trap in each:

**Two coordinate spaces.** macOS measures the screen in *points*; a Retina
display has two pixels to a point. Every CGEvent and every display bound is in
points, while this feature - and `win32.py` - work in pixels, because a
screenshot is pixels and the coordinate conversion in `Shot.to_screen`
produces pixels. So every coordinate crossing this file converts by the
display's scale factor. Multi-monitor setups with *mixed* scales are folded to
one assumption (a pixel is a point times the scale of the display it is on);
the common single-scale case is exact.

**Permission, not API.** Windows lets a process move the mouse and read the
screen unless something says no. macOS says no by default, twice: input needs
Accessibility, screenshots need Screen Recording, and both are granted in
System Settings by a person, not by code. Every entry point here asks the
preflight check first and, refused, raises an error naming the exact settings
page - a raw `CGDisplayCreateImage` failure would instead surface as a black
rectangle or a cryptic null, neither of which tells anybody anything.

Capture draws the display's image through a bitmap context rather than
returning the provider's bytes directly: the context is created in the one
pixel layout the rest of this package expects (top-down BGRA), and CoreGraphics
does the scaling on the way, the same job `StretchBlt` does on Windows.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass

if sys.platform != "darwin":                     # pragma: no cover - guarded above
    raise ImportError("comodor.desktop.quartz is for macOS")

cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
his = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

kCGHIDEventTap = 0

kCGEventLeftMouseDown, kCGEventLeftUp = 1, 2
kCGEventRightMouseDown, kCGEventRightUp = 3, 4
kCGEventMouseMoved = 5
kCGEventOtherMouseDown, kCGEventOtherMouseUp = 25, 26

kCGMouseButtonLeft, kCGMouseButtonRight, kCGMouseButtonCenter = 0, 1, 2

kCGScrollEventUnitLine = 1

kCGWindowListOptionOnScreenOnly = 1
kCGNullWindowID = 0

kCFStringEncodingUTF8 = 0x08000100
kCFNumberFloat64Type = 6
kCFNumberIntType = 9

#: The one supported bitmap layout that is top-down BGRA - what `png.encode`
#: expects and what the Windows capture produces. Verified pixel for pixel
#: against a synthetic display before anything here trusted it.
_PREMULTIPLIED_FIRST = 2
_BYTE_ORDER_32_LITTLE = 2 << 12
BITMAP_LAYOUT = _PREMULTIPLIED_FIRST | _BYTE_ORDER_32_LITTLE


# --------------------------------------------------------------------------- #
# structures
# --------------------------------------------------------------------------- #


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


@dataclass(frozen=True)
class Rect:
    """A rectangle in *pixels* - the unit the rest of this package speaks."""

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


# --------------------------------------------------------------------------- #
# bindings
# --------------------------------------------------------------------------- #

cg.CGGetActiveDisplayList.restype = ctypes.c_int32
cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32,
                                      ctypes.POINTER(ctypes.c_uint32),
                                      ctypes.POINTER(ctypes.c_uint32)]
cg.CGDisplayBounds.restype = CGRect
cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t
cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
cg.CGDisplayCreateImage.restype = ctypes.c_void_p
cg.CGDisplayCreateImage.argtypes = [ctypes.c_uint32]
cg.CGBitmapContextCreate.restype = ctypes.c_void_p
cg.CGBitmapContextCreate.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                     ctypes.c_size_t, ctypes.c_size_t,
                                     ctypes.c_size_t, ctypes.c_void_p,
                                     ctypes.c_uint32]
cg.CGBitmapContextGetData.restype = ctypes.c_void_p
cg.CGBitmapContextGetData.argtypes = [ctypes.c_void_p]
cg.CGContextDrawImage.restype = None
cg.CGContextDrawImage.argtypes = [ctypes.c_void_p, CGRect, ctypes.c_void_p]
cg.CGEventCreate.restype = ctypes.c_void_p
cg.CGEventCreate.argtypes = [ctypes.c_void_p]
cg.CGEventGetLocation.restype = CGPoint
cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                       CGPoint, ctypes.c_uint32]
cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
cg.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                             ctypes.c_uint32, ctypes.c_int32,
                                             ctypes.c_int32]
cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16,
                                          ctypes.c_bool]
cg.CGEventKeyboardSetUnicodeString.restype = None
cg.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p,
                                               ctypes.c_ulong,
                                               ctypes.POINTER(ctypes.c_ushort)]
cg.CGEventPost.restype = None
cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
cg.CGPreflightScreenCaptureAccess.argtypes = []
cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
cg.CGColorSpaceCreateDeviceRGB.argtypes = []

his.AXIsProcessTrusted.restype = ctypes.c_bool
his.AXIsProcessTrusted.argtypes = []
try:                                             # 10.15 and later
    cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    cg.CGSessionCopyCurrentDictionary.argtypes = []
except AttributeError:                           # pragma: no cover
    pass

cf.CFArrayGetCount.restype = ctypes.c_long
cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
cf.CFDictionaryGetValue.restype = ctypes.c_void_p
cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
cf.CFNumberGetValue.restype = ctypes.c_bool
cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_long,
                                ctypes.c_void_p]
cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                         ctypes.c_uint32]
cf.CFStringGetCString.restype = ctypes.c_bool
cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                  ctypes.c_long, ctypes.c_uint32]
cf.CFRelease.restype = None
cf.CFRelease.argtypes = [ctypes.c_void_p]


def _cfstring(text: str) -> int:
    ref = cf.CFStringCreateWithCString(None, text.encode(), kCFStringEncodingUTF8)
    return ref or 0


_KEYS = {
    name: _cfstring(name)
    for name in ("kCGWindowLayer", "kCGWindowOwnerPID", "kCGWindowBounds",
                 "kCGWindowName", "kCGWindowOwnerName")
}

_COLORSPACE = cg.CGColorSpaceCreateDeviceRGB()


# --------------------------------------------------------------------------- #
# permission
# --------------------------------------------------------------------------- #

def _screen_recording_ok() -> bool:
    try:
        return bool(cg.CGPreflightScreenCaptureAccess())
    except AttributeError:                       # pragma: no cover - pre-10.15
        return True


def _accessibility_ok() -> bool:
    return bool(his.AXIsProcessTrusted())


def missing_permissions() -> list[str]:
    """Which macOS permissions this machine has not granted, by name.

    For the doctor; the action paths below raise with the full sentence.
    """
    out = []
    if not _screen_recording_ok():
        out.append("Screen Recording")
    if not _accessibility_ok():
        out.append("Accessibility")
    return out


def _need_input() -> None:
    if not _accessibility_ok():
        raise PermissionError(
            "Comodor cannot move the mouse or type yet. macOS requires "
            "permission first: System Settings, Privacy & Security, "
            "Accessibility, then add the terminal Comodor runs in. "
            "Nothing was sent to the machine.")


# --------------------------------------------------------------------------- #
# displays
# --------------------------------------------------------------------------- #


@dataclass
class _Display:
    identifier: int
    bounds: CGRect                              # points, global origin
    scale: float

    @property
    def pixels(self) -> Rect:
        """The display's rectangle in the pixel space this package speaks."""
        return Rect(int(self.bounds.origin.x * self.scale),
                    int(self.bounds.origin.y * self.scale),
                    int(self.bounds.size.width * self.scale),
                    int(self.bounds.size.height * self.scale))


def _displays() -> list[_Display]:
    count = ctypes.c_uint32(0)
    ids = (ctypes.c_uint32 * 16)()
    if cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count)) != 0:
        raise OSError("CGGetActiveDisplayList failed")
    out = []
    for index in range(count.value):
        identifier = ids[index]
        bounds = cg.CGDisplayBounds(identifier)
        wide = cg.CGDisplayPixelsWide(identifier)
        scale = wide / max(bounds.size.width, 1.0)
        out.append(_Display(identifier, bounds, scale))
    if not out:
        raise OSError("no active display")
    return out


def _display_at_point(x: float, y: float, displays=None) -> _Display:
    for display in displays or _displays():
        box = display.bounds
        if (box.origin.x <= x < box.origin.x + box.size.width
                and box.origin.y <= y < box.origin.y + box.size.height):
            return display
    return (displays or _displays())[0]


def virtual_screen() -> Rect:
    """Every display, as one rectangle in pixels. Its origin can be negative."""
    boxes = [display.pixels for display in _displays()]
    left = min(box.left for box in boxes)
    top = min(box.top for box in boxes)
    right = max(box.right for box in boxes)
    bottom = max(box.bottom for box in boxes)
    return Rect(left, top, right - left, bottom - top)


def monitors() -> list[Rect]:
    """Each display's rectangle, in pixels."""
    return [display.pixels for display in _displays()]


def _frontmost_window() -> int:
    """The first on-screen window of somebody else's process, or 0.

    CGWindowListCopyWindowInfo comes back front-to-back, so the first layer-0
    window not owned by this process sits in front of everything else - which
    is the closest thing to "the window the user is working in" that Carbon
    offers without an AppKit dependency.
    """
    info = cg.CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly,
                                         kCGNullWindowID)
    if not info:
        return 0
    ours = os.getpid()
    for index in range(cf.CFArrayGetCount(info)):
        window = cf.CFArrayGetValueAtIndex(info, index)
        if not window:
            continue
        layer = ctypes.c_long(-1)
        value = cf.CFDictionaryGetValue(window, _KEYS["kCGWindowLayer"])
        if not value or not cf.CFNumberGetValue(value, kCFNumberIntType,
                                                ctypes.byref(layer)):
            continue
        if layer.value != 0:
            continue
        pid = ctypes.c_long(0)
        value = cf.CFDictionaryGetValue(window, _KEYS["kCGWindowOwnerPID"])
        if value and cf.CFNumberGetValue(value, kCFNumberIntType,
                                         ctypes.byref(pid)):
            if pid.value != ours:
                return window
    return 0


def active_monitor() -> Rect:
    """The display holding the window in front of everything else.

    The frontmost window rather than the pointer, because the pointer is about
    to be moved by the agent and would stop meaning anything the moment it did.
    """
    window = _frontmost_window()
    displays = _displays()
    if window:
        value = cf.CFDictionaryGetValue(window, _KEYS["kCGWindowBounds"])
        if value:
            def number(name: str) -> float:
                got = ctypes.c_double(0)
                entry = cf.CFDictionaryGetValue(value, _cfstring(name))
                if entry:
                    cf.CFNumberGetValue(entry, kCFNumberFloat64Type,
                                        ctypes.byref(got))
                return got.value
            # Window bounds are in points, in the same global space as the
            # display bounds; its centre names the monitor it lives on.
            x = number("X") + number("Width") / 2
            y = number("Y") + number("Height") / 2
            return _display_at_point(x, y, displays).pixels
    location = cursor()
    for display in displays:
        if display.pixels.contains(*location):
            return display.pixels
    return displays[0].pixels


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #


def _capture_display(identifier: int) -> int:
    """The display's image, or a refusal that says what to do about it."""
    if not _screen_recording_ok():
        raise PermissionError(
            "Comodor cannot take a screenshot yet. macOS requires permission "
            "first: System Settings, Privacy & Security, Screen Recording, "
            "then add the terminal Comodor runs in and restart it. "
            "No pixels were read.")
    image = cg.CGDisplayCreateImage(identifier)
    if not image:
        raise OSError("CGDisplayCreateImage returned nothing")
    return image


def _dest_rect(display: _Display, area: Rect, width: int, height: int) -> CGRect:
    """Where the display's image lands so the *area* fills the canvas.

    Derived and verified against a synthetic display, pixel for pixel: the
    image is drawn at ``k`` canvas pixels per display point, offset so the
    area's top-left corner lands exactly on the canvas's top-left. The canvas
    clips the rest. Memory row 0 of the result is the top of the area, and the
    layout is BGRA - what `png.encode` wants.
    """
    pixel_box = display.pixels
    scale = display.scale
    x0 = (area.left - pixel_box.left) / scale
    y0 = (area.top - pixel_box.top) / scale
    wide, high = display.bounds.size.width, display.bounds.size.height
    k = width / max(area.width / scale, 1e-9)
    return CGRect(CGPoint(-k * x0, height - k * (high - y0)),
                  CGSize(k * wide, k * high))


def grab(area: Rect, width: int, height: int) -> bytes:
    """A region of the screen, as top-down BGRA, scaled to ``width`` x ``height``.

    Scaling happens inside CoreGraphics, on the way from the display's image to
    a small bitmap context - the same job GDI's `StretchBlt` does on Windows.
    Resampling in Python would move millions of pixels through the interpreter
    per frame, and there are many frames.
    """
    centre = (area.left + area.width // 2, area.top + area.height // 2)
    displays = _displays()
    display = next((d for d in displays if d.pixels.contains(*centre)),
                   displays[0])

    image = _capture_display(display.identifier)
    try:
        context = cg.CGBitmapContextCreate(None, width, height, 8, width * 4,
                                           _COLORSPACE, BITMAP_LAYOUT)
        if not context:
            raise OSError("could not create the bitmap context")
        cg.CGContextDrawImage(context, _dest_rect(display, area, width, height),
                              image)
        bits = cg.CGBitmapContextGetData(context)
        if not bits:
            raise OSError("could not read the bitmap context back")
        return ctypes.string_at(bits, width * height * 4)
    finally:
        cf.CFRelease(image)


# --------------------------------------------------------------------------- #
# pointer
# --------------------------------------------------------------------------- #


def _scale_for_pixels(x: int, y: int) -> float:
    for display in _displays():
        if display.pixels.contains(x, y):
            return display.scale
    return _displays()[0].scale


def cursor() -> tuple[int, int]:
    """Where the pointer is, in pixels."""
    event = cg.CGEventCreate(None)
    if not event:
        return 0, 0
    try:
        location = cg.CGEventGetLocation(event)
    finally:
        cf.CFRelease(event)
    scale = _scale_for_pixels(int(location.x * 2), int(location.y * 2))
    return int(location.x * scale), int(location.y * scale)


def move_to(x: int, y: int) -> None:
    _need_input()
    scale = _scale_for_pixels(x, y)
    point = CGPoint(x / scale, y / scale)
    event = cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, point,
                                       kCGMouseButtonLeft)
    if not event:
        raise OSError("could not create the mouse event")
    cg.CGEventPost(kCGHIDEventTap, event)
    cf.CFRelease(event)


_BUTTONS = {
    "left": (kCGEventLeftMouseDown, kCGEventLeftUp, kCGMouseButtonLeft),
    "right": (kCGEventRightMouseDown, kCGEventRightUp, kCGMouseButtonRight),
    "middle": (kCGEventOtherMouseDown, kCGEventOtherMouseUp,
               kCGMouseButtonCenter),
}


def button(which: str, *, down: bool) -> None:
    _need_input()
    pair = _BUTTONS.get(which)
    if pair is None:
        raise ValueError(f"unknown button {which!r}")
    kind, _, identity = pair
    location = CGPoint(*_cursor_points())
    event = cg.CGEventCreateMouseEvent(None, kind if down else pair[1], location,
                                       identity)
    if not event:
        raise OSError("could not create the mouse event")
    cg.CGEventPost(kCGHIDEventTap, event)
    cf.CFRelease(event)


def _cursor_points() -> tuple[float, float]:
    x, y = cursor()
    scale = _scale_for_pixels(x, y)
    return x / scale, y / scale


def wheel(clicks: int, *, horizontal: bool = False) -> None:
    """Scroll, in lines.

    CoreGraphics scrolls horizontally the other way round from this package's
    convention - positive means left there and right here - so the horizontal
    count is negated rather than passed through.
    """
    _need_input()
    event = cg.CGEventCreateScrollWheelEvent(
        None, kCGScrollEventUnitLine, 2, 0 if horizontal else clicks,
        -clicks if horizontal else 0)
    if not event:
        raise OSError("could not create the scroll event")
    cg.CGEventPost(kCGHIDEventTap, event)
    cf.CFRelease(event)


# --------------------------------------------------------------------------- #
# keyboard
# --------------------------------------------------------------------------- #

#: Windows virtual key code -> macOS hardware keycode (the `kVK_ANSI` table).
#: The rest of this package names keys by Windows code because that is what
#: `keys.py` produces; this table is the translation. Keys with no equivalent
#: on a Mac keyboard are deliberately absent and raise, rather than silently
#: typing something else.
VK_TO_CG: dict[int, int] = {
    # control keys
    0x0D: 0x24,          # Return -> kVK_Return
    0x09: 0x30,          # Tab
    0x1B: 0x35,          # Escape
    0x20: 0x31,          # Space
    0x08: 0x33,          # Backspace -> kVK_Delete
    0x2E: 0x75,          # Delete -> kVK_ForwardDelete
    0x24: 0x73,          # Home
    0x23: 0x77,          # End
    0x21: 0x74,          # PageUp
    0x22: 0x79,          # PageDown
    0x26: 0x7E, 0x28: 0x7D, 0x25: 0x7B, 0x27: 0x7C,     # arrows

    # modifiers
    0x10: 0x38,          # Shift -> kVK_Shift
    0x11: 0x3B,          # Ctrl -> kVK_Control
    0x12: 0x3A,          # Alt -> kVK_Option
    0x5B: 0x37,          # Super/Win -> kVK_Command
    0x14: 0x39,          # CapsLock
    0x90: 0x47,          # NumLock -> kVK_ANSI_KeypadClear

    # punctuation, by the code `keys.py` assigns each symbol
    0xBD: 0x1B,          # - _
    0xBB: 0x18,          # = +
    0xDB: 0x21,          # [ {
    0xDD: 0x1E,          # ] }
    0xBA: 0x29,          # ; :
    0xDE: 0x27,          # ' "
    0xC0: 0x32,          # ` ~
    0xDC: 0x2A,          # \ |
    0xBC: 0x2B,          # , <
    0xBE: 0x2F,          # . >
    0xBF: 0x2C,          # / ?

    # the number pad
    0x6B: 0x45, 0x6D: 0x4E, 0x6A: 0x43, 0x6F: 0x4B, 0x6E: 0x41,

    # the digit row and the slash above it share keys with the pad in the
    # Windows layout but not here; slash sits with the punctuation it types.
    0x2F: 0x2C,
}
VK_TO_CG.update(dict(zip(range(0x30, 0x3A),
                         (0x1D, 0x12, 0x13, 0x14, 0x15, 0x17, 0x16, 0x1A,
                          0x1C, 0x1D), strict=True)))
VK_TO_CG.update({
    0x41: 0x00, 0x42: 0x0B, 0x43: 0x08, 0x44: 0x02, 0x45: 0x0E, 0x46: 0x03,
    0x47: 0x05, 0x48: 0x04, 0x49: 0x22, 0x4A: 0x26, 0x4B: 0x28, 0x4C: 0x25,
    0x4D: 0x2E, 0x4E: 0x2D, 0x4F: 0x1F, 0x50: 0x23, 0x51: 0x0C, 0x52: 0x0F,
    0x53: 0x01, 0x54: 0x11, 0x55: 0x20, 0x56: 0x09, 0x57: 0x0D, 0x58: 0x07,
    0x59: 0x10, 0x5A: 0x06,
})
VK_TO_CG.update(dict(zip(range(0x60, 0x6A),
                         (0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
                          0x5B, 0x5C), strict=True)))
VK_TO_CG.update(dict(zip(range(0x70, 0x7C),
                         (0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64,
                          0x65, 0x6D, 0x67, 0x6F), strict=True)))


class UnknownKeyForPlatform(ValueError):
    """A key with no equivalent on this machine's keyboard."""


def cg_keycode(vk_code: int) -> int:
    """One key, from the Windows virtual key code `keys.py` produces."""
    known = VK_TO_CG.get(vk_code)
    if known is None:
        raise UnknownKeyForPlatform(
            f"key code {vk_code:#04x} has no equivalent on a Mac keyboard")
    return known


def key(code: int, *, down: bool, extended: bool = False) -> None:
    """Press or release one key, by Windows virtual key code.

    The extended-key flag is a Windows idea - macOS keycodes name one physical
    key each, with nothing sharing a scan code - so it is accepted and ignored.
    """
    _need_input()
    event = cg.CGEventCreateKeyboardEvent(None, cg_keycode(code), down)
    if not event:
        raise OSError("could not create the keyboard event")
    cg.CGEventPost(kCGHIDEventTap, event)
    cf.CFRelease(event)


def unicode_char(character: str) -> None:
    """Type one character by its code point rather than by a key.

    The event carries the character itself, so what arrives does not depend on
    which keyboard layout is active - the same reason `win32.py` sends scan
    codes as Unicode.
    """
    _need_input()
    units = character.encode("utf-16-le")
    count = len(units) // 2
    buffer = (ctypes.c_ushort * count)(
        *struct_unpack_shorts(units))
    down = cg.CGEventCreateKeyboardEvent(None, 0, True)
    up = cg.CGEventCreateKeyboardEvent(None, 0, False)
    if not down or not up:
        raise OSError("could not create the keyboard event")
    try:
        cg.CGEventKeyboardSetUnicodeString(down, count, buffer)
        cg.CGEventKeyboardSetUnicodeString(up, count, buffer)
        cg.CGEventPost(kCGHIDEventTap, down)
        cg.CGEventPost(kCGHIDEventTap, up)
    finally:
        cf.CFRelease(down)
        cf.CFRelease(up)


def struct_unpack_shorts(data: bytes) -> list[int]:
    return [int.from_bytes(data[i:i + 2], "little")
            for i in range(0, len(data), 2)]


# --------------------------------------------------------------------------- #
# what is on screen
# --------------------------------------------------------------------------- #


def foreground_title() -> str:
    """The title of the window in front, for the deny-list.

    The window's own name needs Screen Recording on modern macOS; the owning
    application's name never does. One or the other arrives, which is enough
    for a deny-list that matches on words.
    """
    window = _frontmost_window()
    if not window:
        return ""
    for key_name in ("kCGWindowName", "kCGWindowOwnerName"):
        value = cf.CFDictionaryGetValue(window, _KEYS[key_name])
        if not value:
            continue
        buffer = ctypes.create_string_buffer(256)
        if cf.CFStringGetCString(value, buffer, 256, kCFStringEncodingUTF8):
            return buffer.value.decode("utf-8", "replace")
    return ""


def screen_is_locked() -> bool:
    """Whether the login window is in front of everything.

    Read from the session dictionary - it carries a `kCGSSessionLoginwindow`
    entry exactly while the login window owns the screen. There is no stronger
    API to ask without a helper daemon, so a missing dictionary (no session to
    speak of) reads as unlocked; the guard's other checks still apply.
    """
    try:
        if not hasattr(cg, "CGSessionCopyCurrentDictionary"):
            return False
        dictionary = cg.CGSessionCopyCurrentDictionary()
        if not dictionary:
            return False
        try:
            return bool(cf.CFDictionaryGetValue(
                dictionary, _cfstring("kCGSSessionLoginwindow")))
        finally:
            cf.CFRelease(dictionary)
    except OSError:                              # pragma: no cover
        return False
