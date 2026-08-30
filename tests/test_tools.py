"""Tools, permissions, checkpoints, and redaction."""

from __future__ import annotations

import pytest

from comodor.events import Request
from comodor.safety import ALLOW, ALLOW_ALWAYS, DENY, CheckpointStore, PermissionEngine, Risk
from comodor.safety.redact import redact
from comodor.tools.fs import change_stats, unified_diff
from comodor.tools.web import html_to_text

# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #


def test_write_then_read_round_trip(tools, tool_context, workspace):
    result = tools.invoke("write_file", tool_context,
                          {"path": "app.py", "content": "def main():\n    pass\n"})
    assert result.ok
    assert (workspace / "app.py").read_text() == "def main():\n    pass\n"

    read = tools.invoke("read_file", tool_context, {"path": "app.py"})
    assert "def main():" in read.content
    # Line numbers help the model cite `app.py:42`. Not padded: six spaces on
    # every line was 6-7% of a real file read, spent on alignment nobody reads.
    assert read.content.startswith("1\t")


def test_edit_requires_a_unique_anchor(tools, tool_context, workspace):
    (workspace / "dup.py").write_text("value = 1\nvalue = 1\n", encoding="utf-8")

    ambiguous = tools.invoke("edit_file", tool_context,
                             {"path": "dup.py", "old_string": "value = 1",
                              "new_string": "value = 2"})
    assert not ambiguous.ok
    assert "2 places" in ambiguous.content

    replaced = tools.invoke("edit_file", tool_context,
                            {"path": "dup.py", "old_string": "value = 1",
                             "new_string": "value = 2", "replace_all": True})
    assert replaced.ok
    assert (workspace / "dup.py").read_text() == "value = 2\nvalue = 2\n"


def test_edit_reports_a_missing_anchor_instead_of_guessing(tools, tool_context, workspace):
    (workspace / "a.py").write_text("hello\n", encoding="utf-8")
    result = tools.invoke("edit_file", tool_context,
                          {"path": "a.py", "old_string": "goodbye",
                           "new_string": "hi"})
    assert not result.ok
    assert "not found" in result.content
    assert (workspace / "a.py").read_text() == "hello\n"     # unchanged


