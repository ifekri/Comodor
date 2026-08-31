"""Reading a schedule out of words.

Schedules arrive in five shapes, in rough order of how people actually write
them: a cron expression from somebody who knows cron, an interval ("every
2h"), a named time with days ("weekdays at 9am", "mon and thu 14:00"), a
one-shot ("in 30m", "2026-09-01 09:00"), and the words "hourly", "daily" and
"weekly" on their own.

A parse failure is a message, not an exception the CLI formats: the model —
or the person — that wrote the schedule is the only one who can fix it, so
the error says what was wrong and shows the shapes that would have been
right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Weekday names, and the three-letter forms cron and everyday speech use.
#: The numbers are cron's, not Python's: 0 is Sunday, so a generated
#: expression reads the same in a crontab as it does here.
WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "tues": 2, "wed": 3, "thu": 4,
            "thur": 4, "thurs": 4, "fri": 5, "sat": 6,
            "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
            "thursday": 4, "friday": 5, "saturday": 6}

#: The words that stand for a set of days, in the same cron numbering.
DAY_SETS = {"weekday": (1, 2, 3, 4, 5), "weekdays": (1, 2, 3, 4, 5),
            "weekend": (0, 6), "weekends": (0, 6),
            "daily": (0, 1, 2, 3, 4, 5, 6),
            "day": (0, 1, 2, 3, 4, 5, 6), "everyday": (0, 1, 2, 3, 4, 5, 6)}

#: Named times people use instead of writing 09:00.
NAMED_TIMES = {"noon": (12, 0), "midnight": (0, 0)}


class UnparsableSchedule(ValueError):
    """The schedule could not be read. Carries the advice to show instead."""


@dataclass
class Schedule:
    """A parsed schedule.

    ``kind`` decides how the next fire time is found:

    ``cron``      the five-field expression, expanded against the clock.
    ``interval``  fixed steps of ``seconds`` from the job's creation.
    ``once``      one run at ``at``; the job disables itself afterwards.
    """

    kind: str                        # cron | interval | once
    expr: str = ""                   # the raw expression, as written
    seconds: int = 0                 # interval step
    at: datetime | None = None       # one-shot fire time

    def to_json(self) -> dict:
        return {"kind": self.kind, "expr": self.expr,
                "seconds": self.seconds,
                "at": self.at.isoformat() if self.at else ""}


def _advice(text: str) -> str:
    return (f"could not read the schedule {text!r}. Schedules I understand: "
            "'every 2h', 'daily at 9am', 'weekdays at 14:00', 'mon and thu at 9:30', "
            "'in 30m', '2026-09-01 09:00', 'hourly', or a five-field cron "
            "expression like '0 9 * * 1-5'.")


def parse(text: str) -> Schedule:
    """A schedule from words, or `UnparsableSchedule` saying what is wrong."""
    clean = " ".join(str(text or "").strip().lower().split())
    if not clean:
        raise UnparsableSchedule("the schedule is empty")

    parsed = _try_cron(clean) or _try_interval(clean) or _try_once(clean) \
        or _try_named(clean)
    if parsed is None:
        raise UnparsableSchedule(_advice(text))
    return parsed


def next_fire(schedule: Schedule, after: datetime, created: datetime) -> datetime | None:
    """The next time this schedule fires, strictly after `after`.

    For a one-shot past its time there is no next fire, and ``None`` is how
    that is said — the caller disables the job rather than looping forever on
    a date that will never come again.
    """
    if schedule.kind == "once":
        return schedule.at if schedule.at and schedule.at > after else None
    if schedule.kind == "interval":
        step = max(schedule.seconds, 60)
        base = created.replace(second=0, microsecond=0)
        elapsed = (after - base).total_seconds()
        steps = int(elapsed // step) + 1
        return base + timedelta(seconds=steps * step)
    return _cron_next(schedule.expr, after)


# -- intervals -------------------------------------------------------------- #

_INTERVAL = re.compile(r"every\s+(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|"
                       r"hours?|h|days?|d|weeks?|w)\b")
_PLAIN_INTERVALS = {"hourly": ("h", 1), "daily": ("d", 1), "weekly": ("w", 1)}
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86_400, "w": 604_800}


def _unit_seconds(word: str) -> int:
    return _UNIT_SECONDS[word[0]]


def _try_interval(clean: str) -> Schedule | None:
    match = _INTERVAL.match(clean)
    if match:
        count, unit = int(match.group(1)), match.group(2)
        seconds = count * _unit_seconds(unit)
        if seconds >= 60:
            return Schedule(kind="interval", expr=clean, seconds=seconds)
        return None

    for word, (unit, count) in _PLAIN_INTERVALS.items():
        if clean == word:
            return Schedule(kind="interval", expr=clean,
                            seconds=count * _unit_seconds(unit))
    return None


# -- one-shot ---------------------------------------------------------------- #

_ONCE_IN = re.compile(r"in\s+(\d+)\s*(minutes?|mins?|m|hours?|h|days?|d|weeks?|w)\b")
_ONCE_AT = re.compile(r"(?:at\s+)?(\d{4})-(\d{2})-(\d{2})[ t](\d{1,2}):(\d{2})")


def _try_once(clean: str) -> Schedule | None:
    match = _ONCE_IN.match(clean)
    if match:
        count, unit = int(match.group(1)), match.group(2)
        at = datetime.now() + timedelta(seconds=count * _unit_seconds(unit))
        return Schedule(kind="once", expr=clean, at=at.replace(microsecond=0))

    match = _ONCE_AT.match(clean)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        hour, minute = int(match.group(4)), int(match.group(5))
        try:
            at = datetime(year, month, day, hour, minute)
        except ValueError:
            return None
        return Schedule(kind="once", expr=clean, at=at)
    return None


# -- named times with days --------------------------------------------------- #

_TIME = re.compile(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b")


def _read_time(clean: str, start: int) -> tuple[tuple[int, int], int] | None:
    """A clock time starting at or after `start`, as (hour, minute), and where it ended."""
    match = _TIME.search(clean, start)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return (hour, minute), match.end()


def _read_days(clean: str) -> tuple[int, ...] | None:
    """The days named in the text, or None when none are."""
    words = clean.replace(",", " ").replace(" and ", " ").split()
    days: list[int] = []
    for word in words:
        if word in DAY_SETS:
            return DAY_SETS[word]
        if word in WEEKDAYS and word not in clean[:clean.find(word)]:
            days.append(WEEKDAYS[word])
    return tuple(sorted(set(days))) or None


def _try_named(clean: str) -> Schedule | None:
    if not any(word in clean for word in ("day", "mon", "tue", "wed", "thu",
                                          "fri", "sat", "sun", "at")):
        return None
    time = _read_time(clean, 0)
    if time is None:
        return None
    (hour, minute), _ = time
    days = _read_days(clean.replace("at", " ")) or (0, 1, 2, 3, 4, 5, 6)
    expr = f"{minute} {hour} * * {','.join(str(d) for d in days)}"
    return Schedule(kind="cron", expr=expr)


# -- cron expressions --------------------------------------------------------- #

_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _try_cron(clean: str) -> Schedule | None:
    fields = clean.split()
    if len(fields) != 5:
        return None
    for (field, (low, high)) in zip(fields, _FIELD_RANGES):  # noqa: B905
        if not _field_ok(field, low, high):
            return None
    return Schedule(kind="cron", expr=clean)


def _field_ok(field: str, low: int, high: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                return False
            step = int(step_text)
        if part in ("*", ""):
            continue
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2 or not all(b.isdigit() for b in bounds):
                return False
            first, last = int(bounds[0]), int(bounds[1])
        elif part.isdigit():
            first = last = int(part)
        else:
            return False
        if not low <= first <= high or not low <= last <= high or first > last:
            return False
        if step < 1 or step > high - low + 1:
            return False
    return True


def _cron_next(expr: str, after: datetime) -> datetime | None:
    """The next minute matching the expression, after `after`.

    Minute resolution, matching cron. Scanning forward minute by minute is
    the shape with no dependencies and no table of edge cases; the search is
    bounded well before it could take noticeable time, and a schedule that
    matches nothing in a year is a schedule nobody meant to write.
    """
    fields = expr.split()
    minutes = _expand(fields[0], 0, 59)
    hours = _expand(fields[1], 0, 23)
    days_of_month = _expand(fields[2], 1, 31)
    months = _expand(fields[3], 1, 12)
    dom_star, dow_star = fields[2] == "*", fields[4] == "*"
    days_of_week = _expand(fields[4], 0, 6)

    def is_dow(moment: datetime) -> bool:
        # Cron counts Sunday as 0; Python's weekday() counts Monday as 0.
        return (moment.weekday() + 1) % 7 in days_of_week

    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = after + timedelta(days=366)

    while candidate < limit:
        if candidate.month not in months:
            # Jump to the first of the next month rather than walking days.
            candidate = (candidate.replace(day=1, hour=0, minute=0)
                         + timedelta(days=32)).replace(day=1)
            continue
        if candidate.minute not in minutes:
            candidate += timedelta(minutes=1)
            continue
        if candidate.hour not in hours:
            candidate = candidate.replace(minute=0) + timedelta(hours=1)
            continue
        dom_ok = dom_star or candidate.day in days_of_month
        dow_ok = dow_star or is_dow(candidate)
        # Cron's own rule: when both day fields are restricted, either match.
        if not dom_star and not dow_star:
            if not (dom_ok or dow_ok):
                candidate += timedelta(minutes=1)
                continue
        elif not (dom_ok and dow_ok):
            candidate += timedelta(minutes=1)
            continue
        return candidate
    return None


def _expand(field: str, low: int, high: int) -> set[int]:
    """Every value a cron field covers."""
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            step = max(int(step_text), 1)
        if part in ("*", ""):
            values.update(range(low, high + 1, step))
            continue
        if "-" in part:
            first, last = (int(b) for b in part.split("-", 1))
        else:
            first = last = int(part)
        values.update(range(first, last + 1, step))
    return values
