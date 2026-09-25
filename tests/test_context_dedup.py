"""Dedup, referencing and delta at the funnel (T072–T075, T087, T090, T092;
FR-052, FR-093, FR-098, FR-099, FR-100, FR-101, SC-028).

Identical material already resident is admitted as a reference to the call
that holds it; a changed file whose earlier copy is resident is admitted as
a delta against it; a changed source is never served from a stale hash; a
reference is used only while its target is still here; and expansion — the
agent reading again — returns the current content, never a cached copy.
"""

from __future__ import annotations

import difflib

from comodor.agent import AgentLoop, Conversation
from comodor.agent.context import Optimizer, _delta
from comodor.providers.base import Message, Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def big(marker="x", lines=200):
    return "\n".join(f"line {n}: {marker} = {n}" for n in range(lines))


def a_read(call_id, path, body):
    message = Message.tool(call_id=call_id, name="read_file", content=body)
    message.meta["path"] = path
    return message


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


# --------------------------------------------------------------------------- #
# T072 / T073 — identical content is a reference, never a second copy
# --------------------------------------------------------------------------- #


def test_identical_content_is_admitted_as_a_reference_and_the_original_is_untouched():
    conversation = Conversation()
    body = big()
    first = conversation.admit(a_read("r1", "a.py", body), path="a.py")
    second = conversation.admit(a_read("r2", "a.py", body), path="a.py")
    assert first.content == body, "the resident copy is never rewritten"
    assert second.content != body
    assert "unchanged since the result of call r1" in second.content
    assert second.meta["reference"] == "r1"
    assert conversation.referenced == 1 and conversation.bytes_saved > 0


def test_a_changed_source_is_never_served_from_the_stale_hash():
    conversation = Conversation()
    conversation.admit(a_read("r1", "a.py", big("x")), path="a.py")
    changed = conversation.admit(a_read("r2", "a.py", big("y")), path="a.py")
    assert "reference" not in changed.meta
    assert "unchanged" not in changed.content


def test_small_results_failures_and_other_paths_are_carried_in_full():
    conversation = Conversation()
    conversation.admit(a_read("r1", "a.py", "x = 1\n"), path="a.py")
    small = conversation.admit(a_read("r2", "a.py", "x = 1\n"), path="a.py")
    assert small.content == "x = 1\n"
    conversation.admit(a_read("r3", "b.py", big()), path="b.py")
    other = conversation.admit(a_read("r4", "c.py", big()), path="c.py")
    assert "reference" not in other.meta
    failed = Message.tool(call_id="r5", name="read_file", content=big(), is_error=True)
    failed.meta["path"] = "b.py"
    assert conversation.admit(failed, path="b.py").content == big()


def test_a_reference_is_used_only_while_its_target_is_still_resident():
    conversation = Conversation()
    body = big()
    first = conversation.admit(a_read("r1", "a.py", body), path="a.py")
    # The resident copy goes — swept, withheld or compacted — and the next
    # identical result is carried in full again.
    first.meta["superseded"] = True
    first.content = "[dropped]"
    again = conversation.admit(a_read("r2", "a.py", body), path="a.py")
    assert again.content == body
    assert "reference" not in again.meta


def test_a_reference_to_a_reference_is_never_made():
    conversation = Conversation()
    body = big()
    conversation.admit(a_read("r1", "a.py", body), path="a.py")
    second = conversation.admit(a_read("r2", "a.py", body), path="a.py")
    third = conversation.admit(a_read("r3", "a.py", body), path="a.py")
    assert second.meta["reference"] == "r1"
    # The newest resident copy is r2, which is itself a reference: no target,
    # so the third is carried in full rather than pointing at a pointer.
    assert third.content == body


def test_dedup_can_be_switched_off():
    conversation = Conversation(optimizer=Optimizer(()))
    body = big()
    conversation.admit(a_read("r1", "a.py", body), path="a.py")
    second = conversation.admit(a_read("r2", "a.py", body), path="a.py")
    assert second.content == body


# --------------------------------------------------------------------------- #
# T074 — delta context: delta plus base reconstructs the original exactly
# --------------------------------------------------------------------------- #


def test_a_changed_file_is_admitted_as_a_delta_against_the_resident_base():
    conversation = Conversation()
    before, after = big("x"), big("x").replace("line 50: x = 50", "line 50: x = 51")
    base = conversation.admit(a_read("r1", "a.py", before), path="a.py")
    delta = conversation.admit(a_read("r2", "a.py", after), path="a.py")
    assert delta.meta["delta_base"] == "r1"
    assert len(delta.content) < len(after) * 0.6
    assert "-line 50: x = 50" in delta.content and "+line 50: x = 51" in delta.content
    assert base.content == before


