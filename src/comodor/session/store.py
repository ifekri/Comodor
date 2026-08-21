"""Saving conversations, and getting them back out.

Sessions are JSON Lines files under the user directory: one file per session,
one record per message, appended as the conversation happens. That format is
chosen for a specific reason — a crash mid-session loses at most the last line,
where a single JSON document would be truncated and unreadable.

Export is separate from storage. The stored form is for resuming; the exported
Markdown or HTML is for reading and sharing, and has every secret stripped.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..providers.base import Message, Role, ToolCall
from ..safety.redact import redact


@dataclass
class SessionMeta:
    id: str
    title: str = ""
    cwd: str = ""
    provider: str = ""
    model: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: int = 0
    cost_usd: float = 0.0

    @property
    def when(self) -> str:
        delta = time.time() - self.updated_at
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        return time.strftime("%d %b", time.localtime(self.updated_at))


def new_session_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


class SessionStore:
    """One directory of session files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ------------------------------------------------------------ #

    def path_for(self, session_id: str) -> Path:
        return self.root / f"{session_id}.jsonl"

    def meta_path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.meta.json"

    # -- writing ---------------------------------------------------------- #

    def append(self, session_id: str, message: Message) -> None:
        record = {
            "role": message.role.value,
            "content": message.content,
            # Kept because a resumed session must send the same bytes it sent
            # before, or the provider's cache misses on the whole history.
            "briefing": message.briefing,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "is_error": message.is_error,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in message.tool_calls
            ],
            "at": time.time(),
        }
        with self.path_for(session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def save_meta(self, meta: SessionMeta) -> None:
        meta.updated_at = time.time()
        self.meta_path(meta.id).write_text(
            json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")

    # -- reading ---------------------------------------------------------- #

    def load(self, session_id: str) -> list[Message]:
        path = self.path_for(session_id)
        if not path.exists():
            return []
        messages: list[Message] = []
        for record in _read_jsonl(path):
            try:
                messages.append(Message(
                    role=Role(record.get("role", "user")),
                    content=record.get("content", ""),
                    briefing=record.get("briefing", ""),
                    name=record.get("name", ""),
                    tool_call_id=record.get("tool_call_id", ""),
                    is_error=bool(record.get("is_error")),
                    tool_calls=[ToolCall(id=call.get("id", ""), name=call.get("name", ""),
                                         arguments=call.get("arguments") or {})
                                for call in record.get("tool_calls") or []],
                ))
            except (ValueError, TypeError):
                continue
        return messages

    def load_meta(self, session_id: str) -> SessionMeta | None:
        path = self.meta_path(session_id)
        if not path.exists():
            return None
        try:
            return SessionMeta(**json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            return None

    def list_sessions(self, limit: int = 30) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        for path in sorted(self.root.glob("*.meta.json"), reverse=True):
            meta = self.load_meta(path.name.removesuffix(".meta.json"))
            if meta is not None:
                metas.append(meta)
            if len(metas) >= limit:
                break
        return sorted(metas, key=lambda item: item.updated_at, reverse=True)

    def delete(self, session_id: str) -> bool:
        removed = False
        for path in (self.path_for(session_id), self.meta_path(session_id)):
            if path.exists():
                path.unlink()
                removed = True
        return removed

    # -- export ----------------------------------------------------------- #

    def export_markdown(self, session_id: str, target: Path,
                        secrets: list[str] | None = None) -> Path:
        meta = self.load_meta(session_id)
        lines = [f"# {meta.title if meta else session_id}", ""]
        if meta:
            lines += [
                f"*{time.strftime('%Y-%m-%d %H:%M', time.localtime(meta.created_at))} · "
                f"{meta.provider} · {meta.model}*", "",
            ]

        for message in self.load(session_id):
            if message.role is Role.USER:
                lines += ["## User", "", message.content, ""]
            elif message.role is Role.ASSISTANT:
                if message.content:
                    lines += ["## Assistant", "", message.content, ""]
                for call in message.tool_calls:
                    lines += [f"> **{call.name}** "
                              f"`{json.dumps(call.arguments, ensure_ascii=False)[:200]}`", ""]
            elif message.role is Role.TOOL:
                status = "failed" if message.is_error else "ok"
                body = message.content[:2000]
                lines += [f"<details><summary>{message.name} ({status})</summary>", "",
                          "```", body, "```", "", "</details>", ""]

        text = redact("\n".join(lines), secrets or [])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def export_json(self, session_id: str, target: Path,
                    secrets: list[str] | None = None) -> Path:
        payload = {
            "meta": asdict(self.load_meta(session_id) or SessionMeta(id=session_id)),
            "messages": list(_read_jsonl(self.path_for(session_id))),
        }
        text = redact(json.dumps(payload, ensure_ascii=False, indent=2), secrets or [])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def derive_title(text: str, limit: int = 48) -> str:
    """A readable session name taken from the first request."""
    title = " ".join((text or "").split())
    if len(title) <= limit:
        return title or "untitled"
    return title[: limit - 1] + "…"
