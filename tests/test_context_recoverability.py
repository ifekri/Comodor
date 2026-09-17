"""Nothing is lost, only relocated (T079, T080, T082, T095; FR-044, FR-047,
FR-087, FR-089, FR-090, FR-098, SC-014, SC-027).

Every optimization keeps correctness-critical evidence recoverable: a
spilled result points at a file that stays for the session; identical
output spills to one file; a passing log collapses to its outcome with the
whole log a read away; a failing log keeps every failing case, its location
and its message — never a flag; a partial read names what it withheld and
another read fetches it.
"""

from __future__ import annotations

from pathlib import Path

from comodor.tools import overflow
from comodor.tools.base import ToolResult
from comodor.tools.fs import ReadFile


def a_log(passing: bool, lines: int = 400) -> str:
    body = [f"tests/test_module_{n}.py::test_case_{n} PASSED" for n in range(lines)]
    if not passing:
        body[150] = "tests/test_module_150.py::test_case_150 FAILED"
        body[151:151] = [
            "    def test_case_150():",
            ">       assert total == 42",
            "E       AssertionError: assert 41 == 42",
            "tests/test_module_150.py:12: AssertionError",
        ]
        body.append("FAILED tests/test_module_150.py::test_case_150 - AssertionError")
        body.append(f"1 failed, {lines - 1} passed in 3.2s")
    else:
        body.append(f"{lines} passed in 3.2s")
    return "exit 0 in 3.2s\n" + "\n".join(body)


# --------------------------------------------------------------------------- #
# T080 — log summarisation
# --------------------------------------------------------------------------- #


def test_a_passing_run_collapses_to_its_outcome_with_the_whole_log_a_read_away(tool_context):
    result = ToolResult.success(a_log(True), exit_code=0)
    carried = overflow.contain(result, tool_context, "run_shell")
    assert carried.meta["log"] == "passed"
    assert "400 passed in 3.2s" in carried.content
    assert len(carried.content) < len(result.content) / 10
    spill = Path(carried.content.split("All of it is at ")[1].split(" —")[0])
    assert spill.read_text(encoding="utf-8") == a_log(True)


def test_a_failing_run_keeps_the_case_its_location_and_its_message(tool_context):
    result = ToolResult.success(a_log(False), exit_code=1)
    carried = overflow.contain(result, tool_context, "run_shell")
    assert carried.meta["log"] == "failed"
    assert "test_case_150 FAILED" in carried.content
    assert "AssertionError: assert 41 == 42" in carried.content
    assert "tests/test_module_150.py:12" in carried.content
    assert "1 failed, 399 passed" in carried.content
    assert len(carried.content) < len(result.content) / 4
    assert "Failing run" in carried.content and "nothing else is claimed" in carried.content


def test_a_failing_run_is_never_reduced_to_a_flag(tool_context):
    """Mutation check: a summariser that kept only the verdict is caught."""
    result = ToolResult.success(a_log(False), exit_code=1)
    real = overflow._summarise_log

    def flag_only(result, content, ctx, tool):
        return ToolResult(ok=result.ok, content="[Failing run]", meta={"log": "failed"})

    overflow._summarise_log = flag_only
    try:
        carried = overflow.contain(result, tool_context, "run_shell")
        assert "AssertionError" not in carried.content, "the mutation drops the case"
    finally:
        overflow._summarise_log = real
    carried = overflow.contain(result, tool_context, "run_shell")
    assert "AssertionError: assert 41 == 42" in carried.content


def test_a_failure_the_pattern_cannot_find_is_carried_as_it_was(tool_context):
    weird = "exit 0 in 1s\n" + "\n".join(f"row {n} fine" for n in range(300)) + "\nsomething odd"
    result = ToolResult.success(weird, exit_code=2)
    carried = overflow.contain(result, tool_context, "run_shell")
    assert "log" not in carried.meta
    assert "row 1 fine" in carried.content


def test_a_short_log_is_not_touched(tool_context):
    result = ToolResult.success("exit 0 in 1s\n3 passed in 0.1s", exit_code=0)
    assert overflow.contain(result, tool_context, "run_shell").content == result.content


def test_log_summaries_are_off_under_the_naive_strategy(tool_context):
    tool_context.config.agent.context_strategy = "naive"
    result = ToolResult.success(a_log(True), exit_code=0)
    carried = overflow.contain(result, tool_context, "run_shell")
    assert "log" not in carried.meta


# --------------------------------------------------------------------------- #
# T079 — spill dedup and pointer validity
# --------------------------------------------------------------------------- #


def test_identical_output_spills_to_one_file(tool_context):
    body = "x" * 30_000
    first = overflow.contain(ToolResult.success(body), tool_context, "grep")
    second = overflow.contain(ToolResult.success(body), tool_context, "grep")
    first_path = first.content.split("All of it is at ")[1].split(" —")[0]
    second_path = second.content.split("All of it is at ")[1].split(" —")[0]
    assert first_path == second_path
    assert Path(first_path).read_text(encoding="utf-8") == body


def test_changed_output_never_resolves_to_the_old_copy(tool_context):
    first = overflow.contain(ToolResult.success("a" * 30_000), tool_context, "grep")
    second = overflow.contain(ToolResult.success("b" * 30_000), tool_context, "grep")
    assert first.content.split("All of it is at ")[1] != second.content.split("All of it is at ")[1]


def test_a_pointer_handed_to_the_session_survives_pruning(tool_context, monkeypatch):
    monkeypatch.setattr(overflow, "KEEP_FILES", 1)
    first = overflow.contain(ToolResult.success("a" * 30_000), tool_context, "grep")
    first_path = Path(first.content.split("All of it is at ")[1].split(" —")[0])
    for marker in "bcdef":
        overflow.contain(ToolResult.success(marker * 30_000), tool_context, "grep")
    assert first_path.exists(), "a file the conversation points at is never pruned"
    assert str(first_path) in tool_context.spilled


