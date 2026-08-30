"""A file read before it was changed is not merely expensive. It is wrong.

An agent reads a file at step two, edits it at step five, and the copy from
step two stays in the conversation for the rest of the task. It is re-sent with
every request, and on a provider without prefix caching it is paid for every
time — but that is the smaller half of the problem.

The larger half is that it is no longer true. The model is looking at bytes
that are not in the file any more, beside the diff that changed them, and has
to work out for itself which of the two to believe. Every re-read after an edit
is the model doing exactly that, and paying twice for the privilege.

So a read that has been superseded is replaced by a line saying so. What
remains is the diff — which is what actually happened — and an instruction to
read the file again if the current contents are needed.

**This is not compaction.** Compaction summarises what is too big to keep, with
a model call and a loss. This drops something that is known to be stale, by an
exact rule, for free.

Two things it deliberately does not do.

*It never touches the newest read of a file.* That one is current, and dropping
it would make the model re-read what it already has.

*It never touches a read of a file nothing has written to.* An unedited file
read twice is a small waste; an edited file read once is a correctness problem.
Only the second is worth the cache it costs to fix.

The cache is the reason for the threshold. Rewriting a message that a provider
has already cached invalidates every byte after it, so the next request pays
full price for the tail. That is worth doing for a stale ten-thousand-token
file and not worth doing for a stale forty-token one.
"""

from __future__ import annotations

from typing import Any

#: Tools whose result is a snapshot of a file's contents.
READERS = frozenset({"read_file"})

#: Tools that change a file, making every earlier snapshot of it out of date.
WRITERS = frozenset({"write_file", "edit_file"})

#: Below this, dropping a stale read costs more than it saves: the message has
#: to be rewritten, and a rewritten message invalidates the provider's cache
#: from that point on. Roughly a hundred lines of code.
WORTH_IT = 400


def note(message: Any, path: str) -> None:
    """Record which file a tool message was about."""
    if path:
        message.meta["path"] = path


def _about(message: Any) -> str:
    return str(message.meta.get("path") or "")


def forget_superseded_reads(messages: list[Any], estimate: Any,
                            worth_it: int = WORTH_IT) -> tuple[int, int]:
    """Blank out file reads that a later edit made untrue.

    Returns `(reads dropped, tokens freed)`. Walks backwards so that the newest
    read of each file is the one kept, and only considers a read stale if a
    write to the same file came *after* it.
    """
    from ..providers.base import Role

    # Where each file was last written to, by position.
    last_write: dict[str, int] = {}
    for index, message in enumerate(messages):
        if message.role is Role.ASSISTANT:
            for call in message.tool_calls:
                if call.name in WRITERS:
                    target = str(call.arguments.get("path") or "")
                    if target:
                        last_write[target] = index
        elif message.role is Role.TOOL and message.name in WRITERS:
            target = _about(message)
            if target:
                last_write[target] = index

    dropped = 0
    freed = 0
    newest: set[str] = set()

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role is not Role.TOOL or message.name not in READERS:
            continue
        path = _about(message)
        if not path:
            continue

        if path not in newest:
            # The most recent read of this file. It is the current truth.
            newest.add(path)
            continue

        written = last_write.get(path)
        if written is None or written < index:
            # Nothing has changed the file since this read, so it is merely a
            # duplicate rather than a lie. Left alone: rewriting it would cost
            # the cache and buy very little.
            continue

        cost = estimate(message.content)
        if cost < worth_it:
            continue

        message.content = (
            f"[{path} was read here, then changed. Those contents are out of "
            f"date and have been dropped; read the file again if you need it.]"
        )
        message.meta["superseded"] = True
        dropped += 1
        freed += cost - estimate(message.content)

    return dropped, freed
