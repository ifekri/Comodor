"""No cached or summarised representation survives the event that falsifies it
(T077, T083, T084, T094; FR-101, FR-102, FR-103, FR-104, FR-105, SC-029).

Six events, each against every optimization it applies to: a content-hash
change, a source-file change, a branch/worktree change, a tool-output
change, a superseded repository fact, and a stale learned fact. And the one
non-event: the passage of turns, which invalidates nothing.
"""

from __future__ import annotations

import subprocess

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.agent.evidence import EvidenceState as S
from comodor.agent.evidence import Ledger
from comodor.providers.base import Message, Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def big(marker="x", lines=200):
    return "\n".join(f"line {n}: {marker} = {n}" for n in range(lines))


def a_read(call_id, path, body, name="read_file"):
    message = Message.tool(call_id=call_id, name=name, content=body)
    message.meta["path"] = path
    return message


# --------------------------------------------------------------------------- #
# the dedup / reference / delta representations
# --------------------------------------------------------------------------- #


def test_content_hash_change_yields_a_new_entry_never_the_stale_reference():
    conversation = Conversation()
    conversation.admit(a_read("r1", "a.py", big("x")), path="a.py")
    changed = conversation.admit(a_read("r2", "a.py", big("y")), path="a.py")
    assert "reference" not in changed.meta


def test_source_file_change_invalidates_the_reference_and_the_delta_base(config, bus):
    target = config.paths.project / "a.py"
    target.write_text(big("x"), encoding="utf-8")
    edit_call = ToolCall(id="e1", name="edit_file", arguments={
        "path": "a.py", "old_string": "line 5: x = 5\n", "new_string": "line 5: x = 55\n"})
    scripts = [Script(text="Reading.", tool_calls=[ToolCall(id="r1", name="read_file",
                                                             arguments={"path": "a.py"})]),
               Script(text="Editing.", tool_calls=[edit_call]),
               Script(text="Reading again.", tool_calls=[ToolCall(id="r2", name="read_file",
                                                                   arguments={"path": "a.py"})]),
               Script(text="Done.")]
    agent = AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    agent.run("read, edit, read a.py")
    tools = {m.tool_call_id: m for m in agent.conversation.messages if m.role is Role.TOOL}
    assert "reference" not in tools["r2"].meta, "the changed file is not 'unchanged'"
    assert "x = 55" in tools["r2"].content


def test_tool_output_change_is_a_new_result_not_a_reference():
    conversation = Conversation()
    first = a_read("g1", "", "match one\n" * 100, name="grep")
    conversation.admit(first)
    second = a_read("g2", "", "match two\n" * 100, name="grep")
    conversation.admit(second)
    assert "reference" not in second.meta and second.content.startswith("match two")


