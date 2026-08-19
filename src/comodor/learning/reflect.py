"""Turning a finished task into something worth remembering.

After a task ends, the transcript is handed to the model with one question:
what, if anything, would you want to know next time? The answer comes back as
JSON — a handful of lessons, and occasionally a reusable procedure.

The prompt pushes hard toward returning *nothing*. A memory system that records
something after every task fills up with noise, and noise in the playbook is
worse than an empty playbook: it costs tokens on every future turn and nudges
the model with irrelevant advice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..agent.prompts import REFLECT_PROMPT
from ..providers.base import Message, collapse
from .store import Lesson, Skill

MAX_TRANSCRIPT_CHARS = 12_000
VALID_KINDS = ("preference", "fact", "heuristic", "pitfall", "env")


@dataclass
class Reflection:
    lessons: list[Lesson] = field(default_factory=list)
    skill: Skill | None = None
    raw: str = ""

    @property
    def empty(self) -> bool:
        return not self.lessons and self.skill is None


def build_transcript(messages: list[Any], goal: str, outcome: str) -> str:
    """A compact account of what happened, biased toward the end of the task.

    Tool output is trimmed aggressively — what matters for learning is which
    tools were used and whether they failed, not the thousand lines a test
    runner printed.
    """
    lines = [f"GOAL: {goal}", f"OUTCOME: {outcome}", ""]
    for message in messages:
        role = getattr(message.role, "value", str(message.role))
        content = (message.content or "").strip()
        if role == "tool":
            status = "FAILED" if message.is_error else "ok"
            snippet = content[:400].replace("\n", " ")
            lines.append(f"[tool:{message.name} {status}] {snippet}")
        elif role == "assistant":
            calls = ", ".join(call.name for call in message.tool_calls)
            if content:
                lines.append(f"[assistant] {content[:700]}")
            if calls:
                lines.append(f"[assistant calls] {calls}")
        elif role == "user":
            lines.append(f"[user] {content[:700]}")

    text = "\n".join(lines)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        # Keep the goal and the ending; the middle of a long run is the least
        # informative part.
        head = text[:2000]
        tail = text[-(MAX_TRANSCRIPT_CHARS - 2000):]
        text = f"{head}\n\n… [middle omitted] …\n\n{tail}"
    return text


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a reply that may be wrapped in prose or fences."""
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    else:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            stripped = stripped[start:end + 1]
    try:
        value = json.loads(stripped)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def parse_reflection(text: str, scope: str, source: str = "") -> Reflection:
    """Validate the model's JSON into records we are willing to store."""
    payload = extract_json(text)
    reflection = Reflection(raw=text)
    if not payload:
        return reflection

    for entry in payload.get("lessons") or []:
        if not isinstance(entry, dict):
            continue
        guidance = str(entry.get("guidance") or "").strip()
        trigger = str(entry.get("trigger") or "").strip()
        if len(guidance) < 8:
            continue                      # too vague to act on
        kind = str(entry.get("kind") or "heuristic").lower()
        if kind not in VALID_KINDS:
            kind = "heuristic"
        try:
            confidence = float(entry.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        reflection.lessons.append(Lesson(
            kind=kind,
            scope=scope,
            trigger=trigger[:300] or "generally",
            guidance=guidance[:600],
            confidence=max(0.1, min(0.95, confidence)),
            source=source,
        ))

    candidate = payload.get("skill")
    if isinstance(candidate, dict) and candidate.get("name"):
        steps = [str(step)[:300] for step in (candidate.get("steps") or [])
                 if str(step).strip()]
        if len(steps) >= 2:               # one step is not a procedure
            reflection.skill = Skill(
                name=re.sub(r"[^a-z0-9_]+", "_", str(candidate["name"]).lower())[:60],
                description=str(candidate.get("description") or "")[:400],
                steps=steps[:12],
                tags=[str(tag)[:40] for tag in (candidate.get("tags") or [])][:8],
                scope=scope,
            )

    # Four is the cap the prompt asks for; enforce it rather than trust it.
    reflection.lessons = reflection.lessons[:4]
    return reflection


def reflect(gateway: Any, model: str, goal: str, messages: list[Any],
            outcome: str, scope: str, source: str = "") -> Reflection:
    """Run one reflection pass. Returns an empty result on any failure."""
    transcript = build_transcript(messages, goal, outcome)
    try:
        completion = collapse(gateway.stream(
            [Message.system(REFLECT_PROMPT), Message.user(transcript)],
            model=model, temperature=0.2, max_tokens=1200,
        ))
    except Exception:
        # Reflection is best-effort: never let it surface as a user-visible
        # failure of a task that already succeeded.
        return Reflection()
    return parse_reflection(completion.text, scope=scope, source=source)
