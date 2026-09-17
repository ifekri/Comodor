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
import secrets
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
    #: How many times this session's history has been compacted. A long-lived
    #: channel session reads very differently from a fresh one with the same
    #: message count, and `/resume` should say which it is reopening.
    compactions: int = 0
    #: The task list as it stood, so `--resume` brings back the plan and not
    #: just the transcript. Kept here rather than in the JSONL because it is
    #: state, not an event: only the latest version is of any use, and the
    #: transcript is append-only by design.
    todos: list[dict[str, str]] = field(default_factory=list)

    @property
    def when(self) -> str:
        delta = time.time() - self.updated_at
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        return time.strftime("%d %b", time.localtime(self.updated_at))


def new_session_id() -> str:
    """A readable id no other session has.

    The stamp alone was the whole id, and to the second. That is safe at a
    terminal, where a person cannot start two sessions inside the same second.
    In a browser "new chat" is a button: two clicks in one second produced the
    same id twice, and the second conversation was appended to the first one's
    transcript - two chats in one file, neither readable back.

    The suffix is short enough to keep the id something a person can say out
    loud, and the stamp still sorts the way the filenames are listed.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return f"{stamp}-{secrets.token_hex(2)}"


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
        # A question form, as it was shown and how it ended. Additive: a
        # record written before this key existed reads back exactly as it
        # did, and a reader that does not know the key ignores it.
        form = message.meta.get("question") if message.meta else None
        if isinstance(form, dict):
            record["question"] = form
        # A spill path the conversation was given. Additive, like `question`:
        # a record written before this key existed reads back unchanged. Kept
        # so a resumed session still protects the file its pointer names from
        # pruning (FR-089).
        spill = message.meta.get("spill") if message.meta else None
        if isinstance(spill, str) and spill:
            record["spill"] = spill
        # Where a USER-role message came from. The loop's own prompts
        # (compaction brief, completion correction, plan restatement) are
        # marked; without the mark surviving the round trip a resumed session
        # would treat model-written text as something the person said, and the
        # memory tool could persist it as a `user_statement` (FR-066).
        if message.meta.get("synthetic"):
            record["synthetic"] = True
        if message.meta.get("compacted"):
            record["compacted"] = True
        # A deduplicated reference or a delta names the earlier full result it
        # was written against. That link is a promise the content is still in
        # the conversation, and it is what compaction and the budget manager
        # protect; without it a resumed session could summarise the base away
        # and leave the pointer standing for nothing (FR-100, FR-101).
        for key in ("reference", "delta_base"):
            value = message.meta.get(key) if message.meta else None
            if isinstance(value, str) and value:
                record[key] = value
        if message.meta.get("delta"):
            record["delta"] = True
        # The source a tool message observed: the file it was about and the
        # fingerprint of what was there. Without them a resumed observation
        # cannot be tied to a file, so a learned item resting on it could
        # never be invalidated when that file changes (FR-060, FR-114).
        for key in ("path", "fingerprint"):
            value = message.meta.get(key) if message.meta else None
            if isinstance(value, str) and value:
                record[key] = value
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
                meta: dict[str, Any] = {}
                if isinstance(record.get("question"), dict):
                    meta["question"] = record["question"]
                if isinstance(record.get("spill"), str) and record["spill"]:
                    meta["spill"] = record["spill"]
                if record.get("synthetic"):
                    meta["synthetic"] = True
                if record.get("compacted"):
                    meta["compacted"] = True
                for key in ("reference", "delta_base"):
                    if isinstance(record.get(key), str) and record[key]:
                        meta[key] = record[key]
                if record.get("delta"):
                    meta["delta"] = True
                for key in ("path", "fingerprint"):
                    if isinstance(record.get(key), str) and record[key]:
                        meta[key] = record[key]
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
                    meta=meta,
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
                form = message.meta.get("question") if message.meta else None
                if isinstance(form, dict):
                    lines += _question_lines(form)
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


def _question_lines(form: dict[str, Any]) -> list[str]:
    """A question form in an export: what was asked, what was offered, what
    came back, and how it ended — as it was, not as the model summarised it.

    Every option the person saw is listed, the write-your-own row included,
    and a question that was cancelled, expired or unattended says so rather
    than reading as answered.
    """
    outcome = str(form.get("outcome", ""))
    ended = {"answered": "answered", "cancelled": "cancelled — left unresolved",
             "expired": "expired — left unresolved",
             "unattended": "unattended — nobody could answer; left unresolved"}
    lines = ["### Question", ""]
    answers = {str(entry.get("header", "")): entry for entry in form.get("answers") or []
               if isinstance(entry, dict)}
    for question in form.get("questions") or []:
        if not isinstance(question, dict):
            continue
        lines.append(f"**{question.get('header', '')}** — {question.get('prompt', '')}")
        for option in question.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = str(option.get("label", ""))
            note = " *(write your own)*" if option.get("free") else ""
            lines.append(f"- {label}{note}")
        given = answers.get(str(question.get("header", "")))
        chosen = [str(c) for c in (given or {}).get("chosen") or []]
        written = str((given or {}).get("written") or "").strip()
        if chosen or written:
            answer = ", ".join(chosen + ([written] if written else []))
            lines.append(f"- **Answer:** {answer}")
        else:
            lines.append("- **Answer:** none")
        lines.append("")
    lines += [f"*Outcome: {ended.get(outcome, outcome or 'unknown')}*", ""]
    return lines


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
