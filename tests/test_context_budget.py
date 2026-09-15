"""The budget manager and relevance ranking, under pressure (T070, T071,
T076, T078; FR-096, FR-097, FR-102, FR-049, SC-030).

Before a model call summarises history away, retrievable tool results are
moved aside in relevance order — least relevant first — with a pointer that
names how to get each one back. The withheld set is recomputed every turn
and never carried across one; the current request, an outstanding tool
result and the most recent results are never candidates. A compacted
summary names what it replaced, and the original request is never among it.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.agent.context import KEEP_RECENT_RESULTS, Optimizer
from comodor.agent.tokens import estimate_text
from comodor.providers.base import Message, Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def big(marker="x", lines=200):
    return "\n".join(f"line {n}: {marker} = {n}" for n in range(lines))


def a_round(index, path, body, name="read_file"):
    call = ToolCall(id=f"c{index}", name=name, arguments={"path": path})
    result = Message.tool(call_id=call.id, name=name, content=body)
    result.meta["path"] = path
    return [Message.assistant(f"Reading {path}.", [call]), result]


def a_history(paths=("database.py", "pricing.py", "auth.py", "cache.py")):
    conversation = Conversation()
    conversation.add(Message.user("Fix the pricing bug in pricing.py"))
    for index, path in enumerate(paths):
        for message in a_round(index, path, big(path[:3])):
            conversation.add(message)
    conversation.add(Message.user("Now fix it."))     # a settled seam for compaction
    # Enough recent traffic that the reads above are old.
    for index in range(KEEP_RECENT_RESULTS + 1):
        for message in a_round(100 + index, "notes.md", "short"):
            conversation.add(message)
    return conversation


# --------------------------------------------------------------------------- #
# T070 — the budget
# --------------------------------------------------------------------------- #


def test_nothing_is_withheld_within_the_budget():
    conversation = a_history()
    assert conversation.withhold(10_000_000) == (0, 0)
    assert conversation.withheld == []


def test_over_budget_results_are_moved_aside_until_it_fits():
    conversation = a_history()
    total = sum(estimate_text(m.content) for m in conversation.messages)
    budget = total - estimate_text(big("dat")) - 10
    moved, freed = conversation.withhold(budget)
    assert moved >= 1 and freed > 0
    assert sum(estimate_text(m.content) for m in conversation.messages) <= budget + 50
    for entry in conversation.withheld:
        assert entry.tokens > 0 and entry.reason


def test_what_was_withheld_is_determinable_and_retrievable():
    conversation = a_history()
    conversation.withhold(100)
    assert conversation.withheld
    for entry in conversation.withheld:
        message = next(m for m in conversation.messages if m.tool_call_id == entry.call_id)
        assert message.meta["withheld"] is True
        assert entry.path in message.content and "read_file" in message.content
        assert "Nothing is lost" in message.content


def test_the_request_the_outstanding_result_and_recent_results_are_never_candidates():
    conversation = a_history()
    request = conversation.messages[0]
    # An outstanding call: assistant asked, no result yet.
    conversation.add(Message.assistant("Reading more.", [
        ToolCall(id="pending", name="read_file", arguments={"path": "x.py"})]))
    conversation.withhold(1)
    assert request.content == "Fix the pricing bug in pricing.py"
    recent = [m for m in conversation.messages[-KEEP_RECENT_RESULTS:] if m.role is Role.TOOL]
    assert all("withheld" not in m.meta for m in recent)
    assert not any(entry.call_id == "pending" for entry in conversation.withheld)


def test_the_withheld_set_is_recomputed_each_turn_never_carried():
    conversation = a_history()
    conversation.withhold(100)
    first = list(conversation.withheld)
    assert first
    conversation.withhold(10_000_000)
    assert conversation.withheld == []
    conversation.withhold(100)
    assert [e.call_id for e in conversation.withheld] != [e.call_id for e in first] \
        or all("withheld" in next(m for m in conversation.messages
                                  if m.tool_call_id == e.call_id).meta for e in first)


def test_the_budget_can_be_switched_off():
    conversation = a_history()
    conversation.optimizer = Optimizer(())
    assert conversation.withhold(1) == (0, 0)


# --------------------------------------------------------------------------- #
# T071 — ranking: least relevant first, deterministic
# --------------------------------------------------------------------------- #


def test_the_least_relevant_result_goes_first_and_the_relevant_one_stays():
    conversation = a_history()
    conversation.withhold(sum(estimate_text(m.content) for m in conversation.messages)
                          - estimate_text(big("dat")) - 10)
    withheld = {entry.path for entry in conversation.withheld}
    assert "pricing.py" not in withheld, "what the request is about stays"
    assert withheld <= {"database.py", "auth.py", "cache.py"}


def test_a_fixed_corpus_yields_a_deterministic_order():
    orders = []
    for _ in range(3):
        conversation = a_history()
        conversation.withhold(50)
        orders.append([entry.call_id for entry in conversation.withheld])
    assert orders[0] == orders[1] == orders[2]


def test_without_ranking_the_order_is_age():
    conversation = a_history()
    conversation.optimizer = Optimizer(("budget",))
    conversation.withhold(50)
    ids = [entry.call_id for entry in conversation.withheld]
    assert ids == sorted(ids, key=lambda c: int(c[1:]))


# --------------------------------------------------------------------------- #
# under pressure, in the loop: withhold before a model summarises
# --------------------------------------------------------------------------- #


def test_under_pressure_the_loop_withholds_before_it_compacts(config, bus):
    config.agent.compact_at = 0.002          # a 2,000-token budget on a 1M window
    summarised = []
    agent = AgentLoop(config, Gateway(config, scripts=[Script(text="ok")]), ToolRegistry(),
                      bus, PermissionEngine(config, bus), a_history())
    agent._window = lambda: 1_000_000
    agent._summarise = lambda middle: summarised.append(len(middle)) or "brief"
    agent._maybe_compact("HEAD", [])
    assert agent.conversation.withheld, "the budget manager ran"


# --------------------------------------------------------------------------- #
# T076 — summaries carry provenance; T078 — bounded history keeps its rules
# --------------------------------------------------------------------------- #


def test_a_compacted_summary_names_what_it_replaced_and_keeps_the_request():
    conversation = a_history()
    request = conversation.messages[0]
    removed = conversation.compact(lambda middle: "the brief", keep_recent=4)
    assert removed > 0
    marker = conversation.messages[1]
    assert marker.meta["compacted"] is True
    assert "compacted summary of" in marker.content
    assert "database.py" in marker.content and "pricing.py" in marker.content
    assert marker.meta["sources"][:2] == ["database.py", "pricing.py"]
    assert conversation.messages[0] is request
    assert request.content not in marker.content


def test_provenance_can_be_switched_off_but_the_summary_still_exists():
    conversation = a_history()
    conversation.optimizer = Optimizer(())
    conversation.compact(lambda middle: "the brief", keep_recent=4)
    marker = conversation.messages[1]
    assert marker.content.startswith("[Earlier in this session — compacted summary]")


def test_no_cut_ever_orphans_a_tool_call_after_withholding():
    conversation = a_history()
    conversation.withhold(50)
    cut = conversation.safe_cut(keep_recent=4)
    pending = set()
    for message in conversation.messages[:cut]:
        if message.role is Role.ASSISTANT:
            pending.update(c.id for c in message.tool_calls)
        elif message.role is Role.TOOL:
            pending.discard(message.tool_call_id)
    assert not pending
