"""Dropping file reads that a later edit made untrue.

An agent reads a file at step two, edits it at step five, and the copy from
step two rides along for the rest of the task, re-sent with every request.

Prefix caching makes the re-sending cheap — measured at 99% on two live
endpoints — so the tokens are the smaller half of this. The larger half is that
the copy is no longer true. The model is being shown bytes that are not in the
file any more, beside the diff that changed them, and left to work out which of
the two to believe.

Measured on a file the size of `agent/loop.py`, read twice with one edit
between: **8,346 tokens freed, half the history**. On the benchmark's
thirty-line fixtures it correctly does nothing at all.

Most of what is checked here is what it must *not* touch.
"""

from __future__ import annotations

from comodor.agent.context import Conversation
from comodor.agent.staleness import WORTH_IT, forget_superseded_reads
from comodor.agent.tokens import estimate_text
from comodor.providers.base import Message, ToolCall


def big(marker: str = "x") -> str:
    """A file result comfortably over the threshold."""
    return "\n".join(f"{n:6d}\t{marker} = {n}" for n in range(1, 900))


def a_read(path: str, body: str) -> Message:
    message = Message.tool(call_id=f"r{id(body)}", name="read_file", content=body)
    message.meta["path"] = path
    return message


def an_edit(path: str) -> list[Message]:
    call = ToolCall(id=f"e-{path}", name="edit_file",
                    arguments={"path": path, "old_string": "a", "new_string": "b"})
    done = Message.tool(call_id=call.id, name="edit_file",
                        content=f"Edited {path} (+1/-1).")
    done.meta["path"] = path
    return [Message.assistant("Editing.", [call]), done]


def sweep(messages: list[Message]) -> tuple[int, int]:
    return forget_superseded_reads(messages, estimate_text)


# --------------------------------------------------------------------------- #
# what it is for
# --------------------------------------------------------------------------- #


def test_a_read_that_an_edit_made_untrue_is_dropped():
    body = big()
    messages = [a_read("app.py", body), *an_edit("app.py"),
                a_read("app.py", big("y"))]

    dropped, freed = sweep(messages)

    assert dropped == 1
    assert freed > WORTH_IT
    assert "out of date" in messages[0].content
    assert body not in messages[0].content


def test_the_note_says_which_file_and_what_to_do():
    messages = [a_read("app.py", big()), *an_edit("app.py"),
                a_read("app.py", big("y"))]

    sweep(messages)

    assert "app.py" in messages[0].content
    assert "read the file again" in messages[0].content


def test_it_frees_most_of_a_real_history():
    """The shape every multi-file change produces: read, edit, read again."""
    messages = [a_read("app.py", big()), *an_edit("app.py"),
                a_read("app.py", big("y"))]
    before = sum(estimate_text(m.content) for m in messages)

    _, freed = sweep(messages)

    assert freed / before > 0.4, f"only freed {freed / before:.0%}"


# --------------------------------------------------------------------------- #
# what it must never touch
# --------------------------------------------------------------------------- #


def test_the_newest_read_of_a_file_is_kept():
    """It is the current truth. Dropping it would make the model read again
    what it already has."""
    current = big("y")
    messages = [a_read("app.py", big()), *an_edit("app.py"),
                a_read("app.py", current)]

    sweep(messages)

    assert messages[-1].content == current


def test_a_file_read_twice_and_never_edited_is_left_alone():
    """A duplicate, not a lie. Rewriting it would cost the provider's cache
    and buy nothing — the older copy is still true."""
    body = big()
    messages = [a_read("app.py", body), a_read("app.py", body)]

    dropped, freed = sweep(messages)

    assert (dropped, freed) == (0, 0)
    assert messages[0].content == body


def test_an_edit_to_another_file_does_not_make_this_read_stale():
    body = big()
    messages = [a_read("app.py", body), *an_edit("other.py"),
                a_read("app.py", big("y"))]

    dropped, _ = sweep(messages)

    assert dropped == 0, "an edit elsewhere does not change this file"


def test_a_read_after_the_edit_is_not_stale():
    """Only reads that came *before* the edit are out of date."""
    messages = [*an_edit("app.py"), a_read("app.py", big()),
                a_read("app.py", big("y"))]

    dropped, _ = sweep(messages)

    assert dropped == 0


