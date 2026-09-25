"""Characterization: the superseded-read rule as it stands (T004).

`agent/staleness.py` drops a file read that a later edit made untrue, and
nothing else. Spec 002 keeps that rule (FR-045, FR-046, SC-013) and adds
optimizations beside it, so what it must *not* touch is pinned here: the
newest read of a file, any read of a file nothing wrote to, and anything
below the cache-cost threshold.
"""

from __future__ import annotations

from comodor.agent.staleness import READERS, WORTH_IT, WRITERS, forget_superseded_reads
from comodor.agent.tokens import estimate_text
from comodor.providers.base import Message, ToolCall


def big(marker: str = "x") -> str:
    return "\n".join(f"{n:6d}\t{marker} = {n}" for n in range(1, 900))


def a_read(path: str, body: str, call_id: str = "") -> Message:
    message = Message.tool(call_id=call_id or f"r-{path}-{hash(body) % 1000}",
                           name="read_file", content=body)
    message.meta["path"] = path
    return message


def an_edit(path: str) -> list[Message]:
    call = ToolCall(id=f"e-{path}", name="edit_file",
                    arguments={"path": path, "old_string": "a", "new_string": "b"})
    done = Message.tool(call_id=call.id, name="edit_file", content=f"Edited {path}.")
    done.meta["path"] = path
    return [Message.assistant("Editing.", [call]), done]


def sweep(messages):
    return forget_superseded_reads(messages, estimate_text)


def test_the_rule_names_exactly_which_tools_read_and_write():
    assert READERS == frozenset({"read_file"})
    assert WRITERS == frozenset({"write_file", "edit_file"})


def test_the_newest_read_is_never_rewritten_even_after_an_edit():
    newest = big("y")
    messages = [a_read("a.py", big()), *an_edit("a.py"), a_read("a.py", newest)]
    dropped, _ = sweep(messages)
    assert dropped == 1
    assert messages[-1].content == newest
    assert "superseded" not in messages[-1].meta


def test_a_read_of_an_unedited_file_is_never_rewritten_even_when_duplicated():
    body = big()
    messages = [a_read("a.py", body, "r1"), a_read("a.py", body, "r2"),
                a_read("a.py", body, "r3")]
    assert sweep(messages) == (0, 0)
    assert all(m.content == body for m in messages)


def test_a_read_after_the_last_edit_is_current_and_kept():
    body = big()
    messages = [*an_edit("a.py"), a_read("a.py", body, "r1"), a_read("a.py", body, "r2")]
    assert sweep(messages) == (0, 0)


def test_an_edit_to_another_file_supersedes_nothing():
    body = big()
    messages = [a_read("a.py", body, "r1"), *an_edit("b.py"), a_read("a.py", body, "r2")]
    assert sweep(messages) == (0, 0)


def test_a_read_below_the_threshold_is_left_alone():
    small = "x = 1\n" * 5
    assert estimate_text(small) < WORTH_IT
    messages = [a_read("a.py", small, "r1"), *an_edit("a.py"), a_read("a.py", small, "r2")]
    assert sweep(messages) == (0, 0)


def test_only_reader_results_are_ever_touched():
    body = big()
    listing = Message.tool(call_id="l1", name="list_dir", content=body)
    listing.meta["path"] = "a.py"
    messages = [listing, *an_edit("a.py"), a_read("a.py", body, "r2")]
    assert sweep(messages) == (0, 0)
    assert listing.content == body


def test_a_superseded_read_is_replaced_by_a_note_naming_the_file():
    messages = [a_read("a.py", big(), "r1"), *an_edit("a.py"), a_read("a.py", big("y"), "r2")]
    dropped, freed = sweep(messages)
    assert dropped == 1 and freed > 0
    assert messages[0].meta["superseded"] is True
    assert "a.py" in messages[0].content and "read the file again" in messages[0].content


def test_the_sweep_is_idempotent():
    messages = [a_read("a.py", big(), "r1"), *an_edit("a.py"), a_read("a.py", big("y"), "r2")]
    sweep(messages)
    assert sweep(messages) == (0, 0)
