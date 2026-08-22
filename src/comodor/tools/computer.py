"""The computer, as one tool.

Seventeen actions behind a single `action` argument rather than seventeen
tools, for the reason `browse.py` gives about the cached prefix: every schema
is re-sent on every request, and seventeen descriptions of one desktop is
seventeen times the description of a desktop. The names and arguments are
Anthropic's, because a model trained on that vocabulary is markedly better at
using it than at anything invented here, and the same names work as an ordinary
function tool for every other provider.

**This tool does not use the ordinary permission gate**, and the override is
deliberate. `Tool.invoke` asks once and remembers the answer for the session;
for something that can do anything at all to a machine, "allowed once" is not a
limit anybody meant to give. It is replaced by :class:`Guard`, which is asked
again before every single action and carries a clock, a scope and a way out.
The mode check is kept - plan mode still blocks it - by calling the engine's
own `mode_allows`.

What comes back is a sentence, not a dump. `left_click` answers "clicked at
(842, 517)" rather than a fresh screenshot, because a screenshot after every
click is a thousand tokens the model did not ask for and usually cannot use.
`screenshot` and `zoom` are the verbs that cost pixels, and the model chooses
when to spend them.

One thing the tool says out loud that most do not: **typed is not the same as
arrived**. Windows 11's Notepad autocorrected `ümlaut` into `umlaut` while this
was being built. Applications rewrite what is typed into them, and a model that
assumes otherwise will believe a field contains something it does not.
"""

from __future__ import annotations

import time
from typing import Any

from ..events import Request
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

#: Every action, with the arguments each one takes. Kept in one table so the
#: schema the model sees and the dispatch below cannot drift apart.
ACTIONS: dict[str, str] = {
    "screenshot": "Look at the screen. Costs tokens; the other actions do not.",
    "zoom": "Look closely at a region [x0,y0,x1,y1] - how to read small text.",
    "cursor_position": "Where the pointer is now.",
    "mouse_move": "Move the pointer to coordinate, without clicking.",
    "left_click": "Click. coordinate optional; text holds modifiers.",
    "right_click": "Right-click.",
    "middle_click": "Middle-click.",
    "double_click": "Double-click.",
    "triple_click": "Triple-click - selects a line in most editors.",
    "left_mouse_down": "Press and hold the left button.",
    "left_mouse_up": "Release the left button.",
    "left_click_drag": "Drag from start_coordinate to coordinate.",
    "scroll": "Scroll: scroll_direction and scroll_amount, optionally at a point.",
    "type": "Type text. Characters, on any keyboard layout.",
    "key": "Press a key or combination: Return, ctrl+s, alt+Tab. repeat optional.",
    "hold_key": "Hold a key for duration seconds.",
    "wait": "Wait duration seconds for something on screen to finish.",
}

CLICKS = {
    "left_click": ("left", 1), "right_click": ("right", 1),
    "middle_click": ("middle", 1), "double_click": ("left", 2),
    "triple_click": ("left", 3),
}

#: Offered when the model needs the machine and has not been allowed it yet.
GRANTS: list[tuple[str, float, bool]] = [
    ("15 minutes", 15 * 60, False),
    ("15 minutes, this app only", 15 * 60, True),
    ("1 hour", 60 * 60, False),
    ("no", 0, False),
]


