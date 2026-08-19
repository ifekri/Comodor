"""Putting the terminal into raw mode, and reading it without blocking the UI.

This is the part Rich does not do. The reader owns three responsibilities:

* **Mode setup.** Raw mode via ``termios`` on POSIX; on Windows, the console
  input handle is switched to virtual-terminal input with ``ctypes`` so the same
  escape sequences arrive on both platforms and one decoder handles both. If
  that switch fails — an old console host — it falls back to ``msvcrt`` key
  codes with the mouse disabled, and everything else still works.

* **Restoration.** Every exit path restores the console: normal exit, exception,
  Ctrl+C, or a crash. A terminal left in raw mode with mouse reporting on is
  unusable afterwards, so restoration is registered with ``atexit`` as well as
  the context manager.

* **Idle flush.** A lone ``Esc`` is indistinguishable from the start of an arrow
  key until the next byte arrives — or does not. The reader waits a few
  milliseconds and then tells the decoder to resolve it.
"""

from __future__ import annotations

import atexit
import os
import queue
import sys
import threading
import time
from typing import TextIO

from .keys import InputEvent, KeyDecoder, KeyEvent, WINDOWS_SPECIAL

IS_WINDOWS = os.name == "nt"
ESC_FLUSH_SECONDS = 0.06

# Terminal control sequences we turn on and must turn back off.
ENABLE_MOUSE = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"
DISABLE_MOUSE = "\x1b[?1006l\x1b[?1002l\x1b[?1000l"
ENABLE_PASTE = "\x1b[?2004h"
DISABLE_PASTE = "\x1b[?2004l"
ENABLE_FOCUS = "\x1b[?1004h"
DISABLE_FOCUS = "\x1b[?1004l"
SHOW_CURSOR = "\x1b[?25h"

# Windows console mode flags (wincon.h).
_ENABLE_PROCESSED_INPUT = 0x0001
_ENABLE_LINE_INPUT = 0x0002
_ENABLE_ECHO_INPUT = 0x0004
_ENABLE_WINDOW_INPUT = 0x0008
_ENABLE_MOUSE_INPUT = 0x0010
_ENABLE_EXTENDED_FLAGS = 0x0080
_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_STD_INPUT_HANDLE = -10


