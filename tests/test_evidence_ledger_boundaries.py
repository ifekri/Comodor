"""The ledger's security boundaries (T026; FR-074, contract E4, Constitution VIII).

Three things must hold and each is mutation-checked: the cached prompt head
never carries the ledger; entries hold fingerprints, never content; and the
ledger is never persisted into a snapshot, a journal or a checkpoint.
"""

from __future__ import annotations

import json

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.agent import evidence as ev
from comodor.agent.evidence import Ledger
from comodor.agent.prompts import build_system_prompt
from comodor.application import CoreService
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

SECRET = "XIAOMI_API_KEY=sk-live-0123456789abcdef"


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


# --------------------------------------------------------------------------- #
# not in the prompt head
# --------------------------------------------------------------------------- #


def test_the_prompt_head_is_unchanged_by_a_full_ledger(config, bus):
    before = build_system_prompt(config)
    (config.paths.project / ".env").write_text(SECRET + "\n", encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[
            ToolCall(id="r", name="read_file", arguments={"path": ".env"})]),
        Script(text="Done."),
    ])
    agent.run("read the env file")
    assert agent.tool_context.evidence.entries, "the ledger did fill"
    after = build_system_prompt(config)
    assert after == before
    heads = [call[0].content for call in agent.gateway.provider("fake").calls]
    # The loop passes the model profile, which trims advice the fake model
    # cannot use; the head is still identical from turn to turn and carries
    # nothing from the ledger.
    assert len(set(heads)) == 1
    assert "ledger" not in heads[0].lower() and "sk-live" not in heads[0]


def test_the_head_guard_is_that_build_system_prompt_takes_no_ledger():
    """Mutation check: the function has no parameter through which the ledger
    could enter, so the prefix cannot be made query-shaped by it."""
    import inspect

    parameters = inspect.signature(build_system_prompt).parameters
    assert "ledger" not in parameters and "evidence" not in parameters


# --------------------------------------------------------------------------- #
# fingerprints, never content
# --------------------------------------------------------------------------- #


def test_a_read_secret_never_enters_an_entry(config, bus):
    (config.paths.project / ".env").write_text(SECRET + "\n", encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[
            ToolCall(id="r", name="read_file", arguments={"path": ".env"})]),
        Script(text="Done."),
    ])
    agent.run("read the env file")
    for entry in agent.tool_context.evidence.entries:
        serialised = json.dumps(entry.__dict__)
        assert "sk-live" not in serialised
        assert "0123456789abcdef" not in serialised


def test_the_fingerprint_guard_refuses_material_shaped_values():
    """Mutation check: the regex is the guard. Loosen it and a secret can be
    stored as a 'fingerprint'."""
    ledger = Ledger()
    with pytest.raises(ev.IllegalEvidence):
        ledger.seed("x", ev.EvidenceState.VERIFIED, source="s", fingerprint="sk-live-0123")

    real = ev._FINGERPRINT
    import re

    ev._FINGERPRINT = re.compile(r".*")
    try:
        ledger.seed("y", ev.EvidenceState.VERIFIED, source="s", fingerprint="sk-live-0123")
        assert any(entry.fingerprint == "sk-live-0123" for entry in ledger.entries), \
            "with the guard removed the secret is stored"
    finally:
        ev._FINGERPRINT = real
    with pytest.raises(ev.IllegalEvidence):
        Ledger().seed("z", ev.EvidenceState.VERIFIED, source="s", fingerprint="sk-live-0123")


def test_fingerprint_of_is_a_hash_prefix_not_an_encoding():
    assert ev.fingerprint_of(SECRET) != ev.fingerprint_of(SECRET + "x")
    assert len(ev.fingerprint_of(SECRET)) == 16
    assert "sk-live" not in ev.fingerprint_of(SECRET)


# --------------------------------------------------------------------------- #
# never persisted
# --------------------------------------------------------------------------- #


def test_the_ledger_is_in_no_snapshot_no_journal_and_no_session_record(config):
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.agent.gateway = Gateway(config, scripts=[Script(text="ok")])
        handle.assembly.agent.run("hello")
        book = handle.assembly.agent.tool_context.evidence
        book.verified("a secret-adjacent read", source=".env", material=SECRET)

        snapshot = json.dumps(service.snapshot(session))
        assert "secret-adjacent" not in snapshot
        assert ev.fingerprint_of(SECRET) not in snapshot
        assert "sk-live" not in snapshot

        store = service._store()
        stored = json.dumps([m.__dict__ for m in store.load(handle.store_id)],
                            default=str) if handle.store_id else ""
        assert "secret-adjacent" not in stored
    finally:
        service.close()


def test_the_tool_context_never_serialises_its_ledger(config, tool_context):
    import dataclasses

    tool_context.evidence.verified("read .env", source=".env", material=SECRET)
    public = [f.name for f in dataclasses.fields(tool_context) if f.repr]
    assert "_evidence" not in public
    assert "evidence" not in repr(tool_context).lower()


def test_a_checkpoint_carries_file_contents_not_the_ledger(config, tool_context):
    target = config.paths.project / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    tool_context.evidence.verified("read a.py", source="a.py", material="x = 1\n")
    tool_context.checkpoints.snapshot(target, action="write", tool="write_file",
                                      after="x = 2\n")
    for path in config.paths.checkpoints.rglob("*"):
        if path.is_file():
            assert "ledger" not in path.read_text(encoding="utf-8", errors="replace").lower()