class Computer(Tool):
    """See the screen, move the pointer, use the keyboard."""

    name = "computer"
    description = (
        "Use the computer the way a person does: look at the screen, move the "
        "mouse, click, and type - in any application, not just a browser. "
        "Take a screenshot first and work from what is in it; coordinates are "
        "the pixels of that screenshot. Use zoom to read small text rather "
        "than guessing at it. Prefer the browse tool for anything that is only "
        "a web page. Typing can be altered by the application receiving it, so "
        "look again when what was typed matters."
    )
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS),
                       "description": "What to do. "
                                      + " ".join(f"{name}: {why}"
                                                 for name, why in ACTIONS.items())},
            "coordinate": {"type": "array", "items": {"type": "integer"},
                           "minItems": 2, "maxItems": 2,
                           "description": "[x, y] in screenshot pixels."},
            "start_coordinate": {"type": "array", "items": {"type": "integer"},
                                 "minItems": 2, "maxItems": 2,
                                 "description": "Where a drag begins."},
            "region": {"type": "array", "items": {"type": "integer"},
                       "minItems": 4, "maxItems": 4,
                       "description": "[x0, y0, x1, y1], for zoom."},
            "text": {"type": "string",
                     "description": "Text to type, a key for key/hold_key, or "
                                    "modifiers to hold during a click."},
            "scroll_direction": {"type": "string",
                                 "enum": ["up", "down", "left", "right"]},
            "scroll_amount": {"type": "integer", "description": "Wheel clicks."},
            "repeat": {"type": "integer", "description": "For key, 1 to 100."},
            "duration": {"type": "number", "description": "Seconds, up to 300."},
            "whole_desktop": {"type": "boolean",
                              "description": "Screenshot every monitor rather "
                                             "than the active one."},
        },
        "required": ["action"],
    }

    def __init__(self, guard: Any = None, watcher: Any = None,
                 overlay: bool = True) -> None:
        from ..desktop.guard import Guard

        self.guard = guard if guard is not None else Guard()
        self.watcher = watcher
        self.wants_overlay = overlay and watcher is None
        self._desktop: Any = None
        self._last: Any = None            # the most recent Shot, for coordinates

    # -- how it is described ---------------------------------------------- #

    def summary(self, args: dict[str, Any]) -> str:
        action = args.get("action", "?")
        where = args.get("coordinate")
        if action in ("type", "key", "hold_key"):
            text = str(args.get("text", ""))
            short = text if len(text) <= 30 else text[:29] + "…"
            return f"computer: {action} {short!r}"
        if where:
            return f"computer: {action} at ({where[0]}, {where[1]})"
        return f"computer: {action}"

    # -- the gate --------------------------------------------------------- #

    def invoke(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        """Guard, run, and time one action.

        Replaces the base implementation on purpose. `Tool.invoke` asks the
        permission engine, which remembers "allow always" for the session -
        and a session-long unconditional grant over the whole machine is not a
        limit. The mode check is kept; the rest is the guard's.
        """
        started = time.monotonic()

        allowed, why = ctx.permissions.mode_allows(self.risk)
        if not allowed:
            return _timed(ToolResult.failure(why, denied=True), started)

        try:
            self._ensure_allowed(ctx)
            # Before the action, whatever the action is. `Desktop` asks the
            # guard once per thing it does, which means an action that does
            # nothing to the machine - asking where the pointer is, waiting -
            # never asked at all. Those are exactly the moments a user with
            # their hand on the mouse expects to be heard.
            self._before(_Whatever(args.get("action", "")))
            result = self.run(ctx, **args)
        except PermissionError as refusal:
            # Refused by the guard: expiry, scope, deny-list, or the corner.
            # Said on the screen too - somebody watching their own mouse is not
            # reading the transcript at that moment.
            teller = getattr(self.watcher, "say", None)
            if teller is not None:
                teller(str(refusal).split(".")[0], alarm=True)
            result = ToolResult.failure(str(refusal), denied=True)
        except TypeError as exc:
            result = ToolResult.failure(f"invalid arguments for computer: {exc}")
        except Exception as exc:
            result = ToolResult.failure(f"{type(exc).__name__}: {exc}")

        result.content = ctx.redact(result.content)
        result.display = ctx.redact(result.display)
        return _timed(result, started)

    def _ensure_allowed(self, ctx: ToolContext) -> None:
        """A grant, asked for once, with a length rather than a yes."""
        if self.guard.active:
            return

        if ctx.bus is None or not getattr(ctx.bus, "listening", True):
            raise PermissionError(
                "Comodor has not been allowed to use the screen, and there is "
                "nobody here to ask. Run `comodor computer` to allow it, or "
                "`/computer 15m` from the interface.")

        # A grant that has just run out is asked about again rather than
        # simply refused: the run is mid-task, and "your time is up, more?" is
        # the question the moment actually poses. Saying which it is matters -
        # somebody who granted fifteen minutes and is asked again should be
        # told that is why, not shown the same first-time prompt.
        again = self.guard.status()
        expired = "ran out" in again
        request = Request(
            id=f"computer_{int(time.time() * 1000) % 1_000_000}",
            prompt=("The time you allowed ran out. Carry on using your screen?"
                    if expired else
                    "Let Comodor use your screen, mouse and keyboard?"),
            options=[label for label, _, _ in GRANTS],
            detail=_CONSENT,
            kind="permission",
            meta={"tool": self.name, "risk": int(self.risk)},
        )
        asked = ctx.bus.ask(request)
        # The same patience the permission engine has. A hardcoded two minutes
        # here meant a headless run reported a single action as having taken
        # two minutes before refusing it.
        answer = asked.wait(getattr(ctx.permissions, "prompt_timeout", 600.0))

        for label, seconds, this_app in GRANTS:
            if answer == label and seconds:
                scope = self._desk().foreground() if this_app else ""
                self.guard.allow(seconds, scope=scope, reason="asked for it")
                self._show()
                return

        # A timeout returns the last option, which is "no" - the right decision
        # and the wrong description. Somebody who never saw the question should
        # not be told they refused it.
        if not asked.answered:
            raise PermissionError(
                "Nobody answered the request to use the screen, so nothing was "
                "touched. Ask again when someone is at the keyboard.")
        raise PermissionError(
            "You did not allow Comodor to use the screen. Nothing was touched.")

    # -- the actions ------------------------------------------------------ #

    def run(self, ctx: ToolContext, action: str = "", **args: Any) -> ToolResult:
        if action not in ACTIONS:
            return ToolResult.failure(
                f"unknown action {action!r}. One of: {', '.join(ACTIONS)}")

        desk = self._desk()

        if action == "screenshot":
            return self._look(ctx, desk, bool(args.get("whole_desktop")))
        if action == "zoom":
            return self._zoom(ctx, desk, args.get("region"))
        if action == "cursor_position":
            x, y = desk.where()
            return ToolResult.success(f"X={x}, Y={y}",
                                      display=f"pointer at ({x}, {y})")
        if action == "wait":
            seconds = max(0.0, min(float(args.get("duration") or 1.0), 300.0))
            time.sleep(seconds)
            return ToolResult.success(f"Waited {seconds:g} seconds.")

        if action == "mouse_move":
            x, y = self._point(args.get("coordinate"), "mouse_move")
            desk.move(x, y)
            return self._moved(f"Moved to ({x}, {y}).", (x, y))

        if action in CLICKS:
            button, count = CLICKS[action]
            point = args.get("coordinate")
            if point is not None:
                x, y = self._point(point, action)
                desk.click(x, y, button=button, count=count,
                           modifiers=str(args.get("text") or ""))
            else:
                x, y = desk.where()
                desk.click(button=button, count=count,
                           modifiers=str(args.get("text") or ""))
            return self._moved(f"{action.replace('_', ' ').capitalize()} "
                               f"at ({x}, {y}).", (x, y))

        if action in ("left_mouse_down", "left_mouse_up"):
            desk.press("left", down=action.endswith("down"))
            return ToolResult.success(
                f"Left button {'held' if action.endswith('down') else 'released'}.")

        if action == "left_click_drag":
            start = self._point(args.get("start_coordinate"), action)
            end = self._point(args.get("coordinate"), action)
            desk.drag(start, end, modifiers=str(args.get("text") or ""))
            return self._moved(f"Dragged from {start} to {end}.", end)

        if action == "scroll":
            direction = str(args.get("scroll_direction") or "down")
            amount = int(args.get("scroll_amount") or 3)
            at = args.get("coordinate")
            desk.scroll(direction, amount,
                        at=self._point(at, action) if at else None,
                        modifiers=str(args.get("text") or ""))
            return ToolResult.success(f"Scrolled {direction} by {amount}.")

        if action == "type":
            text = str(args.get("text") or "")
            if not text:
                return ToolResult.failure("type needs text")
            desk.type_text(text)
            # Said every time, because it is true every time and the model has
            # no other way to find out.
            return ToolResult.success(
                f"Typed {len(text)} characters. Applications can autocorrect or "
                f"reformat what is typed into them - take a screenshot if what "
                f"arrived matters.",
                display=f"typed {text[:60]!r}")

        if action == "key":
            combination = str(args.get("text") or "")
            repeat = int(args.get("repeat") or 1)
            desk.key(combination, repeat=repeat)
            times = "" if repeat == 1 else f" x{repeat}"
            return ToolResult.success(f"Pressed {combination}{times}.")

        if action == "hold_key":
            combination = str(args.get("text") or "")
            seconds = float(args.get("duration") or 1.0)
            desk.hold(combination, seconds)
            return ToolResult.success(f"Held {combination} for {seconds:g}s.")

        return ToolResult.failure(f"{action} is not implemented")

    # -- looking ---------------------------------------------------------- #

    def _look(self, ctx: ToolContext, desk: Any, whole_desktop: bool) -> ToolResult:
        budget = int(getattr(ctx.config, "computer", None) and
                     ctx.config.computer.screenshot_tokens or 0) or None
        shot = desk.look(budget or _default_budget(), whole_desktop=whole_desktop)
        self._last = shot
        return self._picture(shot, "the screen")

    def _zoom(self, ctx: ToolContext, desk: Any, region: Any) -> ToolResult:
        if not region or len(region) != 4:
            return ToolResult.failure("zoom needs region as [x0, y0, x1, y1]")
        if self._last is None:
            return ToolResult.failure(
                "take a screenshot before zooming - the region is in the "
                "coordinates of one")
        x0, y0 = self._last.to_screen(region[0], region[1])
        x1, y1 = self._last.to_screen(region[2], region[3])
        shot = desk.magnify((x0, y0, x1, y1))
        # Deliberately not stored as `_last`: coordinates stay in the frame of
        # the wide shot, so the model can act on what it read without having to
        # convert anything back.
        return self._picture(shot, f"a close look at {list(region)}")

    def _picture(self, shot: Any, what: str) -> ToolResult:
        import base64

        return ToolResult(
            ok=True,
            content=f"A screenshot of {what}: {shot.width}x{shot.height} pixels. "
                    f"Coordinates you give are in these pixels.",
            display=f"screenshot — {shot.describe()}",
            meta={"image": base64.b64encode(shot.data).decode(),
                  "width": shot.width, "height": shot.height,
                  "scale": shot.scale, "origin": shot.origin},
        )

    # -- helpers ---------------------------------------------------------- #

    def _desk(self) -> Any:
        if self._desktop is None:
            from ..desktop import Desktop

            self._desktop = Desktop(watcher=self.watcher, guard=self._before)
        return self._desktop

    def _show(self) -> None:
        """Open the overlay, once a grant exists and not before.

        Nothing is drawn until there is something to draw, and a transparent
        window over the whole desk for a session that never uses the screen is
        a window nobody asked for.
        """
        if not self.wants_overlay or self.watcher is not None:
            return
        from ..desktop.overlay import Overlay

        overlay = Overlay(status=self.guard.status)
        if not overlay.start():
            self.wants_overlay = False       # said once, not attempted again
            return
        self.watcher = overlay
        if self._desktop is not None:
            self._desktop.watcher = overlay

    def _before(self, action: Any) -> None:
        """The guard, asked again for every single action."""
        machine = self._desk().machine
        self.guard.check(
            pointer=machine.cursor(),
            corners=[(rect.left, rect.top, rect.right, rect.bottom)
                     for rect in machine.monitors()],
            foreground=machine.foreground_title(),
            locked=machine.screen_is_locked(),
            what=action.kind,
        )

    def _point(self, value: Any, action: str) -> tuple[int, int]:
        if not value or len(value) != 2:
            raise TypeError(f"{action} needs coordinate as [x, y]")
        if self._last is None:
            raise TypeError(
                "take a screenshot first - coordinates are the pixels of one")
        return self._last.to_screen(float(value[0]), float(value[1]))

    def _moved(self, message: str, at: tuple[int, int]) -> ToolResult:
        """Remember where the pointer was left, so the corner means something."""
        self.guard.note_pointer(at)
        return ToolResult.success(message)

    def close(self) -> None:
        self.guard.revoke("the session ended")
        closer = getattr(self.watcher, "close", None)
        if closer is not None:
            closer()


class _Whatever:
    """Stands in for an Action when the guard is asked before dispatch.

    The guard only reads `kind`, and at this point what the action will turn
    into is not decided yet - only what the model called it.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind


def _default_budget() -> int:
    from ..desktop import DEFAULT_TOKENS

    return DEFAULT_TOKENS


def _timed(result: ToolResult, started: float) -> ToolResult:
    result.elapsed = time.monotonic() - started
    return result


_CONSENT = """\
It will be able to see everything on your screen and to click and type
anywhere, in any application.

Screenshots go to the model. Whatever is on screen goes with them - open
messages, tokens, anything visible. Redaction works on text and cannot read
pixels.

It will never touch a password manager, a window asking for a password, a
locked screen, or Comodor's own window.

To stop it at any moment: move your mouse into a corner of the screen. That
ends it immediately and takes the permission away."""