class TerminalInput:
    """Raw keyboard and mouse input on a background thread."""

    def __init__(self, stream: TextIO | None = None, mouse: bool = True,
                 paste: bool = True) -> None:
        self.stream = stream or sys.stdin
        self.output = sys.stdout
        self.want_mouse = mouse
        self.want_paste = paste
        self.mouse_enabled = False
        self.vt_input = not IS_WINDOWS

        self.decoder = KeyDecoder()
        self.queue: queue.Queue[InputEvent] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._saved_mode: object = None
        self._restored = False
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------- #

    def __enter__(self) -> "TerminalInput":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def start(self) -> None:
        self._enter_raw_mode()
        self._write_modes(enable=True)
        atexit.register(self.stop)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="comodor-input")
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._restored:
                return
            self._restored = True
        self._stop.set()
        self._write_modes(enable=False)
        self._exit_raw_mode()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.3)

    # -- terminal modes --------------------------------------------------- #

    def _enter_raw_mode(self) -> None:
        if IS_WINDOWS:
            self._saved_mode = _windows_set_input_mode()
            self.vt_input = bool(self._saved_mode is not None
                                 and _windows_vt_input_active())
            return
        try:
            import termios
            import tty

            fd = self.stream.fileno()
            self._saved_mode = termios.tcgetattr(fd)
            tty.setraw(fd)
        except Exception:
            self._saved_mode = None

    def _exit_raw_mode(self) -> None:
        if self._saved_mode is None:
            return
        try:
            if IS_WINDOWS:
                _windows_restore_input_mode(int(self._saved_mode))  # type: ignore[arg-type]
            else:
                import termios

                termios.tcsetattr(self.stream.fileno(), termios.TCSADRAIN,
                                  self._saved_mode)
        except Exception:
            pass

    def _write_modes(self, enable: bool) -> None:
        parts: list[str] = []
        if enable:
            if self.want_mouse and self.vt_input:
                parts.append(ENABLE_MOUSE)
                self.mouse_enabled = True
            if self.want_paste and self.vt_input:
                parts.append(ENABLE_PASTE)
            if self.vt_input:
                parts.append(ENABLE_FOCUS)
        else:
            parts.extend([DISABLE_MOUSE, DISABLE_PASTE, DISABLE_FOCUS, SHOW_CURSOR])
            self.mouse_enabled = False
        if not parts:
            return
        try:
            self.output.write("".join(parts))
            self.output.flush()
        except Exception:
            pass

    # -- reading ---------------------------------------------------------- #

    def _loop(self) -> None:
        reader = self._read_windows if IS_WINDOWS else self._read_posix
        while not self._stop.is_set():
            try:
                data = reader()
            except Exception:
                time.sleep(0.05)
                continue
            if data:
                for event in self.decoder.feed(data):
                    self.queue.put(event)
            elif self.decoder.buffer:
                # Nothing more is coming: settle any half-read sequence.
                for event in self.decoder.flush():
                    self.queue.put(event)

    def _read_posix(self) -> str:
        import select

        fd = self.stream.fileno()
        timeout = ESC_FLUSH_SECONDS if self.decoder.buffer else 0.2
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            return ""
        try:
            return os.read(fd, 4096).decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _read_windows(self) -> str:
        import msvcrt

        deadline = time.monotonic() + (ESC_FLUSH_SECONDS if self.decoder.buffer else 0.2)
        chunk: list[str] = []
        while time.monotonic() < deadline:
            if self._stop.is_set():
                break
            if not msvcrt.kbhit():
                if chunk:
                    break
                time.sleep(0.008)
                continue
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0") and not self.vt_input:
                # Legacy console: the next character identifies the special key.
                code = msvcrt.getwch()
                event = WINDOWS_SPECIAL.get(code)
                self.queue.put(event or KeyEvent("char", char=code))
                continue
            chunk.append(char)
        return "".join(chunk)

    # -- consuming -------------------------------------------------------- #

    def poll(self, limit: int = 128) -> list[InputEvent]:
        """Every event queued since the last call."""
        events: list[InputEvent] = []
        for _ in range(limit):
            try:
                events.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return events

    def wait(self, timeout: float) -> InputEvent | None:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None


# --------------------------------------------------------------------------- #
# Windows console plumbing
# --------------------------------------------------------------------------- #


def _windows_set_input_mode() -> int | None:
    """Switch the console to raw VT input. Returns the previous mode."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
        if handle == -1:
            return None
        previous = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(previous)):
            return None

        mode = previous.value
        mode &= ~(_ENABLE_LINE_INPUT | _ENABLE_ECHO_INPUT | _ENABLE_PROCESSED_INPUT)
        mode |= (_ENABLE_EXTENDED_FLAGS | _ENABLE_VIRTUAL_TERMINAL_INPUT
                 | _ENABLE_WINDOW_INPUT | _ENABLE_MOUSE_INPUT)
        if not kernel32.SetConsoleMode(handle, mode):
            # Retry without VT: an old console still gives us raw key codes.
            mode &= ~_ENABLE_VIRTUAL_TERMINAL_INPUT
            if not kernel32.SetConsoleMode(handle, mode):
                return None
        return previous.value
    except Exception:
        return None


def _windows_vt_input_active() -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
        current = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(current)):
            return False
        return bool(current.value & _ENABLE_VIRTUAL_TERMINAL_INPUT)
    except Exception:
        return False


def _windows_restore_input_mode(mode: int) -> None:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
        kernel32.SetConsoleMode(handle, mode)
    except Exception:
        pass
