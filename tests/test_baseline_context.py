"""Characterization: context assembly and the compaction boundary (T002).

Pins how `Conversation.render()` shapes a request and where `safe_cut` is
allowed to cut, before spec 002 puts optimizations behind that one funnel
(FR-049, FR-051). Every optimization added later must leave these true.
"""

from __future__ import annotations

from comodor.agent.context import Conversation
from comodor.providers.base import Message, Role, ToolCall


def a_round(index: int) -> list[Message]:
    """One assistant tool call and its result."""
    call = ToolCall(id=f"c{index}", name="read_file", arguments={"path": f"f{index}.py"})
    return [Message.assistant(f"Reading {index}.", [call]),
            Message.tool(call_id=call.id, name="read_file", content=f"body {index}")]


def test_render_is_the_system_prompt_followed_by_every_message_in_order():
    conversation = Conversation()
    conversation.add(Message.user("do the thing", briefing="playbook"))
    for message in a_round(1):
        conversation.add(message)
    conversation.add(Message.assistant("Done."))

    payload = conversation.render("HEAD")

    assert payload[0].role is Role.SYSTEM and payload[0].content == "HEAD"
    assert [m.role for m in payload[1:]] == [m.role for m in conversation.messages]
    assert [m.content for m in payload[1:]] == [m.content for m in conversation.messages]
    # The briefing travels on the message, not the head.
    assert payload[1].briefing == "playbook"
    assert "playbook" not in payload[0].content


def test_render_does_not_copy_or_rewrite_messages():
    conversation = Conversation()
    original = conversation.add(Message.user("hello"))
    assert conversation.render("HEAD")[1] is original


def test_no_cut_when_the_history_is_short():
    conversation = Conversation()
    conversation.add(Message.user("start"))
    for message in a_round(1):
        conversation.add(message)
    assert conversation.safe_cut(keep_recent=8) == 0
    assert conversation.compact(lambda _m: "brief") == 0


def test_the_cut_never_orphans_a_tool_call():
    """A cut lands only on a user message with nothing outstanding."""
    conversation = Conversation()
    conversation.add(Message.user("start"))
    for index in range(1, 12):
        for message in a_round(index):
            conversation.add(message)
        conversation.add(Message.user(f"and then {index}"))

    cut = conversation.safe_cut(keep_recent=4)
    assert cut > 0
    assert conversation.messages[cut].role is Role.USER

    pending: set[str] = set()
    for message in conversation.messages[:cut]:
        if message.role is Role.ASSISTANT:
            pending.update(call.id for call in message.tool_calls)
        elif message.role is Role.TOOL:
            pending.discard(message.tool_call_id)
    assert not pending, "a tool call before the cut has its result after it"


def test_a_cut_is_never_inside_the_kept_recent_tail():
    conversation = Conversation()
    conversation.add(Message.user("start"))
    for index in range(1, 12):
        for message in a_round(index):
            conversation.add(message)
        conversation.add(Message.user(f"and then {index}"))
    cut = conversation.safe_cut(keep_recent=4)
    assert cut <= len(conversation.messages) - 4


def test_compaction_keeps_the_original_request_verbatim():
    conversation = Conversation()
    request = conversation.add(Message.user("the original request"))
    for index in range(1, 12):
        for message in a_round(index):
            conversation.add(message)
        conversation.add(Message.user(f"and then {index}"))

    removed = conversation.compact(lambda middle: f"brief of {len(middle)}", keep_recent=4)

    assert removed > 0
    assert conversation.messages[0] is request
    assert conversation.messages[1].role is Role.USER
    assert conversation.messages[1].meta.get("compacted") is True
    assert conversation.messages[1].content.startswith("[Earlier in this session")
    assert conversation.compactions == 1


def test_a_failed_summary_loses_nothing():
    conversation = Conversation()
    conversation.add(Message.user("start"))
    for index in range(1, 12):
        for message in a_round(index):
            conversation.add(message)
        conversation.add(Message.user(f"and then {index}"))
    before = list(conversation.messages)

    def broken(_messages):
        raise RuntimeError("provider down")

    assert conversation.compact(broken, keep_recent=4) == 0
    assert conversation.messages == before