def test_a_small_read_is_not_worth_the_cache_it_costs():
    """Rewriting a message invalidates the provider's cache from that point.
    Worth it for ten thousand tokens; not for forty."""
    tiny = "     1\tx = 1\n     2\tx = 2\n"
    messages = [a_read("app.py", tiny), *an_edit("app.py"),
                a_read("app.py", tiny)]

    dropped, freed = sweep(messages)

    assert (dropped, freed) == (0, 0)
    assert messages[0].content == tiny


def test_a_read_with_no_recorded_path_is_left_alone():
    """Nothing can be known about it, so nothing is done to it."""
    orphan = Message.tool(call_id="x", name="read_file", content=big())
    messages = [orphan, *an_edit("app.py"), a_read("app.py", big("y"))]

    sweep(messages)

    assert orphan.content == big()


def test_nothing_but_read_results_is_touched():
    shell = Message.tool(call_id="s", name="run_shell", content=big())
    shell.meta["path"] = "app.py"
    messages = [shell, *an_edit("app.py"), a_read("app.py", big("y"))]

    sweep(messages)

    assert shell.content == big(), "command output is not a file snapshot"


# --------------------------------------------------------------------------- #
# it runs twice without doing more damage
# --------------------------------------------------------------------------- #


def test_sweeping_again_changes_nothing():
    """A second pass must find nothing left to do. Every sweep that changes
    something invalidates the provider's cache from that point, so one that
    repeats its own work would pay that price again for nothing."""
    messages = [a_read("app.py", big()), *an_edit("app.py"),
                a_read("app.py", big("y"))]

    first = sweep(messages)
    after = [m.content for m in messages]
    second = sweep(messages)

    assert first[0] == 1
    assert second == (0, 0), "it would bust the cache on every turn"
    assert [m.content for m in messages] == after


# --------------------------------------------------------------------------- #
# through the conversation, as the loop calls it
# --------------------------------------------------------------------------- #


def test_the_conversation_exposes_it():
    talk = Conversation()
    talk.add(Message.user("change it"))
    talk.add(a_read("app.py", big()))
    for message in an_edit("app.py"):
        talk.add(message)
    talk.add(a_read("app.py", big("y")))

    dropped, freed = talk.forget_superseded_reads()

    assert dropped == 1 and freed > WORTH_IT


def test_an_empty_conversation_is_fine():
    assert Conversation().forget_superseded_reads() == (0, 0)


# --------------------------------------------------------------------------- #
# when it runs, which the cache decides
#
# Measured against two live endpoints: a repeated prefix comes back 99% cached
# (MiMo 9,920 of 9,963; B.AI 8,576 of 8,637). Rewriting a message in the middle
# of the history stops everything after it matching, so the next request pays
# full price for the tail. On every step that would cost more than it saves.
# At the moment compaction would happen anyway it costs nothing extra —
# compaction busts the same cache and pays a model call on top.
# --------------------------------------------------------------------------- #


def test_it_is_tried_before_the_model_is_asked_to_summarise():
    import inspect

    from comodor.agent.loop import AgentLoop

    source = inspect.getsource(AgentLoop._maybe_compact)
    sweep = source.index("forget_superseded_reads")
    compact = source.index("self.conversation.compact")

    assert sweep < compact, "it would summarise away what it could have dropped"


def test_it_does_not_run_while_there_is_room():
    """Every sweep that finds something invalidates the provider's cache. One
    that was not needed is a bill for nothing."""
    import inspect

    from comodor.agent.loop import AgentLoop

    source = inspect.getsource(AgentLoop._maybe_compact)
    guard = source.index("needs_compaction")
    sweep = source.index("forget_superseded_reads")

    assert guard < sweep, "it sweeps before checking whether it needs to"


def test_a_sweep_that_frees_enough_avoids_compaction_entirely():
    """The point of doing it first: the history ends up smaller *and* more
    accurate, with nothing summarised away to get there."""
    import inspect

    from comodor.agent.loop import AgentLoop

    source = inspect.getsource(AgentLoop._maybe_compact)
    after = source[source.index("forget_superseded_reads"):]

    assert "needs_compaction" in after, "it compacts regardless of what it freed"
    assert after.index("needs_compaction") < after.index("self.conversation.compact")
