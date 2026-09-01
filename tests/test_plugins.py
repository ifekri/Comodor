"""The plugin system: discovery, trust, isolation, and the gate.

The acceptance from the spec: a sample plugin registers a tool in ten lines
and it passes the same permission gate as a built-in; a project plugin is
inert until trusted, with the scan findings shown first; a broken plugin
costs itself nothing but a line in the report — the session, and every
other plugin, survive it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from comodor.config import Config
from comodor.paths import Paths
from comodor.plugins import PluginManager, load_for

GOOD = """
def register(ctx):
    def shout(text):
        return text.upper()
    ctx.tool("shout", "Shout the text back", {"type": "object",
                                              "properties": {}}, shout,
             risk="safe")
    ctx.note("demo plugin")
"""

BROKEN = """
raise RuntimeError("this plugin never worked")
"""

BAD_REGISTER = """
def register(ctx):
    ctx.tool("Bad Name", "", {}, print)
"""

DANGEROUS = """
def register(ctx):
    def wipe():
        return "nothing was actually deleted, this is a test"
    ctx.tool("wipe", "delete everything", {"type": "object", "properties": {}},
             wipe, risk="dangerous")
"""


def write_plugin(root: Path, name: str, source: str) -> Path:
    folder = root / "plugins" / name
    folder.mkdir(parents=True)
    (folder / "plugin.py").write_text(source, encoding="utf-8")
    return folder


@pytest.fixture
def config(tmp_path, workspace):
    cfg = Config(paths=Paths(user=tmp_path / "home", project=workspace))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return cfg


def make(config, **kwargs) -> PluginManager:
    manager = PluginManager(config.paths, **kwargs)
    manager.discover()
    return manager


# --------------------------------------------------------------------------- #
# discovery and trust
# --------------------------------------------------------------------------- #

def test_a_user_plugin_is_trusted_by_being_theirs(config):
    write_plugin(config.paths.user, "hello", GOOD)
    manager = make(config)
    (state,) = manager.states.values()
    assert state.source == "user" and state.trusted


def test_a_project_plugin_is_inert_until_trusted(config):
    write_plugin(config.paths.project_dir, "shipped", GOOD)
    manager = make(config)
    (state,) = manager.states.values()
    assert state.source == "project" and not state.trusted

    state = manager.load_all()[0]
    assert not state.loaded and not state.error, "untrusted means skipped, \
never an error"


def test_trust_records_the_project_root_and_loads(config):
    write_plugin(config.paths.project_dir, "shipped", GOOD)
    manager = make(config)
    manager.trust("shipped")
    assert manager.trusted_folders, "the project root is remembered"
    state = manager.load_all()[0]
    assert state.loaded


def test_trust_is_per_folder_not_per_plugin_name(config, tmp_path):
    write_plugin(config.paths.project_dir, "one", GOOD)
    manager = make(config)
    manager.trust("one")
    # A different project with the same plugin name is not covered by it.
    other = tmp_path / "other"
    (other / ".comodor" / "plugins" / "one").mkdir(parents=True)
    (other / ".comodor" / "plugins" / "one" / "plugin.py").write_text(
        GOOD, encoding="utf-8")
    config.paths = Paths(user=config.paths.user, project=other)
    fresh = make(config)
    assert not fresh.states["one"].trusted


def test_untrust_takes_it_back(config):
    write_plugin(config.paths.project_dir, "shipped", GOOD)
    manager = make(config)
    manager.trust("shipped")
    assert manager.untrust("shipped")
    assert not manager.states["shipped"].trusted


# --------------------------------------------------------------------------- #
# the scan: a second look, not a sandbox
# --------------------------------------------------------------------------- #

def test_the_scan_flags_exec_and_hard_coded_keys(config):
    write_plugin(config.paths.project_dir, "shady",
                 'KEY = "sk-abcdefghijklmnopqrstuv"\n'
                 "def register(ctx):\n"
                 "    exec('pass')\n")
    manager = make(config)
    findings = manager.scan("shady")
    assert any("exec" in finding for finding in findings)
    assert any("hard-coded" in finding for finding in findings)


def test_a_clean_plugin_scans_clean(config):
    write_plugin(config.paths.user, "clean", GOOD)
    manager = make(config)
    assert manager.scan("clean") == []


# --------------------------------------------------------------------------- #
# loading: isolation and the context API
# --------------------------------------------------------------------------- #

def test_a_good_plugin_registers_its_tool(config):
    write_plugin(config.paths.user, "hello", GOOD)
    manager = make(config)
    (state,) = manager.load_all()
    assert state.ok
    ((owner, spec),) = manager.registered_tools()
    assert owner == "hello" and spec["name"] == "shout"
    assert spec["handler"]("hi") == "HI"


def test_a_broken_plugin_does_not_take_the_rest_down(config):
    write_plugin(config.paths.user, "broken", BROKEN)
    write_plugin(config.paths.user, "hello", GOOD)
    manager = make(config)
    states = manager.load_all()
    by_name = {state.name: state for state in states}
    assert "never worked" in by_name["broken"].error
    assert by_name["hello"].ok
    assert [owner for owner, _ in manager.registered_tools()] == ["hello"]


def test_a_bad_tool_name_is_refused_at_load(config):
    write_plugin(config.paths.user, "badname", BAD_REGISTER)
    manager = make(config)
    (state,) = manager.load_all()
    assert not state.ok and "not usable" in state.error


def test_unknown_hooks_are_refused_not_silently_dropped(config):
    write_plugin(config.paths.user, "wronghook",
                 "def register(ctx):\n"
                 "    ctx.on('agent:exploded', print)\n")
    manager = make(config)
    (state,) = manager.load_all()
    assert not state.ok and "unknown hook" in state.error


def test_hook_aliases_map_to_bus_kinds(config):
    write_plugin(config.paths.user, "hooked",
                 "def register(ctx):\n"
                 "    ctx.on('turn:end', print)\n")
    manager = make(config)
    manager.load_all()
    assert manager.hook_callbacks("turn_end")


def test_plugin_factory_uses_the_config(config):
    write_plugin(config.paths.user, "hello", GOOD)
    manager = load_for(config)
    assert "hello" in manager.states


# --------------------------------------------------------------------------- #
# through the registry and the gate
# --------------------------------------------------------------------------- #

def test_a_plugin_tool_enters_the_registry_and_passes_the_gate(config):
    from comodor.events import Cancellation, EventBus
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor, Risk
    from comodor.tools.base import ToolContext
    from comodor.tools.registry import ToolRegistry

    write_plugin(config.paths.user, "hello", GOOD)
    manager = make(config)
    manager.load_all()

    registry = ToolRegistry(config=config, plugins=manager)
    assert "shout" in registry
    assert registry.get("shout").risk is Risk.SAFE

    bus = EventBus()
    ctx = ToolContext(
        config=config, permissions=PermissionEngine(config, bus),
        checkpoints=CheckpointStore(config.paths.checkpoints), bus=bus,
        redact=Redactor([]), cancel=Cancellation(),
        cwd=config.paths.project)
    config.safety.auto_approve_safe = True
    result = registry.invoke("shout", ctx, {"text": "quiet please"})
    assert result.ok and result.content == "QUIET PLEASE"


def test_a_dangerous_plugin_tool_is_gated_like_a_shell_command(config):
    from comodor.events import Cancellation, EventBus
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor
    from comodor.tools.base import ToolContext
    from comodor.tools.registry import ToolRegistry

    write_plugin(config.paths.user, "scary", DANGEROUS)
    manager = make(config)
    manager.load_all()

    registry = ToolRegistry(config=config, plugins=manager)
    bus = EventBus()
    permissions = PermissionEngine(config, bus)
    permissions.prompt_timeout = 1.0        # nobody is coming; do not wait long
    ctx = ToolContext(
        config=config, permissions=permissions,
        checkpoints=CheckpointStore(config.paths.checkpoints), bus=bus,
        redact=Redactor([]), cancel=Cancellation(),
        cwd=config.paths.project)
    # Nobody is there to approve, so the request times out to "no": the
    # plugin tool is denied the same way an unapproved shell command is.
    result = registry.invoke("wipe", ctx, {})
    assert not result.ok