def test_needs_compaction_is_measured_against_the_rendered_payload():
    conversation = Conversation()
    conversation.add(Message.user("x" * 4000))
    with_head = conversation.used_tokens("H" * 4000)
    without = conversation.used_tokens()
    assert with_head > without
    assert conversation.needs_compaction(limit=with_head, threshold=1.0, system_prompt="H" * 4000)
    assert not conversation.needs_compaction(limit=with_head * 10, threshold=0.75,
                                             system_prompt="H" * 4000)


def test_compaction_keeps_a_base_a_surviving_reference_points_at():
    """A reference promises its base is still in the conversation.

    Summarising that base away would leave the pointer standing for a lossy
    summary instead of the content it named, so the cut moves back to keep
    the base verbatim (FR-100, FR-101).
    """
    conversation = Conversation()
    conversation.add(Message.user("start"))
    big = "A" * 600
    first = Message.tool(call_id="c1", name="read_file", content=big)
    first.meta["path"] = "f.py"
    conversation.admit(first, path="f.py")

    # The base ages into the summarised middle while a later, identical read
    # stays in the tail as a reference to it.
    for index in range(10):
        conversation.add(Message.user(f"turn {index}"))
        conversation.add(Message.assistant("ok"))
    second = Message.tool(call_id="c2", name="read_file", content=big)
    second.meta["path"] = "f.py"
    conversation.admit(second, path="f.py")
    assert second.meta.get("reference") == "c1", "the second read points at the first"
    conversation.add(Message.user("last"))
    conversation.add(Message.assistant("ok"))

    conversation.compact(lambda _middle: "a brief", keep_recent=4)

    base = next((m for m in conversation.messages if m.tool_call_id == "c1"), None)
    assert base is not None, "the base a live reference names stays verbatim"
    assert base.content == big


def test_a_reference_dependency_survives_a_session_round_trip(tmp_path):
    """The link from a reference or delta to its base is a promise that has to
    survive a resume, or compaction can summarise the base away (FR-101)."""
    from comodor.session.store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    reference = Message.tool(call_id="c2", name="read_file",
                             content="[unchanged since call c1 above]")
    reference.meta["reference"] = "c1"
    store.append("s1", reference)
    delta = Message.tool(call_id="c3", name="read_file", content="[changed]")
    delta.meta["delta_base"] = "c2"
    delta.meta["delta"] = True
    store.append("s1", delta)

    restored = store.load("s1")

    assert restored[0].meta.get("reference") == "c1"
    assert restored[1].meta.get("delta_base") == "c2"
    assert restored[1].meta.get("delta") is True


def test_a_tool_source_survives_a_session_round_trip(tmp_path):
    """A resumed observation keeps the file it was about and the fingerprint
    of what was there, or a learned item resting on it can never be
    invalidated when that file changes (FR-060, FR-114)."""
    from comodor.session.store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    read = Message.tool(call_id="c1", name="read_file", content="runs-on: ubuntu-latest")
    read.meta["path"] = "ci.yml"
    read.meta["fingerprint"] = "0123456789abcdef"
    store.append("s1", read)

    [restored] = store.load("s1")

    assert restored.meta.get("path") == "ci.yml"
    assert restored.meta.get("fingerprint") == "0123456789abcdef"


def test_a_withheld_marker_survives_a_session_round_trip(tmp_path):
    """A withheld message keeps its path and fingerprint; without the mark a
    resumed session reads the retrieval note as a resident full copy and a
    reread is replaced by a reference to content that is not there (FR-101)."""
    from comodor.agent.context import Conversation
    from comodor.session.store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    withheld = Message.tool(call_id="c1", name="read_file",
                            content="[read x.py again with read_file]")
    withheld.meta["path"] = "x.py"
    withheld.meta["fingerprint"] = "0123456789abcdef"
    withheld.meta["withheld"] = True
    store.append("s1", withheld)

    [restored] = store.load("s1")
    assert restored.meta.get("withheld") is True

    conversation = Conversation()
    conversation.extend([restored])
    assert conversation._resident("x.py") is None, \
        "a retrieval pointer is not a resident full copy"
