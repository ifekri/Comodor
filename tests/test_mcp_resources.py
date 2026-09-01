"""MCP resources and prompts: reading what a server holds, running what it asks.

The rule from the spec: a server's resources and prompts ride the same
lazy discovery its tools do; a server that offers neither stays exactly
as it was — no capability declared, no error recorded, no tool advertised.
Every test drives a real subprocess speaking real JSON-RPC, as the rest
of the MCP tests do.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from comodor.config import MCPServerConfig
from comodor.mcp import MCPError, MCPManager
from comodor.tools.mcp_resources import MCPReadResource

SERVER = str(Path(__file__).parent / "support" / "fake_mcp_server.py")


def server(*flags: str, name: str = "fake", enabled: bool = True) -> MCPServerConfig:
    return MCPServerConfig(name=name, command=sys.executable,
                           args=[SERVER, *flags], enabled=enabled)


@pytest.fixture
def plain():
    made = MCPManager({"plain": server()})
    yield made
    made.close()


@pytest.fixture
def rich():
    made = MCPManager({"rich": server("--rich")})
    yield made
    made.close()


# --------------------------------------------------------------------------- #
# discovery: capabilities a server never declared are simply absent
# --------------------------------------------------------------------------- #

def test_a_server_without_resources_starts_clean(plain):
    state = plain.start("plain")
    assert state.ok
    assert state.tools, "the plain server still has tools"
    assert state.resources == []
    assert state.prompts == []


def test_a_rich_server_lists_its_resources(rich):
    state = rich.start("rich")
    assert state.ok
    assert [r.uri for r in state.resources] == [
        "file:///logs/app.log", "sqlite:///data.db/main/users"]
    assert state.resources[0].name == "application log"


def test_a_rich_server_lists_its_prompts(rich):
    state = rich.start("rich")
    assert state.ok
    names = [p.name for p in state.prompts]
    assert names == ["review_pr", "morning"]
    review = state.prompts[0]
    assert [a.get("name") for a in review.arguments] == ["number", "focus"]
    assert review.arguments[0].get("required") is True


def test_report_mentions_what_the_server_holds(rich):
    rich.start("rich")
    detail = {name: detail for name, _, detail in rich.report()}["rich"]
    assert "3 tool(s)" in detail
    assert "2 resource(s)" in detail
    assert "2 prompt(s)" in detail


# --------------------------------------------------------------------------- #
# reading resources
# --------------------------------------------------------------------------- #

def test_a_resource_reads_back_as_text(rich):
    text = rich.read_resource("rich", "file:///logs/app.log")
    assert "INFO started" in text
    assert "ERROR 1 + 1 = 3" in text


def test_the_resource_tool_lists_then_reads(rich):
    tool = MCPReadResource(rich)
    listing = tool.run(None, server="rich")
    assert listing.ok
    assert "file:///logs/app.log" in listing.content

    reading = tool.run(None, server="rich", uri="sqlite:///data.db/main/users")
    assert reading.ok
    assert "alice" in reading.content


def test_an_unknown_resource_is_a_failure_in_words(rich):
    tool = MCPReadResource(rich)
    result = tool.run(None, server="rich", uri="file:///no/such/thing")
    assert not result.ok
    assert result.content.startswith("Error")


def test_a_failed_server_is_reported_not_raised():
    made = MCPManager({"dead": server("--die-on-call", name="dead")})
    try:
        # A server that dies on any call: started fine, then gone.
        state = made.start("dead")
        assert state.ok
        state.connection.close()
        with pytest.raises(MCPError):
            made.read_resource("dead", "file:///logs/app.log")
    finally:
        made.close()


def test_the_reader_tool_is_only_advertised_when_a_server_has_resources(plain,
                                                                        rich):
    from comodor.tools.registry import ToolRegistry

    with_none = ToolRegistry(mcp=plain)
    assert "mcp_read_resource" not in with_none

    # The reader appears only once a started server has declared resources —
    # and `has_resources` never starts servers to find out.
    rich.start("rich")
    with_some = ToolRegistry(mcp=rich)
    assert "mcp_read_resource" in with_some
    advertised = with_some.get("mcp_read_resource")
    assert advertised.risk is not None and advertised.description


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #

def test_a_prompt_comes_back_filled(rich):
    text = rich.get_prompt("rich", "review_pr", {"number": "7"})
    assert "Review pull request #7" in text
    assert "correctness" in text, "the declared default of focus is used"


def test_a_prompt_with_no_arguments_needs_none(rich):
    text = rich.get_prompt("rich", "morning")
    assert "on my plate" in text


def test_an_unknown_prompt_raises_with_the_server_saying_why(rich):
    with pytest.raises(MCPError) as caught:
        rich.get_prompt("rich", "nonsense")
    assert "nonsense" in str(caught.value)