def test_writes_outside_the_workspace_are_refused(tools, tool_context, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    result = tools.invoke("write_file", tool_context,
                          {"path": str(outside), "content": "nope"})
    assert not result.ok
    assert "outside the workspace" in result.content
    assert not outside.exists()


def test_reading_a_binary_file_fails_cleanly(tools, tool_context, workspace):
    (workspace / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    result = tools.invoke("read_file", tool_context, {"path": "blob.bin"})
    assert not result.ok
    assert "binary" in result.content


def test_a_slice_of_a_very_large_file_can_actually_be_read(tools, tool_context,
                                                           workspace):
    """The tool used to refuse anything over the byte cap with "read a slice
    with offset/limit instead", and then refuse the slice too — it loaded the
    whole file before taking one. The advice could not be followed at any
    offset, which made a large log unreadable by the tool that suggested how to
    read it."""
    (workspace / "big.txt").write_text(
        "".join(f"line {n}\n" for n in range(200_000)), encoding="utf-8")
    assert (workspace / "big.txt").stat().st_size > \
        tool_context.config.safety.max_file_read_bytes

    result = tools.invoke("read_file", tool_context,
                          {"path": "big.txt", "offset": 150_000, "limit": 3})

    assert result.ok, result.content
    assert "line 149999" in result.content
    assert result.meta["lines"] == 200_000


def test_a_file_too_large_even_to_scan_says_so(tools, tool_context, workspace):
    tool_context.config.safety.max_file_scan_bytes = 100
    (workspace / "huge.txt").write_text("x" * 500, encoding="utf-8")

    result = tools.invoke("read_file", tool_context, {"path": "huge.txt"})

    assert not result.ok
    assert "grep" in result.content


def test_an_offset_past_the_end_is_not_an_error(tools, tool_context, workspace):
    (workspace / "short.txt").write_text("one\ntwo\n", encoding="utf-8")

    result = tools.invoke("read_file", tool_context,
                          {"path": "short.txt", "offset": 900})

    assert result.ok
    assert "2 lines" in result.content


def test_diff_and_stats_describe_the_change():
    before, after = "a\nb\nc\n", "a\nB\nc\nd\n"
    diff = unified_diff(before, after, "x.py")
    assert "-b" in diff and "+B" in diff
    assert change_stats(before, after) == (2, 1)


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #


def test_grep_finds_matches_and_reports_locations(tools, tool_context, workspace):
    (workspace / "src" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (workspace / "src" / "b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")

    result = tools.invoke("grep", tool_context, {"pattern": r"def \w+", "path": "."})
    assert result.ok
    assert "a.py" in result.content and "b.py" in result.content
    assert result.meta["files"] == 2


def test_grep_reports_a_bad_regex_rather_than_raising(tools, tool_context):
    result = tools.invoke("grep", tool_context, {"pattern": "([unclosed"})
    assert not result.ok
    assert "regular expression" in result.content


def test_grep_skips_ignored_directories(tools, tool_context, workspace):
    (workspace / ".gitignore").write_text("build/\n", encoding="utf-8")
    (workspace / "build").mkdir()
    (workspace / "build" / "junk.py").write_text("SECRET_MARKER = 1\n", encoding="utf-8")
    (workspace / "src" / "real.py").write_text("SECRET_MARKER = 2\n", encoding="utf-8")

    result = tools.invoke("grep", tool_context, {"pattern": "SECRET_MARKER"})
    assert "real.py" in result.content
    assert "junk.py" not in result.content


def test_glob_matches_by_pattern(tools, tool_context, workspace):
    (workspace / "src" / "one.py").write_text("", encoding="utf-8")
    (workspace / "src" / "two.txt").write_text("", encoding="utf-8")

    result = tools.invoke("glob", tool_context, {"pattern": "**/*.py"})
    assert "one.py" in result.content
    assert "two.txt" not in result.content


# --------------------------------------------------------------------------- #
# shell
# --------------------------------------------------------------------------- #


def test_shell_returns_output_and_exit_code(tools, tool_context):
    result = tools.invoke("run_shell", tool_context, {"command": "echo comodor-ok"})
    assert result.ok
    assert "comodor-ok" in result.content
    assert result.meta["exit_code"] == 0


def test_a_failing_command_is_reported_as_a_failure(tools, tool_context):
    result = tools.invoke("run_shell", tool_context, {"command": "exit 3"})
    assert not result.ok
    assert result.meta["exit_code"] == 3


def test_denied_commands_are_refused_before_they_run(tools, tool_context):
    for command in ("rm -rf /", "sudo rm -rf /  ", "mkfs.ext4 /dev/sda"):
        result = tools.invoke("run_shell", tool_context, {"command": command})
        assert not result.ok
        assert "blocked pattern" in result.content


def test_python_snippets_run_and_report_output(tools, tool_context):
    result = tools.invoke("run_python", tool_context, {"code": "print(6 * 7)"})
    assert result.ok
    assert "42" in result.content


# --------------------------------------------------------------------------- #
# permissions
# --------------------------------------------------------------------------- #


def test_safe_tools_do_not_prompt(config, bus):
    config.safety.auto_approve_safe = True
    engine = PermissionEngine(config, bus)
    assert engine.check("read_file", Risk.SAFE, "read x")


def test_a_write_prompts_and_honours_the_answer(config, bus):
    config.safety.auto_approve_writes = False
    engine = PermissionEngine(config, bus)
    answers = {"value": DENY}

    def responder(event):
        request = event.payload.get("request")
        if isinstance(request, Request):
            request.answer(answers["value"])

    bus.subscribe(responder)

    assert not engine.check("write_file", Risk.WRITE, "write x")
    answers["value"] = ALLOW
    assert engine.check("write_file", Risk.WRITE, "write x")


def test_always_allow_is_remembered_for_the_session(config, bus):
    config.safety.auto_approve_shell = False
    engine = PermissionEngine(config, bus)
    prompts = []

    def responder(event):
        request = event.payload.get("request")
        if isinstance(request, Request):
            prompts.append(request)
            request.answer(ALLOW_ALWAYS)

    bus.subscribe(responder)

    assert engine.check("run_shell", Risk.DANGEROUS, "run x", key="run_shell:git")
    assert engine.check("run_shell", Risk.DANGEROUS, "run y", key="run_shell:git")
    assert len(prompts) == 1, "the second call should use the remembered grant"


def test_shell_grants_are_scoped_to_the_command_not_the_tool(config, bus):
    from comodor.tools.shell import RunShell

    tool = RunShell()
    assert tool.permission_key({"command": "git status"}) == "run_shell:git"
    assert tool.permission_key({"command": "rm -rf build"}) == "run_shell:rm"


def test_headless_without_a_surface_refuses_rather_than_assuming_yes(config):
    config.safety.auto_approve_writes = False
    engine = PermissionEngine(config, bus=None)
    decision = engine.check("write_file", Risk.WRITE, "write x")
    assert not decision
    assert "no interactive approval" in decision.reason


def test_chat_mode_switches_every_tool_off(config, bus):
    config.agent.mode = "chat"
    engine = PermissionEngine(config, bus)
    assert not engine.check("read_file", Risk.SAFE, "read x")


# --------------------------------------------------------------------------- #
# checkpoints
# --------------------------------------------------------------------------- #


def test_undo_restores_previous_content(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")
    store = CheckpointStore(tmp_path / ".checkpoints")

    store.snapshot(target, action="edit")
    target.write_text("changed", encoding="utf-8")

    assert store.undo_last() == [str(target)]
    assert target.read_text() == "original"


def test_undo_removes_a_file_the_agent_created(tmp_path):
    target = tmp_path / "new.txt"
    store = CheckpointStore(tmp_path / ".checkpoints")

    store.snapshot(target, action="create")
    target.write_text("created", encoding="utf-8")

    store.undo_last()
    assert not target.exists()


def test_undo_walks_backwards_through_several_changes(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("v1", encoding="utf-8")
    store = CheckpointStore(tmp_path / ".checkpoints")

    store.snapshot(target)
    target.write_text("v2", encoding="utf-8")
    store.snapshot(target)
    target.write_text("v3", encoding="utf-8")

    store.undo_last()
    assert target.read_text() == "v2"
    store.undo_last()
    assert target.read_text() == "v1"
    assert store.undo_last() == []


def test_identical_content_is_stored_once(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("same", encoding="utf-8")
    store = CheckpointStore(tmp_path / ".checkpoints")

    for _ in range(5):
        store.snapshot(target)

    assert len(list((tmp_path / ".checkpoints" / "blobs").iterdir())) == 1


# --------------------------------------------------------------------------- #
# redaction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("secret", [
    "sk-ant-api03-" + "a" * 40,
    "sk-or-v1-" + "b" * 40,
    "ghp_" + "c" * 36,
    "AKIA" + "D" * 16,
    "tp-" + "e" * 40,
])
def test_known_key_shapes_are_masked(secret):
    masked = redact(f"the key is {secret} ok")
    assert secret not in masked
    assert "REDACTED" in masked


def test_secret_looking_assignments_are_masked():
    masked = redact("DATABASE_PASSWORD=hunter2hunter2\nAPI_TOKEN: 'abcdefghijkl'")
    assert "hunter2hunter2" not in masked
    assert "abcdefghijkl" not in masked


def test_known_session_secrets_are_masked_whatever_their_shape():
    masked = redact("value=wibble-wobble-123", extra=["wibble-wobble-123"])
    assert "wibble-wobble-123" not in masked


def test_ordinary_text_survives_redaction():
    text = "the function get_user_token() is defined in auth.py"
    assert redact(text) == text


def test_tool_output_is_redacted_before_it_reaches_the_model(tools, tool_context, workspace):
    (workspace / ".env").write_text("OPENAI_API_KEY=sk-" + "z" * 40, encoding="utf-8")
    result = tools.invoke("read_file", tool_context, {"path": ".env"})
    assert "z" * 40 not in result.content
    assert "REDACTED" in result.content


# --------------------------------------------------------------------------- #
# web helpers
# --------------------------------------------------------------------------- #


def test_html_is_reduced_to_readable_text():
    markup = ("<html><head><style>body{color:red}</style></head><body>"
              "<h1>Title</h1><p>First&nbsp;paragraph.</p>"
              "<script>alert(1)</script><p>Second.</p></body></html>")
    text = html_to_text(markup)

    assert "Title" in text and "First paragraph." in text and "Second." in text
    assert "alert" not in text and "color:red" not in text


# --------------------------------------------------------------------------- #
# arguments that were not JSON
#
# `parse_arguments` files what it cannot decode under `__raw__` rather than
# crashing. That then reached the tool as an unexpected keyword, so the model
# was told "invalid arguments for read_file: unexpected keyword __raw__" —
# which names neither the problem nor the fix. A weaker model told that emits
# the same thing again.
# --------------------------------------------------------------------------- #


def test_a_malformed_argument_blob_is_named_as_such(tool_context, tools):
    result = tools.invoke("read_file", tool_context, {"__raw__": "path=a.py"})

    assert not result.ok
    assert "not valid JSON" in result.content
    assert "__raw__" not in result.content, \
        "an internal key is not something the model can act on"


def test_it_is_shown_the_object_it_should_have_sent(tool_context, tools):
    import json

    result = tools.invoke("edit_file", tool_context,
                          {"__raw__": '{"path": "a.py", '})

    example = result.content.split("Send an object like: ")[1].split("\n")[0]
    example = example.split(" Optional:")[0].strip()
    decoded = json.loads(example)

    assert set(decoded) == {"path", "old_string", "new_string"}, \
        f"the example does not match the tool's own required fields: {decoded}"


def test_what_arrived_is_quoted_back(tool_context, tools):
    """Without it the model cannot tell which of its calls was rejected."""
    result = tools.invoke("read_file", tool_context, {"__raw__": "path=notes.md"})

    assert "path=notes.md" in result.content


def test_an_enormous_blob_does_not_come_back_whole(tool_context, tools):
    result = tools.invoke("read_file", tool_context, {"__raw__": "x" * 50_000})

    assert len(result.content) < 2_000


# --------------------------------------------------------------------------- #
# what a file read costs
#
# A read is the largest thing most turns add, and the prefix behind it comes
# back 99% cached — so what a read costs is close to what a turn costs. Six
# characters of padding on every line was 6-7% of a real read: 542 tokens on
# `agent/loop.py`, 893 on `config.py`, spent on leading spaces.
# --------------------------------------------------------------------------- #


def test_line_numbers_are_not_padded(tool_context):
    from comodor.tools.fs import ReadFile

    (tool_context.cwd / "small.py").write_text(
        "\n".join(f"x = {n}" for n in range(1, 4)), encoding="utf-8")

    result = ReadFile().run(tool_context, path="small.py")

    assert result.content.startswith("1\tx = 1"), result.content[:40]
    assert "     1" not in result.content


def test_the_number_and_the_line_are_still_separated_by_a_tab(tool_context):
    """The tab is what makes the number readable as a number. Only the
    alignment went."""
    from comodor.tools.fs import ReadFile

    (tool_context.cwd / "small.py").write_text("first\nsecond\n", encoding="utf-8")

    lines = ReadFile().run(tool_context, path="small.py").content.splitlines()

    assert lines[0] == "1\tfirst"
    assert lines[1] == "2\tsecond"


def test_an_offset_read_still_numbers_from_the_real_line(tool_context):
    from comodor.tools.fs import ReadFile

    (tool_context.cwd / "big.py").write_text(
        "\n".join(f"x = {n}" for n in range(1, 30)), encoding="utf-8")

    result = ReadFile().run(tool_context, path="big.py", offset=10, limit=2)

    assert result.content.startswith("10\tx = 10")


def test_the_padding_was_worth_removing(tool_context):
    """Measured rather than asserted: the same file, both ways."""
    from comodor.agent.tokens import estimate_text
    from comodor.tools.fs import ReadFile

    body = "\n".join(f"    value_{n} = compute(n={n})" for n in range(1, 400))
    (tool_context.cwd / "real.py").write_text(body, encoding="utf-8")

    tight = ReadFile().run(tool_context, path="real.py").content
    padded = "\n".join(f"{n + 1:6d}\t{line}"
                       for n, line in enumerate(body.splitlines()))

    saved = estimate_text(padded) - estimate_text(tight)
    assert saved > 0, "the change saves nothing"
    assert saved / estimate_text(padded) > 0.03, \
        f"only {saved / estimate_text(padded):.1%} — not worth the churn"