def test_delta_plus_base_reconstructs_the_original_exactly():
    before, after = big("x"), big("x").replace("line 50: x = 50", "line 50: x = 51")
    diff = _delta(before, after, "a.py")
    reconstructed = _apply(before, diff)
    assert reconstructed == after


def test_a_delta_larger_than_the_content_is_not_used():
    conversation = Conversation()
    conversation.admit(a_read("r1", "a.py", big("x")), path="a.py")
    rewritten = conversation.admit(a_read("r2", "a.py", big("zz", 250)), path="a.py")
    assert "delta" not in rewritten.meta
    assert rewritten.content == big("zz", 250)


def test_a_delta_is_never_made_against_an_evicted_base():
    conversation = Conversation()
    base = conversation.admit(a_read("r1", "a.py", big("x")), path="a.py")
    base.meta["withheld"] = True
    base.content = "[moved]"
    after = big("x").replace("line 50: x = 50", "line 50: x = 51")
    full = conversation.admit(a_read("r2", "a.py", after), path="a.py")
    assert full.content == after and "delta" not in full.meta


def _apply(base: str, diff: str) -> str:
    """Apply a unified diff produced by `_delta` (no external tool)."""
    result = base.splitlines(keepends=True)
    out: list[str] = []
    position = 0
    for line in diff.splitlines(keepends=True):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            header = line.split()[1]                # "-start,count"
            start = int(header[1:].split(",")[0]) - 1
            out.extend(result[position:start])
            position = start
            continue
        if line.startswith("+"):
            out.append(line[1:])
        elif line.startswith("-"):
            position += 1
        else:
            out.append(result[position])
            position += 1
    out.extend(result[position:])
    return "".join(out)


# --------------------------------------------------------------------------- #
# T075 — expansion reads the current state
# --------------------------------------------------------------------------- #


def test_expanding_a_reference_returns_the_current_content_not_a_cached_copy(config, bus):
    target = config.paths.project / "a.py"
    target.write_text(big("x"), encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[ToolCall(id="r1", name="read_file",
                                                     arguments={"path": "a.py"})]),
        Script(text="Reading again.", tool_calls=[ToolCall(id="r2", name="read_file",
                                                           arguments={"path": "a.py"})]),
        Script(text="Done."),
    ])
    agent.run("read a.py twice")
    tools = [m for m in agent.conversation.messages if m.role is Role.TOOL]
    assert tools[1].meta.get("reference") == "r1"

    # The file changes; expansion reads what is there now.
    target.write_text(big("y"), encoding="utf-8")
    from comodor.tools.fs import ReadFile

    fresh = ReadFile().run(agent.tool_context, path="a.py")
    assert "y = 7" in fresh.content and "x = 7" not in fresh.content


# --------------------------------------------------------------------------- #
# T092 — zero duplicate-bearing requests
# --------------------------------------------------------------------------- #


def test_no_request_carries_the_same_material_twice(config, bus):
    target = config.paths.project / "a.py"
    target.write_text(big("x"), encoding="utf-8")
    reads = [ToolCall(id=f"r{i}", name="read_file", arguments={"path": "a.py"})
             for i in range(3)]
    agent = make_agent(config, bus, [Script(text="Reading.", tool_calls=[call])
                                     for call in reads] + [Script(text="Done.")])
    agent.run("read a.py three times")
    for payload in agent.gateway.provider("fake").calls:
        bodies = [m.content for m in payload if m.role is Role.TOOL
                  and m.content.startswith("line 0:")]
        assert len(bodies) <= 1, "a request carried the same file twice"


def test_a_delta_is_reproducible_from_difflib_alone():
    before, after = "a\nb\nc\n", "a\nB\nc\n"
    assert _delta(before, after, "f") == "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="f (as in the conversation)", tofile="f (now)", n=2))


# --------------------------------------------------------------------------- #
# T194 — FR-099 re-verified: similarity alone never collapses anything
# --------------------------------------------------------------------------- #


def test_a_near_duplicate_is_never_collapsed_on_similarity_alone():
    """Differing by one character — and at another path, so no delta base
    applies — the second result is carried in full, never as a reference to
    the look-alike. Exact duplicates collapse only on content identity."""
    conversation = Conversation()
    body = big("x")
    near = body.replace("line 100: x = 100", "line 100: x = 101")
    assert near != body and len(near) == len(body)
    conversation.admit(a_read("r1", "a.py", body), path="a.py")
    second = conversation.admit(a_read("r2", "b.py", near), path="b.py")
    assert second.content == near
    assert "reference" not in second.meta and "delta_base" not in second.meta
    assert conversation.referenced == 0
