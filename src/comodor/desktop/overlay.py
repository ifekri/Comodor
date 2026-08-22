"""Drawing what the agent is about to do, on top of everything.

The requirement this exists for: a person should be able to watch the mouse
move and see where it is going to click, while it happens. Not a log
afterwards - the moment before.

So the overlay draws a halo at the destination *before* the pointer sets off,
traces the path it takes, and puts a ripple where the click lands, with a
caption saying what it is doing in words. A badge in the corner shows how much
of the grant is left and how to stop it. The pointer itself travels at human
speed, which is what makes any of this watchable.

Three properties it must have, and each one is a way it could go wrong:

* **On top of everything**, or it is drawing behind the window being driven.
* **Click-through**, or it swallows the very clicks it is illustrating.
* **Never focused**, or the typing goes into a transparent canvas instead of
  the application. This one is subtle: `WS_EX_NOACTIVATE` governs every
  activation *after* the window exists, and `tk.Tk()` has already shown and
  activated it before the next line of Python runs. The keyboard has to be
  handed back explicitly, once, at the start.

It runs in its own thread with its own event loop, because tkinter owns
whichever thread creates it and the agent cannot give up its own. Everything
crossing that boundary goes through a queue; nothing here blocks the agent, and
a failure to draw never stops the work - an overlay that cannot start is a
missing picture, not a missing feature.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

#: A colour nothing else will pick, mapped to fully transparent.
KEY_COLOUR = "#010203"

#: The palette, from the Ember theme, so the overlay and the interface look
#: like the same program.
ACCENT = "#ff9d5c"
BRIGHT = "#ffd9b8"
QUIET = "#9a8f86"
ALARM = "#ff6b6b"

HALO_OUTER = 34
HALO_INNER = 15
RIPPLE_STEPS = 7
RIPPLE_SECONDS = 0.28
#: How long a caption stays after the action that wrote it.
LINGER_SECONDS = 1.6
FRAME_MS = 16


@dataclass
class _Mark:
    """One thing on the canvas, and when it stops being interesting."""

    kind: str
    at: tuple[int, int] | None
    to: tuple[int, int] | None
    caption: str
    born: float
    stage: int = 0


class Overlay:
    """A transparent window over the whole desk, showing what is happening.

    Implements the watcher protocol `Desktop` expects: `about_to` before an
    action, `did` after it.
    """

    def __init__(self, status: Callable[[], str] | None = None) -> None:
        self.status = status or (lambda: "")
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self.failed = ""

    # -- lifecycle -------------------------------------------------------- #

    def start(self) -> bool:
        """Open the window. False if this machine cannot show one."""
        if self._thread is not None:
            return not self.failed
        if sys.platform != "win32":
            self.failed = "the overlay is Windows-only so far"
            return False

        self._thread = threading.Thread(target=self._run, name="comodor-overlay",
                                        daemon=True)
        self._thread.start()
        # Worth waiting for: the first action may be a fraction of a second
        # away, and a halo that appears after the click has happened is worse
        # than none. A second is far longer than it takes.
        self._ready.wait(1.0)
        return not self.failed

    def close(self) -> None:
        """Ask the overlay thread to end, and wait for it to.

        Waiting matters: the thread has to reach its own `finally` and destroy
        the window itself. Returning early leaves a Tk object alive with no
        loop running, to be finalised by whatever thread collects it.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        self._ready.clear()

    # -- the watcher protocol --------------------------------------------- #

    def about_to(self, action: Any) -> None:
        self._queue.put(("about_to", action))

    def did(self, action: Any) -> None:
        self._queue.put(("did", action))

    def say(self, text: str, *, alarm: bool = False) -> None:
        """A line of its own - a refusal, a stop, the end of a grant."""
        self._queue.put(("say", (text, alarm)))

    # -- the thread that owns tkinter ------------------------------------- #

    def _run(self) -> None:
        try:
            self._build()
        except Exception as error:              # no display, no tk, no matter
            self.failed = f"{type(error).__name__}: {error}"
            self._ready.set()
            return

        self._ready.set()
        try:
            self._root.mainloop()
        except Exception:
            pass
        finally:
            # Destroyed here, on the thread that created it, and then let go of
            # here too. A Tk object that outlives its thread is finalised by
            # whichever thread happens to garbage-collect it, and Tcl says so
            # on the way out: "async handler deleted by the wrong thread". It
            # is printed at interpreter shutdown, long after the overlay has
            # apparently closed cleanly.
            # Everything holding a handle to the interpreter, not only the
            # root. This Overlay object lives on the main thread, so any Tk
            # object still reachable from it is finalised by the main thread
            # and Tcl complains at interpreter shutdown: "async handler
            # deleted by the wrong thread". It survived clearing the root
            # alone, and came back the moment a font cache was added - so the
            # rule is the list, not the one attribute that happened to be it.
            root, self._root = self._root, None
            self._canvas = None
            self._fonts = None
            try:
                root.destroy()
            except Exception:
                pass
            del root

    def _build(self) -> None:
        import tkinter as tk

        from . import win32

        # Whoever has the keyboard now must still have it in a moment.
        previous = win32.user32.GetForegroundWindow()

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.overrideredirect(True)
        self._root.configure(bg=KEY_COLOUR)
        self._root.attributes("-transparentcolor", KEY_COLOUR)

        area = win32.virtual_screen()
        self._origin = (area.left, area.top)
        self._root.geometry(f"{area.width}x{area.height}+{area.left}+{area.top}")
        self._canvas = tk.Canvas(self._root, bg=KEY_COLOUR, highlightthickness=0,
                                 width=area.width, height=area.height)
        self._canvas.pack()
        self._root.update_idletasks()

        self._handle = (win32.user32.GetParent(self._root.winfo_id())
                        or self._root.winfo_id())
        style = win32.user32.GetWindowLongW(self._handle, -20)   # GWL_EXSTYLE
        win32.user32.SetWindowLongW(
            self._handle, -20,
            style | 0x00080000        # LAYERED
            | 0x00000020              # TRANSPARENT - clicks pass through
            | 0x08000000              # NOACTIVATE - never takes focus
            | 0x00000080)             # TOOLWINDOW - not in the task switcher
        win32.user32.ShowWindow(self._handle, 4)                 # SHOWNOACTIVATE
        self._raise()
        if previous and previous != self._handle:
            win32.user32.SetForegroundWindow(previous)

        self._marks: list[_Mark] = []
        self._note = ""
        self._note_until = 0.0
        self._note_alarm = False
        self._root.after(FRAME_MS, self._tick)

    def _raise(self) -> None:
        from . import win32

        # Topmost, without activating. Repeated each frame is wasteful; done
        # after a full-screen application appears is not enough. Once a second
        # is the compromise, and `_tick` counts the frames.
        win32.user32.SetWindowPos(self._handle, __import__("ctypes").c_void_p(-1),
                                  0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010 | 0x0040)

    # -- the loop --------------------------------------------------------- #

    def _tick(self) -> None:
        if self._stop.is_set():
            self._root.quit()            # leaves mainloop; the finally tidies up
            return

        self._drain()
        self._paint()

        self._frames = getattr(self, "_frames", 0) + 1
        if self._frames % 60 == 0:
            # A game or a video that goes full-screen claims the top; taking it
            # back periodically is cheaper than fighting for it every frame.
            self._raise()

        self._root.after(FRAME_MS, self._tick)

    def _drain(self) -> None:
        now = time.monotonic()
        while True:
            try:
                what, payload = self._queue.get_nowait()
            except queue.Empty:
                break

            if what == "say":
                self._note, self._note_alarm = payload
                self._note_until = now + 4.0
                continue

            action = payload
            if what == "about_to":
                if action.kind == "move" and action.to:
                    self._marks.append(_Mark("target", action.at, action.to,
                                             action.caption, now))
                elif action.kind in ("click", "drag") and action.at:
                    self._marks.append(_Mark("target", None, action.at,
                                             action.caption, now))
                elif action.at:
                    self._marks.append(_Mark("caption", action.at, None,
                                             action.caption, now))
            elif what == "did" and action.kind == "click" and action.at:
                self._marks.append(_Mark("ripple", None, action.at,
                                         action.caption, now))

        cutoff = now - LINGER_SECONDS
        self._marks = [mark for mark in self._marks if mark.born > cutoff][-8:]

    def _paint(self) -> None:
        self._canvas.delete("all")
        now = time.monotonic()
        left, top = self._origin

        for mark in self._marks:
            age = now - mark.born
            if mark.kind == "target" and mark.to:
                self._halo(mark.to[0] - left, mark.to[1] - top, mark.caption, age)
                if mark.at:
                    self._trail(mark.at[0] - left, mark.at[1] - top,
                                mark.to[0] - left, mark.to[1] - top)
            elif mark.kind == "ripple" and mark.to:
                self._ripple(mark.to[0] - left, mark.to[1] - top, age)
            elif mark.kind == "caption" and mark.at:
                self._caption(mark.at[0] - left, mark.at[1] - top + 44,
                              mark.caption)

        self._badge()

    # -- the pieces ------------------------------------------------------- #

    def _halo(self, x: int, y: int, caption: str, age: float) -> None:
        """Where it is going, before it goes there."""
        self._canvas.create_oval(x - HALO_OUTER, y - HALO_OUTER,
                                 x + HALO_OUTER, y + HALO_OUTER,
                                 outline=ACCENT, width=3)
        self._canvas.create_oval(x - HALO_INNER, y - HALO_INNER,
                                 x + HALO_INNER, y + HALO_INNER,
                                 outline=BRIGHT, width=2)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            self._canvas.create_line(
                x + dx * (HALO_OUTER + 4), y + dy * (HALO_OUTER + 4),
                x + dx * (HALO_OUTER + 14), y + dy * (HALO_OUTER + 14),
                fill=ACCENT, width=2)
        if caption:
            self._caption(x, y + HALO_OUTER + 30, caption)

    def _trail(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """A dashed line from where it was to where it is going."""
        self._canvas.create_line(x0, y0, x1, y1, fill=ACCENT, width=1,
                                 dash=(6, 6))

    def _ripple(self, x: int, y: int, age: float) -> None:
        """A ring that opens where the click landed."""
        fraction = min(1.0, age / RIPPLE_SECONDS)
        if fraction >= 1.0:
            return
        radius = int(10 + fraction * 46)
        # Thinning as it grows reads as fading, which a canvas with a colour
        # key cannot do with alpha.
        width = max(1, int(4 * (1 - fraction)))
        self._canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                                 outline=BRIGHT, width=width)

    def _caption(self, x: int, y: int, text: str) -> None:
        if not text:
            return
        # Drawn twice, dark then light, so it stays readable over a white
        # window and a dark one. Cheaper and more reliable than measuring the
        # pixels underneath.
        for offset, colour in (((1, 1), "#1a1512"), ((0, 0), BRIGHT)):
            self._canvas.create_text(x + offset[0], y + offset[1], text=text,
                                     fill=colour, font=("Consolas", 12))

    def _badge(self) -> None:
        """What is left of the grant, and how to end it.

        On a panel, at the top centre. The first version put bare text in the
        top-right corner and it was unreadable on a real desktop: that corner
        already held a monitoring widget and a row of browser tabs, and amber
        text on top of them was noise. The two things worth reading here are
        how long is left and how to stop - neither can be left to compete with
        whatever the screen happens to be showing.
        """
        status = ""
        try:
            status = self.status()
        except Exception:
            pass

        now = time.monotonic()
        note = self._note if now < self._note_until else ""
        if not status and not note:
            return

        lines: list[tuple[str, str, tuple[str, int, str]]] = []
        if note:
            lines.append((note, ALARM, ("Consolas", 13, "bold")))
        if status:
            lines.append((f"Comodor · {status}", ACCENT, ("Consolas", 12, "normal")))
            lines.append(("move the mouse to a corner to stop", QUIET,
                          ("Consolas", 10, "normal")))

        widest = max(self._width_of(text, font) for text, _, font in lines)
        height = sum(font[1] + 9 for _, _, font in lines) + 12
        centre = int(self._canvas["width"]) // 2
        half = widest // 2 + 18
        top = 14

        # A panel, not bare text. The border is the same amber as the halo, so
        # the two read as one program rather than as two things on the screen.
        self._canvas.create_rectangle(centre - half, top, centre + half,
                                      top + height, fill="#161210",
                                      outline=ACCENT, width=1)

        y = top + 12
        for text, colour, font in lines:
            self._canvas.create_text(centre, y, text=text, fill=colour,
                                     font=font, anchor="n")
            y += font[1] + 9

    def _width_of(self, text: str, font: tuple[str, int, str]) -> int:
        """How wide a line will be, so the panel fits it.

        Measured rather than guessed at: the status is a countdown and a window
        name, so its length changes every second and with every application.
        """
        try:
            import tkinter.font as tkfont

            key = (font[0], font[1], font[2])
            cache = getattr(self, "_fonts", None)
            if cache is None:
                cache = self._fonts = {}
            if not isinstance(cache, dict):      # cleared as the thread ends
                return int(len(text) * font[1] * 0.62)
            measure = cache.get(key)
            if measure is None:
                measure = cache[key] = tkfont.Font(
                    family=font[0], size=font[1],
                    weight="bold" if font[2] == "bold" else "normal")
            return measure.measure(text)
        except Exception:
            return int(len(text) * font[1] * 0.62)
