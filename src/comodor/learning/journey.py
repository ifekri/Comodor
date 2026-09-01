"""The journey: what the brain has learned, as one timeline.

Three other screens show pieces of this — /progress the numbers, /memory the
facts, /rules the conventions — but none of them answer the question a person
actually asks after a few weeks: *what has it picked up along the way?* This
one answers it, oldest first, every learning event in the order it happened.

It is pure rendering. Nothing here is queried by the agent, nothing enters a
prompt, and the cache prefix is untouched. The output can contain the text of
personal facts, so it is for the person reading the terminal — never an
automatic export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .store import BrainStore

#: Below this many events the timeline is a claim about a sample of one, and
#: says so instead — the same honesty rule progress.py applies to trends.
MIN_FOR_STORY = 6

STAMP = "%Y-%m-%d %H:%M"


def render(timeline: "Journey", theme, width: int = 90):
    """The timeline as a Rich renderable, for the overlay and the CLI alike.

    Kept beside the data rather than in ``ui/widgets``: the rendering is a
    table of what the store already says, with nothing to lay out that a
    grid cannot say.
    """
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    style = theme.style
    if not timeline.events:
        return Panel(Text("nothing learned yet — the timeline starts as it "
                          "works", style=style("dim")),
                     title="journey")

    table = Table.grid(padding=(0, 2))
    table.add_column("when", no_wrap=True, style=style("dim"))
    table.add_column("kind", no_wrap=True, style=style("accent"))
    table.add_column("what", max_width=max(20, width - 46), overflow="ellipsis")
    table.add_column("backing", style=style("dim"),
                     max_width=max(14, width // 4), overflow="ellipsis")

    for event in timeline.events:
        table.add_row(event.stamp, event.kind, event.text, event.detail)

    counts = timeline.counts()
    summary = " · ".join(f"{count} {name}{'s' if count != 1 else ''}"
                         for name, count in sorted(counts.items()))
    if timeline.thin:
        summary += (f"   — {len(timeline.events)} event(s) so far; "
                    f"the shape means more after {MIN_FOR_STORY}")
    return Panel(table, title=f"journey — {summary}")


@dataclass
class Event:
    """One learning event, rendered as a timeline row."""

    when: float
    kind: str                        # lesson | rule | skill | fact
    text: str                        # the one-line summary, already truncated
    detail: str = ""                 # evidence, scores, origins — what backs it
    node_id: str = ""                # "lesson:12" — the target of journey remove

    @property
    def stamp(self) -> str:
        return datetime.fromtimestamp(self.when).strftime(STAMP)


@dataclass
class Journey:
    """The whole timeline, plus the honest counts about it."""

    events: list[Event] = field(default_factory=list)

    @property
    def thin(self) -> bool:
        return len(self.events) < MIN_FOR_STORY

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for event in self.events:
            tally[event.kind] = tally.get(event.kind, 0) + 1
        return tally


def _clip(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build(store: BrainStore, scope: str = "") -> Journey:
    """Every learning event in the store, oldest first. No model involved."""
    events: list[Event] = []

    for lesson in store.all_lessons():
        events.append(Event(
            when=lesson.created_at, kind="lesson",
            text=_clip(lesson.text),
            detail=(f"{lesson.kind} · confidence {lesson.confidence:.2f}"
                    + (f", {lesson.wins} win(s)" if lesson.wins else "")
                    + ("" if lesson.status == "active" else f", {lesson.status}")),
            node_id=f"lesson:{lesson.id}"))

    for rule in store.all_rules():
        events.append(Event(
            when=rule.created_at, kind="rule",
            text=_clip(rule.statement or rule.key),
            detail=(f"{rule.key} · {rule.support} agreeing observation(s)"
                    + (f", {rule.against} against" if rule.against else "")
                    + ("" if rule.active else ", disabled")),
            node_id=f"rule:{rule.id}"))

    for skill in store.all_skills():
        events.append(Event(
            when=skill.created_at, kind="skill",
            text=_clip(skill.name),
            detail=(f"learned procedure · used {skill.uses}x"
                    f", success {skill.success_rate:.0%}"),
            node_id=f"skill:{skill.name}"))

    for fact in store.all_facts(settled_only=False):
        events.append(Event(
            when=fact.created_at, kind="fact",
            text=_clip(fact.text),
            detail=(f"{fact.kind} · origin episode #{fact.origin_episode}"
                    if fact.origin_episode else f"{fact.kind}")
            + ("" if fact.status == "settled" else f", {fact.status}"),
            node_id=f"fact:{fact.id}"))

    events.sort(key=lambda event: event.when)
    return Journey(events=events)

def remove(store: BrainStore, node_id: str) -> tuple[bool, str]:
    """Retire one node, by the curator's rules: archive or forget, never lose.

    A lesson is deleted the way /memory forget does. A rule is disabled, not
    deleted — its evidence is still a true fact about how the user works. A
    fact is removed. A learned skill is deleted from the brain; the folder on
    disk, if there is one, is the archive and stays where it is.
    """
    kind, _, raw = node_id.partition(":")
    if not raw.isdigit():
        return False, f"{node_id!r} is not a node id — see `comodor journey`"
    ident = int(raw)

    if kind == "lesson":
        return store.delete_lesson(ident), f"lesson #{ident} forgotten"
    if kind == "rule":
        if store.set_rule_flags(ident, active=False):
            return True, (f"rule #{ident} disabled — its evidence stays; "
                          "`comodor rules` can re-enable it")
        return False, f"no rule #{ident}"
    if kind == "fact":
        return store.delete_fact(ident), f"fact #{ident} removed"
    if kind == "skill":
        try:
            with store._lock, store.connection as connection:
                cursor = connection.execute(
                    "DELETE FROM skills WHERE id=?", (ident,))
            removed = cursor.rowcount > 0
        except Exception:
            return False, f"could not remove skill #{ident}"
        return removed, f"skill #{ident} removed from the brain"
    return False, f"nothing called {node_id!r}"
