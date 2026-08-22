"""Talking to MCP servers.

Every test here runs a real subprocess speaking real JSON-RPC over real pipes.
Mocking the transport would test the mock, and the interesting failures — a
server that writes a banner to stdout, one that dies mid-call, one that returns
a schema it got wrong — all live in the transport.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from comodor.config import Config, MCPServerConfig, load
from comodor.mcp import MCPError, MCPManager, StdioConnection, catalogue, probe_server
from comodor.paths import Paths
from comodor.safety import Risk

SERVER = str(Path(__file__).parent / "support" / "fake_mcp_server.py")


def server(*flags: str, name: str = "fake", enabled: bool = True) -> MCPServerConfig:
    return MCPServerConfig(name=name, command=sys.executable,
                           args=[SERVER, *flags], enabled=enabled)


@pytest.fixture
def connection():
    link = StdioConnection(sys.executable, [SERVER])
    link.start()
    yield link
    link.close()


@pytest.fixture
def manager():
    made = MCPManager({"fake": server()})
    yield made
    made.close()


# --------------------------------------------------------------------------- #
# the protocol
# --------------------------------------------------------------------------- #


def test_the_handshake_reports_who_answered(connection):
    assert connection.server_info.get("name") == "fake-server"
    assert connection.alive


def test_tools_are_listed(connection):
    tools = connection.request("tools/list", {})
    assert [tool["name"] for tool in tools["tools"]] == [
        "echo", "write_note", "broken_schema"]


def test_a_tool_can_be_called(connection):
    result = connection.request(
        "tools/call", {"name": "echo", "arguments": {"text": "hello"}})
    assert result["content"][0]["text"] == "hello"


def test_a_banner_on_stdout_does_not_break_the_handshake():
    """Servers really do log to the wrong stream, and it must not be fatal."""
    link = StdioConnection(sys.executable, [SERVER, "--noise"])
    try:
        link.start()
        assert link.server_info.get("name") == "fake-server"
    finally:
        link.close()


def test_pagination_is_followed():
    link = StdioConnection(sys.executable, [SERVER, "--paginate"])
    try:
        link.start()
        from comodor.mcp.manager import _list_tools

        assert len(_list_tools(link)) == 3
    finally:
        link.close()


def test_a_command_that_does_not_exist_says_so():
    link = StdioConnection("a-command-that-is-not-installed-anywhere")
    with pytest.raises(MCPError, match="not installed"):
        link.start()


def test_a_server_error_becomes_an_exception(connection):
    with pytest.raises(MCPError, match="no tool"):
        connection.request("tools/call", {"name": "nonexistent", "arguments": {}})


def test_a_server_that_dies_mid_call_is_reported_with_its_own_words():
    link = StdioConnection(sys.executable, [SERVER, "--die-on-call"])
    try:
        link.start()
        with pytest.raises(MCPError) as error:
            link.request("tools/call", {"name": "echo", "arguments": {}})
        # The server's stderr is the only thing that explains this to a user
        # who did not write the server.
        assert "crashed on purpose" in str(error.value)
    finally:
        link.close()


def test_a_slow_handshake_times_out_rather_than_hanging():
    link = StdioConnection(sys.executable, [SERVER, "--slow", "5"])
    try:
        with pytest.raises(MCPError, match="timed out"):
            link.start(timeout=0.5)
    finally:
        link.close()


def test_closing_twice_is_harmless(connection):
    connection.close()
    connection.close()
    assert not connection.alive


# --------------------------------------------------------------------------- #
# the manager
# --------------------------------------------------------------------------- #


def test_tools_arrive_namespaced_by_server(manager):
    names = [tool.name for tool in manager.tools()]
    assert "fake__echo" in names
    assert all(name.startswith("fake__") for name in names)


def test_a_tool_call_returns_text(manager):
    assert manager.call("fake", "echo", {"text": "round trip"}) == "round trip"


def test_a_tool_reporting_its_own_error_raises(manager):
    with pytest.raises(MCPError, match="went wrong"):
        manager.call("fake", "explodes", {})


def test_a_disabled_server_is_never_started():
    made = MCPManager({"fake": server(enabled=False)})
    try:
        assert made.tools() == []
        assert made.states == {}, "nothing should have been spawned"
    finally:
        made.close()


def test_a_server_that_will_not_start_does_not_take_the_others_down():
    made = MCPManager({
        "broken": MCPServerConfig(name="broken", command="not-a-real-command",
                                  enabled=True),
        "fake": server(),
    })
    try:
        names = [tool.name for tool in made.tools()]
        assert any(name.startswith("fake__") for name in names)
        assert not any(name.startswith("broken__") for name in names)

        rows = {row[0]: row[1] for row in made.report()}
        assert rows["broken"] == "failed"
        assert rows["fake"] == "ready"
    finally:
        made.close()


def test_a_failed_server_is_not_retried_on_every_turn():
    """Respawning a broken server for each tool listing would be a slow leak."""
    made = MCPManager({"broken": MCPServerConfig(
        name="broken", command="not-a-real-command", enabled=True)})
    try:
        made.tools()
        first = made.states["broken"].error
        made.tools()
        assert made.states["broken"].error is first
    finally:
        made.close()


def test_servers_start_only_when_something_asks(manager):
    assert manager.states == {}, "constructing the manager must not spawn anything"
    manager.tools()
    assert "fake" in manager.states


def test_a_huge_result_is_truncated_with_a_note(manager):
    from comodor.mcp import manager as manager_module

    text = manager.call("fake", "echo", {"text": "x" * (manager_module.MAX_RESULT + 500)})
    assert len(text) < manager_module.MAX_RESULT + 200
    assert "truncated" in text


# --------------------------------------------------------------------------- #
# how they appear to the agent
# --------------------------------------------------------------------------- #


def tool_named(manager, name):
    for tool in manager.tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"no tool {name!r}")


def test_a_read_only_tool_is_safe(manager):
    assert tool_named(manager, "fake__echo").risk is Risk.SAFE


def test_a_tool_that_says_it_modifies_things_needs_approval(manager):
    """The description is all there is to go on, so it is read generously."""
    assert tool_named(manager, "fake__write_note").risk is Risk.WRITE


def test_a_malformed_schema_does_not_poison_the_tool_list(manager):
    """One server's mistake must not make its other tools unusable."""
    tool = tool_named(manager, "fake__broken_schema")
    assert tool.parameters["type"] == "object"
    assert isinstance(tool.parameters["properties"], dict)
    assert "required" not in tool.parameters


