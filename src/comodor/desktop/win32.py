"""The Windows backend. Every ctypes binding in this feature lives here.

One file per platform, so adding macOS is adding a file rather than threading
`if sys.platform` through the logic - the same shape `browser/launch.py` uses
for finding a browser. Nothing above this module knows what an HWND is.

Three things it does, and the trap in each:

**Screen metrics.** On a display scaled to 125% or 150% - the out-of-the-box
setting on most Windows laptops - a process that has not declared itself
DPI-aware is told the screen is smaller than it is, and every coordinate it
computes is wrong by that ratio. Clicks land above and left of their target,
consistently, and the cause is invisible. `SetProcessDpiAwarenessContext` is
therefore called on import, before anything can read a metric.

**Capture.** GDI copies the screen into a bitmap, and `StretchBlt` shrinks it
on the way. That matters: the model wants an image about 1280 wide, the screen
may be 3840, and resampling four million pixels in Python is seconds per frame.
`HALFTONE` mode makes GDI average rather than drop pixels, which is the
difference between readable small text and noise.

**Input.** `SendInput` is the only way that works everywhere; the older
`mouse_event` is documented as superseded and does not cross monitors properly.
Absolute coordinates go in normalised to 0..65535 across the *virtual* desktop,
which is not the same rectangle as the primary monitor the moment a second
screen exists.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

if sys.platform != "win32":                     # pragma: no cover - guarded above
    raise ImportError("comodor.desktop.win32 is for Windows")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000          # include layered windows, which is most of them
HALFTONE = 4
DIB_RGB_COLORS = 0
BI_RGB = 0

MONITOR_DEFAULTTONEAREST = 2

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
WHEEL_DELTA = 120

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


# --------------------------------------------------------------------------- #
# DPI, once, before anything reads a metric
# --------------------------------------------------------------------------- #

def _become_dpi_aware() -> str:
    """Tell Windows we speak in real pixels.

    Without this the screen appears to be its scaled size, screenshots come
    back stretched, and every click is off by the scale factor - a bug that
    looks like bad model aim rather than a missing call.
    """
    try:
        # -4 is PER_MONITOR_AWARE_V2: correct per monitor, and correct when the
        # window is dragged between two monitors with different scaling.
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except (AttributeError, OSError):
        return "none"


AWARENESS = _become_dpi_aware()


# --------------------------------------------------------------------------- #
# structures
# --------------------------------------------------------------------------- #


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


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


def virtual_screen() -> Rect:
    """Every monitor, as one rectangle. Its origin can be negative."""
    return Rect(user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
                user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
                user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
                user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))


def monitors() -> list[Rect]:
    """Each display, in the order Windows enumerates them."""
    found: list[Rect] = []

    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def collect(handle, _dc, rect, _param):     # noqa: ANN001 - a C callback
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            box = info.rcMonitor
            found.append(Rect(box.left, box.top,
                              box.right - box.left, box.bottom - box.top))
        return True

    user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
    return found or [virtual_screen()]


def monitor_at(x: int, y: int) -> Rect:
    """The display a point is on, or the nearest one to it."""
    point = wintypes.POINT(x, y)
    handle = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        box = info.rcMonitor
        return Rect(box.left, box.top, box.right - box.left, box.bottom - box.top)
    return virtual_screen()


def active_monitor() -> Rect:
    """The display holding the window the user is working in.

    The focused window rather than the pointer, because the pointer is about to
    be moved by the agent and would stop meaning anything the moment it did.
    """
    handle = user32.GetForegroundWindow()
    if handle:
        box = wintypes.RECT()
        if user32.GetWindowRect(handle, ctypes.byref(box)):
            return monitor_at((box.left + box.right) // 2,
                              (box.top + box.bottom) // 2)
    return monitor_at(0, 0)


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #


def grab(area: Rect, width: int, height: int) -> bytes:
    """A region of the screen, as top-down BGRA, scaled to ``width`` x ``height``.

    The scaling happens in GDI rather than afterwards. The alternative -
    capture at full size, resample in Python - moves several million pixels
    through the interpreter for every frame, and there are a lot of frames.
    """
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise OSError("could not get a device context for the screen")

    memory_dc = bitmap = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            raise OSError("could not create a memory device context")

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        # Negative height asks for a top-down bitmap. A positive one is stored
        # bottom-up, and every consumer would have to know that.
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(memory_dc, ctypes.byref(info),
                                        DIB_RGB_COLORS, ctypes.byref(bits),
                                        None, 0)
        if not bitmap or not bits:
            raise OSError("could not allocate a bitmap for the screenshot")

        gdi32.SelectObject(memory_dc, bitmap)
        # HALFTONE averages the pixels it drops. Without it, shrinking a screen
        # by three throws two pixels in three away and small text turns to
        # speckle - which the model then reads wrongly rather than not at all.
        gdi32.SetStretchBltMode(memory_dc, HALFTONE)
        gdi32.SetBrushOrgEx(memory_dc, 0, 0, None)

        ok = gdi32.StretchBlt(memory_dc, 0, 0, width, height,
                              screen_dc, area.left, area.top,
                              area.width, area.height,
                              SRCCOPY | CAPTUREBLT)
        if not ok:
            raise OSError(f"StretchBlt failed: {ctypes.get_last_error()}")

        return ctypes.string_at(bits, width * height * 4)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)


# --------------------------------------------------------------------------- #
# pointer
# --------------------------------------------------------------------------- #


def cursor() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _send(*events: INPUT) -> None:
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(f"SendInput sent {sent} of {len(events)}: "
                      f"{ctypes.get_last_error()}")


def _absolute(x: int, y: int) -> tuple[int, int]:
    """Screen pixels to the 0..65535 grid SendInput wants.

    Across the *virtual* desktop, not the primary monitor: with two screens the
    two rectangles are different, and using the wrong one puts every click on
    the wrong half of the desk.
    """
    area = virtual_screen()
    span_x = max(area.width - 1, 1)
    span_y = max(area.height - 1, 1)
    return (int((x - area.left) * 65535 / span_x),
            int((y - area.top) * 65535 / span_y))


def move_to(x: int, y: int) -> None:
    dx, dy = _absolute(x, y)
    _send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(
        dx=dx, dy=dy, mouseData=0,
        dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time=0, dwExtraInfo=None)))


_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def button(which: str, *, down: bool) -> None:
    pair = _BUTTONS.get(which)
    if pair is None:
        raise ValueError(f"unknown button {which!r}")
    flag = pair[0] if down else pair[1]
    _send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(
        dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=None)))


def wheel(clicks: int, *, horizontal: bool = False) -> None:
    _send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(
        dx=0, dy=0, mouseData=clicks * WHEEL_DELTA,
        dwFlags=MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL,
        time=0, dwExtraInfo=None)))


# --------------------------------------------------------------------------- #
# keyboard
# --------------------------------------------------------------------------- #


def key(code: int, *, down: bool, extended: bool = False) -> None:
    flags = 0 if down else KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        wVk=code, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)))


def unicode_char(character: str) -> None:
    """Type one character by its code point rather than by a key.

    A virtual key code means "the key in that position", which depends on the
    layout: the model asking for `@` on an AZERTY keyboard would get something
    else entirely. A scan code sent as Unicode means the character itself, on
    every layout, including ones with no key for it at all.
    """
    for value in [ord(part) for part in character]:
        if value > 0xFFFF:                      # outside the BMP: a surrogate pair
            value -= 0x10000
            units = [0xD800 + (value >> 10), 0xDC00 + (value & 0x3FF)]
        else:
            units = [value]
        for unit in units:
            _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
                wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE, time=0,
                dwExtraInfo=None)))
            _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
                wVk=0, wScan=unit, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                time=0, dwExtraInfo=None)))


# --------------------------------------------------------------------------- #
# what is on screen
# --------------------------------------------------------------------------- #


def foreground_title() -> str:
    """The title of the window with the keyboard, for the deny-list."""
    handle = user32.GetForegroundWindow()
    if not handle:
        return ""
    length = user32.GetWindowTextLengthW(handle)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, buffer, length + 1)
    return buffer.value


def screen_is_locked() -> bool:
    """Whether the desktop is locked, so nothing is driven behind a lock screen.

    There is no direct question to ask. The reliable answer is whether the
    input desktop can be opened at all: while the machine is locked it belongs
    to Winlogon and this fails.
    """
    try:
        u = ctypes.WinDLL("user32", use_last_error=True)
        desktop = u.OpenInputDesktop(0, False, 0x0001)   # DESKTOP_READOBJECTS
        if not desktop:
            return True
        u.CloseDesktop(desktop)
        return False
    except OSError:
        return False
