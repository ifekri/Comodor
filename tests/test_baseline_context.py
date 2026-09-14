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