def test_the_description_says_where_the_tool_came_from(manager):
    """With several servers the model chooses between them on this text alone."""
    assert "fake MCP server" in tool_named(manager, "fake__echo").description


def test_calling_through_the_tool_wrapper(manager, tmp_path):
    from comodor.events import Cancellation, EventBus
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor
    from comodor.tools.base import ToolContext

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    bus = EventBus()
    context = ToolContext(
        config=config, permissions=PermissionEngine(config, bus),
        checkpoints=CheckpointStore(tmp_path / "cp"), bus=bus,
        redact=Redactor([]), cancel=Cancellation(), cwd=tmp_path)

    result = tool_named(manager, "fake__echo").run(context, text="through the tool")
    assert result.ok
    assert result.content == "through the tool"


def test_a_failing_call_is_a_tool_failure_not_a_crash(manager, tmp_path):
    """The agent should get to try something else, as with any other tool."""
    from comodor.events import Cancellation, EventBus
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor
    from comodor.tools.base import ToolContext

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    bus = EventBus()
    context = ToolContext(
        config=config, permissions=PermissionEngine(config, bus),
        checkpoints=CheckpointStore(tmp_path / "cp"), bus=bus,
        redact=Redactor([]), cancel=Cancellation(), cwd=tmp_path)

    tool = tool_named(manager, "fake__echo")
    tool.remote_name = "nonexistent"
    result = tool.run(context, text="x")

    assert not result.ok
    assert "no tool" in result.content


# --------------------------------------------------------------------------- #
# the catalogue
# --------------------------------------------------------------------------- #


def test_the_catalogue_offers_servers_people_use():
    ids = {spec.id for spec in catalogue.offered()}
    for expected in ("filesystem", "git", "github", "fetch", "memory", "sqlite"):
        assert expected in ids


def test_every_catalogue_entry_can_actually_be_started():
    for spec in catalogue.CATALOGUE:
        assert spec.command in ("npx", "uvx"), spec.id
        assert spec.args, spec.id
        assert spec.blurb and spec.label, spec.id
        # What it can reach has to be stated before somebody enables it.
        assert spec.reach, f"{spec.id} does not say what it can reach"
        assert spec.url.startswith("http"), spec.id


def test_entries_needing_a_secret_say_what_and_why():
    for spec in catalogue.CATALOGUE:
        for name, why in spec.needs_env:
            assert name.isupper(), f"{spec.id}: {name}"
            assert len(why) > 10, f"{spec.id}: {name} has no explanation"