def test_branch_or_worktree_change_is_a_content_change(config, bus, tmp_path):
    """A checkout rewrites the file; the fingerprint moves with it, so the
    resident copy is not what a reference would name."""
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git not available")
    repo = config.paths.project
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.py").write_text(big("main"), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "main"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "a.py").write_text(big("feature"), encoding="utf-8")
    subprocess.run(["git", "commit", "-q", "-am", "feature"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)

    conversation = Conversation()
    conversation.admit(a_read("r1", "a.py", (repo / "a.py").read_text(encoding="utf-8")),
                       path="a.py")
    subprocess.run(["git", "checkout", "-q", "feature"], cwd=repo, check=True)
    moved = conversation.admit(a_read("r2", "a.py", (repo / "a.py").read_text(encoding="utf-8")),
                               path="a.py")
    assert "reference" not in moved.meta
    assert "feature = 7" in moved.content or "delta" in moved.meta


# --------------------------------------------------------------------------- #
# the ledger: verified facts, citations, and the passage of turns
# --------------------------------------------------------------------------- #


def test_a_source_change_sends_the_verified_fact_back_to_unknown_and_drops_its_citation():
    ledger = Ledger()
    first = ledger.verified("read a.py", source="a.py", material=big("x"), reference="call r1")
    assert ledger.cite("read a.py") == "call r1"
    second = ledger.verified("read a.py", source="a.py", material=big("y"), reference="call r2")
    assert ledger.get(first.id).state is S.UNKNOWN
    assert second.state is S.VERIFIED
    assert ledger.cite("read a.py") == "call r2"
    assert not ledger.may_rely_on_entry(first) if hasattr(ledger, "may_rely_on_entry") else True


def test_the_same_source_unchanged_is_not_re_verified_and_counts_as_a_rediscovery():
    ledger = Ledger()
    first = ledger.verified("read a.py", source="a.py", material=big("x"), reference="call r1")
    again = ledger.verified("read a.py", source="a.py", material=big("x"), reference="call r2")
    assert again is first
    assert len([e for e in ledger.entries if e.source == "a.py"]) == 1


def test_the_passage_of_turns_invalidates_nothing():
    ledger = Ledger()
    entry = ledger.verified("read a.py", source="a.py", material=big("x"))
    for step in range(1, 50):
        ledger.step = step
    assert ledger.get(entry.id).state is S.VERIFIED
    assert ledger.cite("read a.py") == "a.py"


def test_a_superseded_repository_fact_is_contradicted_not_carried():
    ledger = Ledger()
    fact = ledger.verified("the port is 8080", source="config.py", material="PORT = 8080")
    ledger.contradict(fact.id)
    assert ledger.get(fact.id).state is S.FAILED
    assert ledger.cite("the port is 8080") == ""
    assert not ledger.may_rely_on("the port is 8080")


def test_a_stale_learned_fact_is_not_cited(config, bus):
    """A knowledge entry whose record went stale is contradicted in the
    ledger, so nothing the turn says can rest on it (FR-114)."""
    ledger = Ledger()
    learned = ledger.knowledge("the project targets PostgreSQL 15", ref="fact:12")
    assert ledger.cite("the project targets PostgreSQL 15") == "knowledge:fact:12"
    ledger.contradict(learned.id)
    assert ledger.cite("the project targets PostgreSQL 15") == ""


def test_rediscovery_falls_on_a_fixed_multi_file_task(config, bus):
    """T083: reading the same unchanged files again costs a reference, not
    the material, and the ledger counts the repeat rather than re-verifying."""
    for name in ("a.py", "b.py"):
        (config.paths.project / name).write_text(big(name), encoding="utf-8")
    calls = [ToolCall(id=f"{name}-{n}", name="read_file", arguments={"path": name})
             for n in range(2) for name in ("a.py", "b.py")]
    scripts = [Script(text="Reading.", tool_calls=[call]) for call in calls] + [Script(text="ok")]
    agent = AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    agent.run("read both files twice")
    book = agent.tool_context.evidence
    assert book.rediscoveries("a.py") == 1 and book.rediscoveries("b.py") == 1
    verified = [e for e in book.entries if e.state is S.VERIFIED and e.source in ("a.py", "b.py")]
    assert len(verified) == 2, "one verified entry per file, not per read"
    tools = [m for m in agent.conversation.messages if m.role is Role.TOOL]
    assert sum(1 for m in tools if m.meta.get("reference")) == 2


def test_compacted_summaries_name_sources_so_a_change_can_be_traced():
    from comodor.agent.context import KEEP_RECENT_RESULTS

    conversation = Conversation()
    conversation.add(Message.user("start"))
    for index in range(3):
        call = ToolCall(id=f"c{index}", name="read_file", arguments={"path": f"f{index}.py"})
        conversation.add(Message.assistant("Reading.", [call]))
        conversation.add(a_read(call.id, f"f{index}.py", big()))
    conversation.add(Message.user("go on"))
    for index in range(KEEP_RECENT_RESULTS + 1):
        conversation.add(Message.user(f"and {index}"))
    conversation.compact(lambda middle: "brief", keep_recent=4)
    marker = conversation.messages[1]
    assert marker.meta["sources"] == ["f0.py", "f1.py", "f2.py"]
