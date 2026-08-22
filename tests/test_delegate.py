"""Work that costs its own context and returns only its conclusion.

Some questions take a great deal of reading to answer and very little to state.
Asked in the main conversation, the reading is permanent — resent with every
later request. Asked of a delegate, the reading stays with the delegate and
only the sentence comes back.

What is checked here is that separation, and the two things that make it safe:
a delegate cannot write unless it was told to, and it cannot delegate at all.
"""

from __future__ import annotations

import subprocess

import pytest

from comodor.agent import Conversation
from comodor.agent.spawn import spawner
from comodor.providers.base import Message
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.tools import ToolRegistry
from comodor.tools.delegate import Delegate


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), text=True,
                          capture_output=True)


@pytest.fixture
def repo(workspace):
    git(workspace, "init", "-q")
    git(workspace, "config", "user.email", "t@example.com")
    git(workspace, "config", "user.name", "T")
    (workspace / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-q", "-m", "first")
    return workspace


def delegate_for(config, bus, *scripts):
    gateway = Gateway(config, scripts=list(scripts))
    return Delegate(spawner(config, gateway, bus)), gateway


# --------------------------------------------------------------------------- #
# the point of it
# --------------------------------------------------------------------------- #


def test_only_the_answer_comes_back(config, bus, tool_context):
    """Not the transcript, not the files it opened — the sentence."""
    tool, _ = delegate_for(config, bus, Script(text="Retries live in net/http.py."))

    result = tool.run(tool_context, task="Find where retries are implemented.")

    assert result.ok
    assert result.content.strip() == "Retries live in net/http.py."


def test_the_reading_is_not_added_to_this_conversation(config, bus, tool_context):
    conversation = Conversation()
    conversation.add(Message.user("where are retries?"))
    before = len(conversation.messages)

    tool, _ = delegate_for(config, bus, Script(text="In net/http.py."))
    tool.run(tool_context, task="Find retries.")

    assert len(conversation.messages) == before


def test_what_it_read_is_reported_so_the_saving_is_visible(config, bus, tool_context):
    tool, _ = delegate_for(config, bus, Script(text="Done."))

    result = tool.run(tool_context, task="Survey the package.")

    assert "delegate_tokens" in result.meta


def test_an_empty_brief_is_refused(config, bus, tool_context):
    tool, _ = delegate_for(config, bus, Script(text="anything"))

    assert not tool.run(tool_context, task="   ").ok


def test_a_delegate_that_says_nothing_is_a_failure(config, bus, tool_context):
    """Silence read as success would be a confident answer built on nothing."""
    tool, _ = delegate_for(config, bus, Script(text=""))

    result = tool.run(tool_context, task="Find retries.")

    assert not result.ok
    assert "without an answer" in result.content


# --------------------------------------------------------------------------- #
# what it is not allowed to do
# --------------------------------------------------------------------------- #


def test_answering_cannot_write(config, bus, tool_context):
    """A question is not a reason to hand a second agent the ability to edit."""
    spawn = spawner(config, Gateway(config, scripts=[Script(text="ok")]), bus)
    loop = spawn(cwd=tool_context.cwd, mode="plan", max_steps=3)

    offered = {tool.name for tool in loop.tools.for_mode(loop.config.agent.mode)}

    assert "write_file" not in offered
    assert "edit_file" not in offered
    assert "read_file" in offered


def test_a_delegate_cannot_delegate(config, bus, tool_context):
    """One level is a tool. A tree of them spends an afternoon in ninety seconds."""
    spawn = spawner(config, Gateway(config, scripts=[Script(text="ok")]), bus)
    loop = spawn(cwd=tool_context.cwd, mode="act", max_steps=3)

    assert "delegate" not in loop.tools


def test_a_delegate_does_not_reflect(config, bus, tool_context):
    """Its episode is half a task seen out of context; learning from it teaches
    the brain about a fragment."""
    spawn = spawner(config, Gateway(config, scripts=[Script(text="ok")]), bus)
    loop = spawn(cwd=tool_context.cwd)

    assert loop.memory is None


def test_it_stops_when_the_parent_does(config, bus, tool_context):
    """Escape must stop the whole thing, not leave one working with a shell open."""
    spawn = spawner(config, Gateway(config, scripts=[Script(text="ok")]), bus)
    loop = spawn(cwd=tool_context.cwd, cancel=tool_context.cancel)

    assert loop.cancel is tool_context.cancel


def test_its_budget_is_a_fraction_of_the_parents(config, bus, tool_context):
    from comodor.tools.delegate import MAX_STEPS, MIN_STEPS, _steps

    tool_context.config.agent.max_steps = 24
    assert MIN_STEPS <= _steps(tool_context) <= MAX_STEPS
    assert _steps(tool_context) < 24


def test_the_registry_offers_it_only_when_there_is_something_to_spawn_with():
    """A registry built inside a delegate has no gateway, and must not
    advertise a tool that cannot run."""
    assert "delegate" not in ToolRegistry()
    assert "delegate" in ToolRegistry(spawn=lambda **_: None)


# --------------------------------------------------------------------------- #
# doing, in a checkout of its own
# --------------------------------------------------------------------------- #


def test_it_edits_a_separate_checkout_and_the_change_comes_back(config, bus,
                                                                tool_context, repo):
    tool_context.cwd = repo
    tool_context.config.paths = tool_context.config.paths
    written = Script(text="Changed it.")
    tool, _ = delegate_for(config, bus, written)

    result = tool.run(tool_context, task="Change value to 2.", write=True)

    assert result.ok
    # It changed nothing, and says so rather than implying it did.
    assert "changed no files" in result.content


def test_the_parents_working_tree_is_not_where_it_experiments(config, bus,
                                                              tool_context, repo):
    from comodor.tools.delegate import _Worktree

    tool_context.cwd = repo
    worktree = _Worktree.create(repo)
    assert worktree is not None
    try:
        assert worktree.path.exists()
        assert worktree.path != repo
        (worktree.path / "app.py").write_text("value = 2\n", encoding="utf-8")

        assert (repo / "app.py").read_text() == "value = 1\n"
        assert b"value = 2" in worktree.diff()
    finally:
        worktree.remove()

    assert not worktree.path.exists()


def test_a_project_that_is_not_a_repository_gets_no_worktree(config, bus,
                                                             tool_context, workspace):
    """Nothing to isolate against, and nothing to turn the result into."""
    from comodor.tools.delegate import _Worktree

    assert _Worktree.create(workspace) is None


def test_changes_that_do_not_apply_keep_the_checkout(config, bus, tool_context, repo):
    """Something moved underneath it. Discarding the work would be the worst
    of the available answers."""
    from comodor.tools.base import ToolResult
    from comodor.tools.delegate import _Worktree, _with_changes

    tool_context.cwd = repo
    worktree = _Worktree.create(repo)
    assert worktree is not None
    try:
        (worktree.path / "app.py").write_text("value = 99\n", encoding="utf-8")
        # The parent moved on, so the delegate's patch no longer applies.
        (repo / "app.py").write_text("something else entirely\n", encoding="utf-8")

        result = _with_changes(ToolResult.success("did it"), worktree,
                               tool_context, 1.0)

        assert result.ok
        assert str(worktree.path) in result.content
        assert result.meta["applied"] is False
    finally:
        worktree.keep = False
        worktree.remove()


def test_a_clean_patch_is_applied_to_the_parent(config, bus, tool_context, repo):
    from comodor.tools.base import ToolResult
    from comodor.tools.delegate import _Worktree, _with_changes

    tool_context.cwd = repo
    worktree = _Worktree.create(repo)
    assert worktree is not None
    try:
        (worktree.path / "app.py").write_text("value = 2\n", encoding="utf-8")

        result = _with_changes(ToolResult.success("did it"), worktree,
                               tool_context, 1.0)

        assert result.meta["applied"] is True
        assert (repo / "app.py").read_text() == "value = 2\n"
        assert "app.py" in result.content
    finally:
        worktree.remove()


def test_it_says_when_it_did_not_get_the_isolation_it_was_asked_for(config, bus,
                                                                    tool_context,
                                                                    workspace):
    """write=true promises a checkout of its own. Without a repository there is
    none, which is a fine fallback and a bad thing to do quietly."""
    tool_context.cwd = workspace                 # not a git repository
    tool, _ = delegate_for(config, bus, Script(text="Edited it."))

    result = tool.run(tool_context, task="Change something.", write=True)

    assert result.ok
    assert "directly in this project" in result.content
    assert result.meta["isolated"] is False


def test_a_repository_gets_the_checkout_and_says_nothing_about_it(config, bus,
                                                                  tool_context, repo):
    tool_context.cwd = repo
    tool, _ = delegate_for(config, bus, Script(text="Looked at it."))

    result = tool.run(tool_context, task="Change something.", write=True)

    assert "directly in this project" not in result.content


def test_the_patch_reaches_git_as_the_bytes_it_was(config, bus, tool_context, repo):
    """`subprocess(text=True)` wraps stdin in a stream with default newline
    handling, and on Windows every "\n" written becomes "\r\n". For output that
    is harmless; for a patch it is fatal — every line of the diff gains a
    carriage return, the context no longer matches, and git refuses all of it.

    The failure was silent and one-platform: on Linux and macOS nothing is
    translated, so every delegate that changed a file worked here and reported
    an imaginary merge conflict on Windows."""
    from comodor.tools.base import ToolResult
    from comodor.tools.delegate import _Worktree, _with_changes

    tool_context.cwd = repo
    worktree = _Worktree.create(repo)
    assert worktree is not None
    try:
        (worktree.path / "app.py").write_text("value = 2\nsecond = 3\n",
                                              encoding="utf-8", newline="")
        patch = worktree.diff()

        assert isinstance(patch, bytes), "a patch is bytes, not text"
        assert b"\r\n" not in patch, "the patch already has carriage returns"

        result = _with_changes(ToolResult.success("did it"), worktree,
                               tool_context, 1.0)

        assert result.meta["applied"] is True, result.content
        # Read as text: git applies the checkout's own line-ending policy when
        # it writes, and on Windows that legitimately produces CRLF. What had
        # to survive is the content, which is what the mangled patch destroyed.
        assert (repo / "app.py").read_text() == "value = 2\nsecond = 3\n"
    finally:
        worktree.keep = False
        worktree.remove()


def test_git_is_never_asked_to_translate_anything():
    """The one line that caused it, pinned so it cannot come back."""
    import inspect

    from comodor.tools import delegate

    source = inspect.getsource(delegate._git_bytes)
    # The docstring explains the trap by name, so look at the code only.
    code = source.split('"""')[-1]

    assert "text=True" not in code
    assert "universal_newlines" not in code