def test_probe_reports_a_working_server():
    ok, detail = probe_server(server())
    assert ok
    assert "3 tool" in detail


def test_probe_reports_a_broken_one():
    ok, detail = probe_server(MCPServerConfig(
        name="x", command="not-a-real-command", enabled=True))
    assert not ok
    assert detail


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #


def test_servers_survive_a_save_and_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    (tmp_path / "project").mkdir()

    config = load(cwd=tmp_path / "project", use_environment=False)
    config.mcp.servers["github"] = MCPServerConfig(
        name="github", command="npx", args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp-x"}, enabled=True, spec="github")
    config.save()

    reloaded = load(cwd=tmp_path / "project", use_environment=False)
    entry = reloaded.mcp.servers["github"]

    assert entry.command == "npx"
    assert entry.args == ["-y", "@modelcontextprotocol/server-github"]
    assert entry.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp-x"
    assert entry.enabled and entry.spec == "github"


def test_a_project_can_add_a_server_without_removing_yours(tmp_path, monkeypatch):
    import json

    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".comodor").mkdir(parents=True)
    home.mkdir(parents=True)
    monkeypatch.setenv("COMODOR_HOME", str(home))

    (home / "config.json").write_text(json.dumps({
        "mcp": {"servers": {"mine": {"command": "npx", "enabled": True}}},
    }), encoding="utf-8")
    (project / ".comodor" / "config.json").write_text(json.dumps({
        "mcp": {"servers": {"theirs": {"command": "uvx", "enabled": True}}},
    }), encoding="utf-8")

    config = load(cwd=project, use_environment=False)
    assert set(config.mcp.servers) == {"mine", "theirs"}


def test_an_entry_without_a_command_is_ignored(tmp_path, monkeypatch):
    import json

    home = tmp_path / "home"
    home.mkdir(parents=True)
    (tmp_path / "project").mkdir()
    monkeypatch.setenv("COMODOR_HOME", str(home))
    (home / "config.json").write_text(json.dumps({
        "mcp": {"servers": {"broken": {"enabled": True}}},
    }), encoding="utf-8")

    config = load(cwd=tmp_path / "project", use_environment=False)
    assert "broken" not in config.mcp.servers


# --------------------------------------------------------------------------- #
# starting the process
# --------------------------------------------------------------------------- #


def test_a_windows_batch_launcher_goes_through_the_shell(monkeypatch):
    """`npx` is `npx.cmd` on Windows, and CreateProcess cannot run a batch file.

    Without this, `Popen(["npx", ...])` reports "not installed" on every
    Windows machine that has Node — which is to say, on the machines where
    almost every MCP server is launched.
    """
    from comodor.mcp import protocol

    monkeypatch.setattr(protocol.os, "name", "nt")
    monkeypatch.setattr(protocol.shutil, "which",
                        lambda name: r"C:\Program Files\nodejs\npx.cmd")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\system32\cmd.exe")

    argv = protocol._spawn_argv("npx", ["-y", "@modelcontextprotocol/server-git"])

    assert argv[0].endswith("cmd.exe")
    assert argv[1] == "/c"
    assert argv[2].endswith("npx.cmd")
    # Arguments stay separate items so subprocess quotes them, rather than
    # being pasted into a command line where a space would split them.
    assert argv[3:] == ["-y", "@modelcontextprotocol/server-git"]


def test_a_real_executable_is_started_directly(monkeypatch):
    from comodor.mcp import protocol

    monkeypatch.setattr(protocol.os, "name", "nt")
    monkeypatch.setattr(protocol.shutil, "which",
                        lambda name: r"C:\Users\x\.local\bin\uvx.exe")

    argv = protocol._spawn_argv("uvx", ["mcp-server-git"])
    assert argv == [r"C:\Users\x\.local\bin\uvx.exe", "mcp-server-git"]


def test_posix_never_involves_a_shell(monkeypatch):
    from comodor.mcp import protocol

    monkeypatch.setattr(protocol.os, "name", "posix")
    monkeypatch.setattr(protocol.shutil, "which", lambda name: "/usr/bin/npx")

    assert protocol._spawn_argv("npx", ["-y", "x"]) == ["/usr/bin/npx", "-y", "x"]


def test_an_unresolvable_command_is_passed_through_unchanged(monkeypatch):
    """So the error comes from the spawn, with its real message."""
    from comodor.mcp import protocol

    monkeypatch.setattr(protocol.shutil, "which", lambda name: None)
    assert protocol._spawn_argv("nonexistent", ["a"]) == ["nonexistent", "a"]