def test_an_on_disk_file_is_pointed_at_in_place_never_copied(tool_context, config):
    target = config.paths.project / "big.py"
    body = "\n".join(f"x{n} = {n}" for n in range(3000))
    target.write_text(body, encoding="utf-8")
    result = ToolResult.success(body, path=str(target), lines=3000)
    carried = overflow.contain(result, tool_context, "read_file")
    assert "The file is unchanged at big.py" in carried.content
    assert not list(overflow.directory(tool_context).glob("read-file-*.txt"))


# --------------------------------------------------------------------------- #
# T082 — partial-file carriage
# --------------------------------------------------------------------------- #


def test_a_window_names_what_it_withheld_and_another_read_fetches_it(tool_context, config):
    target = config.paths.project / "long.py"
    target.write_text("\n".join(f"line{n} = {n}" for n in range(500)), encoding="utf-8")
    window = ReadFile().run(tool_context, path="long.py", offset=1, limit=50)
    assert "line49 = 49" in window.content and "line200 = 200" not in window.content
    assert "500" in window.content or "more" in window.content.lower()
    rest = ReadFile().run(tool_context, path="long.py", offset=200, limit=5)
    assert "line200 = 200" in rest.content
    assert not tool_context.was_read(target), "a window is not knowing the file"


def test_a_withheld_command_points_at_its_saved_output_not_a_rerun(tool_context):
    """A command's output that was spilled is named where it went.

    Replacing a withheld command result with "re-run the command" would repeat
    a side effect — a commit, a migration, a deploy. The spill file the result
    already points at is the safe way back.
    """
    from comodor.agent import Conversation
    from comodor.agent.context import KEEP_RECENT_RESULTS
    from comodor.providers.base import Message
    from comodor.tools import overflow

    body = "exit 0 in 2s\n" + "\n".join(f"line {n}: doing work" for n in range(4000))
    carried = overflow.contain(ToolResult.success(body, exit_code=0),
                               tool_context, "run_shell")
    spill = str(carried.meta.get("spill") or "")
    assert spill, "the command output should have been spilled"

    conversation = Conversation()
    conversation.add(Message.user("run the migration"))
    message = Message.tool(call_id="c1", name="run_shell", content=carried.content)
    message.meta.update(carried.meta)
    conversation.add(message)
    for index in range(KEEP_RECENT_RESULTS + 1):
        conversation.add(Message.tool(call_id=f"r{index}", name="read_file",
                                      content="short result"))

    moved, _ = conversation.withhold(1)
    assert moved >= 1
    withheld = next(m for m in conversation.messages if m.tool_call_id == "c1")
    assert withheld.meta.get("withheld") is True
    assert spill in withheld.content, "the pointer must name the saved output"
    assert "re-run" not in withheld.content, "a command must not be replayed"


def test_a_command_with_no_saved_output_is_never_withheld(tool_context):
    """With nothing on disk to point at, withholding would invite a replay."""
    from comodor.agent import Conversation
    from comodor.agent.context import KEEP_RECENT_RESULTS
    from comodor.providers.base import Message

    conversation = Conversation()
    conversation.add(Message.user("run the migration"))
    message = Message.tool(
        call_id="c1", name="run_shell",
        content="exit 0 in 2s\n" + "\n".join(f"line {n}: work" for n in range(4000)))
    conversation.add(message)
    for index in range(KEEP_RECENT_RESULTS + 1):
        conversation.add(Message.tool(call_id=f"r{index}", name="read_file",
                                      content="short result"))

    conversation.withhold(1)
    untouched = next(m for m in conversation.messages if m.tool_call_id == "c1")
    assert "withheld" not in untouched.meta


def test_a_referenced_base_is_never_withheld(tool_context):
    """A full result a live reference points at must stay resident.

    Only the dependent message carries the reference; the base it names is
    unmarked, so withholding it would leave the reference pointing at a
    retrieval pointer instead of the content it promised.
    """
    from comodor.agent import Conversation
    from comodor.agent.context import KEEP_RECENT_RESULTS
    from comodor.providers.base import Message

    conversation = Conversation()
    conversation.add(Message.user("read the file"))
    base = Message.tool(call_id="base", name="read_file", content="x" * 1000)
    base.meta["path"] = "big.py"
    base.meta["fingerprint"] = "fp"
    conversation.add(base)
    reference = Message.tool(call_id="ref", name="read_file",
                             content="unchanged since the result of call base above")
    reference.meta["reference"] = "base"
    conversation.add(reference)
    for index in range(KEEP_RECENT_RESULTS + 1):
        conversation.add(Message.tool(call_id=f"r{index}", name="read_file",
                                      content="short result"))

    conversation.withhold(1)
    assert "withheld" not in base.meta, "a referenced base was moved aside"


def test_an_unreferenced_full_result_is_still_withheld(tool_context):
    from comodor.agent import Conversation
    from comodor.agent.context import KEEP_RECENT_RESULTS
    from comodor.providers.base import Message

    conversation = Conversation()
    conversation.add(Message.user("read the file"))
    base = Message.tool(call_id="base", name="read_file", content="x" * 1000)
    base.meta["path"] = "big.py"
    base.meta["fingerprint"] = "fp"
    conversation.add(base)
    for index in range(KEEP_RECENT_RESULTS + 1):
        conversation.add(Message.tool(call_id=f"r{index}", name="read_file",
                                      content="short result"))

    moved, _ = conversation.withhold(1)
    assert moved >= 1
    assert base.meta.get("withheld") is True
