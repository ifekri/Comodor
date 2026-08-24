"""Comodor as an agent an editor drives.

Two halves, and they fail differently.

The **framing** is checked against a pipe, because the bugs there are the ones
that do not show up against a mock: a message with a newline in it, a batch of
notifications that must produce no reply at all, a response arriving for a
request that has already timed out. An editor parses every line it is handed,
so one malformed line ends the session with nothing on screen to explain it.

The **translation** is checked by putting Comodor's own events on the bus and
reading what comes out the other side. That is the part that has to keep step
with the agent: if a tool event changes shape and this does not, the editor
shows a tool call that never finishes.
"""

from __future__ import annotations

import io
import json
import threading
import time

import pytest

from comodor.acp import agent as acp_agent
from comodor.acp.jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR, Connection, RpcError


class Pipe:
    """A writer that keeps every line, readable as parsed messages."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            self.lines.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    @property
    def messages(self) -> list:
        out = []
        for chunk in "".join(self.lines).splitlines():
            if chunk.strip():
                out.append(json.loads(chunk))
        return out


def talking(*incoming: str) -> tuple[Connection, Pipe]:
    """A connection fed the given lines, with its output captured."""
    out = Pipe()
    rpc = Connection(reader=io.StringIO("\n".join(incoming) + "\n"),
                     writer=out, log=io.StringIO())
    return rpc, out


# --------------------------------------------------------------------------- #
# framing
# --------------------------------------------------------------------------- #


def test_a_request_gets_a_response_with_the_same_id():
    rpc, out = talking('{"jsonrpc":"2.0","id":7,"method":"ping"}')
    rpc.methods["ping"] = lambda params: {"pong": True}

    rpc.serve()

    assert out.messages == [{"jsonrpc": "2.0", "id": 7, "result": {"pong": True}}]


def test_a_handler_that_returns_nothing_answers_with_an_empty_object():
    """`session/prompt` does exactly this: accepted, and the rest comes as
    notifications."""
    rpc, out = talking('{"jsonrpc":"2.0","id":1,"method":"go"}')
    rpc.methods["go"] = lambda params: None

    rpc.serve()

    assert out.messages[0]["result"] == {}


def test_a_notification_gets_no_reply():
    seen = []
    rpc, out = talking('{"jsonrpc":"2.0","method":"tick","params":{"n":1}}')
    rpc.notifications["tick"] = seen.append

    rpc.serve()

    assert seen == [{"n": 1}]
    assert out.messages == []


def test_a_notification_nobody_handles_is_ignored():
    """Not an error: the specification has no way to report one, and a client
    is allowed to send notifications an agent does not know."""
    rpc, out = talking('{"jsonrpc":"2.0","method":"unknown/thing"}')

    rpc.serve()

    assert out.messages == []


def test_a_method_nobody_handles_is_an_error_with_a_name():
    rpc, out = talking('{"jsonrpc":"2.0","id":2,"method":"nope"}')

    rpc.serve()

    assert out.messages[0]["error"]["code"] == METHOD_NOT_FOUND
    assert "nope" in out.messages[0]["error"]["message"]


def test_broken_json_is_a_parse_error_with_a_null_id():
    rpc, out = talking("{not json at all")

    rpc.serve()

    assert out.messages[0]["id"] is None
    assert out.messages[0]["error"]["code"] == PARSE_ERROR


def test_an_empty_batch_is_refused():
    rpc, out = talking("[]")

    rpc.serve()

    assert out.messages[0]["error"]["code"] != PARSE_ERROR
    assert out.messages[0]["id"] is None


def test_a_batch_is_answered_as_a_batch():
    rpc, out = talking('[{"jsonrpc":"2.0","id":1,"method":"a"},'
                       '{"jsonrpc":"2.0","id":2,"method":"a"}]')
    rpc.methods["a"] = lambda params: {"ok": True}

    rpc.serve()

    assert len(out.messages) == 1
    assert isinstance(out.messages[0], list)
    assert [item["id"] for item in out.messages[0]] == [1, 2]


def test_a_batch_of_notifications_produces_nothing():
    """Not an empty array. JSON-RPC is explicit about this and a client that
    waits for a reply would wait forever."""
    seen = []
    rpc, out = talking('[{"jsonrpc":"2.0","method":"t"},{"jsonrpc":"2.0","method":"t"}]')
    rpc.notifications["t"] = seen.append

    rpc.serve()

    assert len(seen) == 2
    assert out.messages == []


def test_a_batch_answers_the_parts_that_were_valid():
    rpc, out = talking('[{"jsonrpc":"2.0","id":1,"method":"a"},"rubbish"]')
    rpc.methods["a"] = lambda params: {"ok": True}

    rpc.serve()

    replies = out.messages[0]
    assert len(replies) == 2
    assert replies[0]["result"] == {"ok": True}
    assert "error" in replies[1]


def test_a_handler_that_raises_becomes_an_error_rather_than_a_crash():
    """One bad tool call must not take the connection down with it."""
    rpc, out = talking('{"jsonrpc":"2.0","id":3,"method":"boom"}')

    def boom(params):
        raise ValueError("nope")

    rpc.methods["boom"] = boom
    rpc.serve()

    assert "ValueError" in out.messages[0]["error"]["message"]


def test_an_rpc_error_keeps_its_own_code():
    rpc, out = talking('{"jsonrpc":"2.0","id":4,"method":"x"}')

    def refuse(params):
        raise RpcError(INVALID_PARAMS, "which session?")

    rpc.methods["x"] = refuse
    rpc.serve()

    assert out.messages[0]["error"] == {"code": INVALID_PARAMS,
                                        "message": "which session?"}


def test_nothing_ever_written_contains_a_newline():
    """The framing is one message per line. A newline inside one is two
    messages as far as the editor is concerned, and the second is rubbish."""
    rpc, out = talking('{"jsonrpc":"2.0","id":1,"method":"multi"}')
    rpc.methods["multi"] = lambda params: {"text": "one\ntwo\r\nthree"}

    rpc.serve()

    assert len(out.lines) == 1
    assert out.lines[0].count("\n") == 1 and out.lines[0].endswith("\n")
    assert json.loads(out.lines[0])["result"]["text"] == "one\ntwo\r\nthree"


def test_a_message_is_never_interleaved_with_another():
    """Tool output arrives on a worker while the reader is on the main
    thread, so two writes can meet."""
    out = Pipe()
    rpc = Connection(reader=io.StringIO(""), writer=out, log=io.StringIO())

    def spam(n: int) -> None:
        for index in range(60):
            rpc.notify("session/update", {"n": n, "i": index, "pad": "x" * 200})

    threads = [threading.Thread(target=spam, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(out.messages) == 360, "a message was lost or split"


# --------------------------------------------------------------------------- #
# asking the client something
# --------------------------------------------------------------------------- #


def test_an_answer_from_the_client_reaches_the_waiting_caller():
    out = Pipe()
    rpc = Connection(reader=io.StringIO(""), writer=out, log=io.StringIO())
    answers: list = []

    def ask():
        answers.append(rpc.call("session/request_permission", {"x": 1}, timeout=5))

    thread = threading.Thread(target=ask)
    thread.start()
    deadline = time.monotonic() + 3
    while not out.messages and time.monotonic() < deadline:
        time.sleep(0.01)
    sent = out.messages[0]
    rpc._handle_line(json.dumps({"jsonrpc": "2.0", "id": sent["id"],
                                 "result": {"outcome": {"outcome": "selected",
                                                        "optionId": "yes"}}}))
    thread.join(timeout=5)

    assert answers == [{"outcome": {"outcome": "selected", "optionId": "yes"}}]


def test_a_client_error_reaches_the_caller_as_one():
    out = Pipe()
    rpc = Connection(reader=io.StringIO(""), writer=out, log=io.StringIO())
    trouble: list = []

    def ask():
        try:
            rpc.call("session/request_permission", {}, timeout=5)
        except RpcError as error:
            trouble.append(error)

    thread = threading.Thread(target=ask)
    thread.start()
    deadline = time.monotonic() + 3
    while not out.messages and time.monotonic() < deadline:
        time.sleep(0.01)
    rpc._handle_line(json.dumps({"jsonrpc": "2.0", "id": out.messages[0]["id"],
                                 "error": {"code": -1, "message": "no"}}))
    thread.join(timeout=5)

    assert trouble and trouble[0].code == -1


def test_a_request_nobody_answers_gives_up_rather_than_waiting_forever():
    """A caller that cannot tell "refused" from "never answered" would treat a
    dead editor as a denial and carry on regardless."""
    out = Pipe()
    rpc = Connection(reader=io.StringIO(""), writer=out, log=io.StringIO())

    with pytest.raises(RpcError, match="not answered"):
        rpc.call("session/request_permission", {}, timeout=0.2)


# --------------------------------------------------------------------------- #
# what an editor is told
# --------------------------------------------------------------------------- #


@pytest.fixture
def driven(config):
    """A real agent, with its output captured."""
    out = Pipe()
    rpc = Connection(reader=io.StringIO(""), writer=out, log=io.StringIO())
    agent = acp_agent.ComodorAgent(config, rpc)
    yield agent, out
    agent.close()


def test_initialize_agrees_on_the_version_and_says_who_it_is(driven):
    agent, _ = driven

    said = agent.initialize({"protocolVersion": 2, "capabilities": {}})

    assert said["protocolVersion"] == acp_agent.PROTOCOL_VERSION == 2
    assert said["info"]["name"] == "comodor"
    assert said["info"]["version"]
    assert said["authMethods"] == [], (
        "an empty list means a client must not call auth/login")


def test_a_session_is_made_in_the_folder_the_editor_names(driven, tmp_path):
    agent, _ = driven
    project = tmp_path / "a-project"
    project.mkdir()

    made = agent.session_new({"cwd": str(project)})

    session = agent.sessions[made["sessionId"]]
    assert session.cwd == project.resolve()
    # And that is what confines every write, which is the whole point of the
    # editor deciding it.
    allowed, _ = session.permissions.path_allowed(project / "x.py")
    refused, _ = session.permissions.path_allowed(tmp_path / "outside.py")
    assert allowed is True and refused is False


def test_a_folder_that_is_not_there_is_refused(driven, tmp_path):
    agent, _ = driven

    with pytest.raises(RpcError, match="no folder"):
        agent.session_new({"cwd": str(tmp_path / "nowhere")})


def test_two_sessions_in_two_projects_do_not_share_a_root(driven, tmp_path):
    agent, _ = driven
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()

    first = agent.sessions[agent.session_new({"cwd": str(one)})["sessionId"]]
    second = agent.sessions[agent.session_new({"cwd": str(two)})["sessionId"]]

    assert first.config.paths.project != second.config.paths.project
    assert first.permissions.path_allowed(two / "x.py")[0] is False


def test_a_prompt_becomes_updates_rather_than_a_long_response(driven, tmp_path):
    """The v2 shape: accepted immediately, and reported by notification."""
    from comodor.events import Kind

    agent, out = driven
    project = tmp_path / "p"
    project.mkdir()
    session = agent.sessions[agent.session_new({"cwd": str(project)})["sessionId"]]

    session.bus.emit(Kind.USER_MESSAGE, text="rename the parser")
    session.bus.emit(Kind.ASSISTANT_START)
    session.bus.emit(Kind.ASSISTANT_DELTA, text="Renaming ")
    session.bus.emit(Kind.ASSISTANT_DELTA, text="it.")
    session.bus.emit(Kind.ASSISTANT_END, text="Renaming it.")

    updates = [m["params"]["update"] for m in out.messages
               if m.get("method") == "session/update"]
    kinds = [u["sessionUpdate"] for u in updates]

    assert kinds == ["user_message", "agent_message_chunk", "agent_message_chunk"]
    assert "".join(u["content"]["text"] for u in updates
                   if u["sessionUpdate"] == "agent_message_chunk") == "Renaming it."
    # Every chunk of one message carries the same id, or the editor draws two.
    ids = {u["messageId"] for u in updates if u["sessionUpdate"] == "agent_message_chunk"}
    assert len(ids) == 1


def test_a_tool_call_starts_and_finishes_under_one_id(driven, tmp_path):
    from comodor.events import Kind

    agent, out = driven
    project = tmp_path / "p"
    project.mkdir()
    session = agent.sessions[agent.session_new({"cwd": str(project)})["sessionId"]]

    session.bus.emit(Kind.TOOL_START, id="call_1", name="read_file",
                     summary="src/parse.py")
    session.bus.emit(Kind.TOOL_END, id="call_1", ok=True, elapsed=0.2,
                     display="142 lines")

    updates = [m["params"]["update"] for m in out.messages
               if m.get("method") == "session/update"]
    assert [u["status"] for u in updates] == ["in_progress", "completed"]
    assert {u["toolCallId"] for u in updates} == {"call_1"}
    assert updates[0]["kind"] == "read"
    assert "142 lines" in updates[1]["content"][0]["content"]["text"]


def test_a_tool_that_failed_is_reported_as_failed(driven, tmp_path):
    from comodor.events import Kind

    agent, out = driven
    project = tmp_path / "p"
    project.mkdir()
    session = agent.sessions[agent.session_new({"cwd": str(project)})["sessionId"]]

    session.bus.emit(Kind.TOOL_START, id="c", name="run_shell", summary="pytest")
    session.bus.emit(Kind.TOOL_END, id="c", ok=False, display="1 failed")

    last = [m["params"]["update"] for m in out.messages
            if m.get("method") == "session/update"][-1]
    assert last["status"] == "failed"


def test_tool_kinds_are_the_ones_acp_names():
    """Wrong is worse than `other` here: the client picks an icon from it, so
    a shell command wearing a magnifying glass is a lie about what ran."""
    for name, expect in (("read_file", "read"), ("edit_file", "edit"),
                         ("run_shell", "execute"), ("grep", "search"),
                         ("delete_file", "delete"), ("fetch_url", "fetch"),
                         ("todo", "think")):
        assert acp_agent.tool_kind(name) == expect, name

    # Something this build has never heard of — an MCP server's tool.
    assert acp_agent.tool_kind("github_create_issue") == "edit"
    assert acp_agent.tool_kind("wibble") == "other"


def test_a_permission_prompt_is_put_to_the_editor(driven, tmp_path):
    from comodor.events import Kind, Request

    agent, out = driven
    project = tmp_path / "p"
    project.mkdir()
    session = agent.sessions[agent.session_new({"cwd": str(project)})["sessionId"]]

    request = Request(id="ask-1", kind="shell", prompt="Run this?",
                      detail="rm -rf build/", options=["yes", "no", "always"])
    session.bus.emit(Kind.REQUEST, request=request)

    deadline = time.monotonic() + 3
    asked = None
    while time.monotonic() < deadline:
        asked = next((m for m in out.messages
                      if m.get("method") == "session/request_permission"), None)
        if asked:
            break
        time.sleep(0.02)

    assert asked is not None, "the editor was never asked"
    params = asked["params"]
    assert params["title"] == "Run this?"
    assert "rm -rf build/" in params["description"]
    assert [option["optionId"] for option in params["options"]] == [
        "yes", "no", "always"]
    assert [option["kind"] for option in params["options"]] == [
        "allow_once", "reject_once", "allow_always"]

    # Answering the editor answers the worker.
    session.agent.rpc._handle_line(json.dumps({
        "jsonrpc": "2.0", "id": asked["id"],
        "result": {"outcome": {"outcome": "selected", "optionId": "yes"}}}))
    assert request.wait(timeout=3) == "yes"


def test_a_permission_nobody_answers_is_a_refusal(driven, tmp_path, monkeypatch):
    """Assuming yes because an editor went quiet is the wrong way for this to
    fail — it is the difference between a command not running and one that
    ran unattended."""
    from comodor.acp import jsonrpc
    from comodor.events import Request

    monkeypatch.setattr(jsonrpc, "CALL_TIMEOUT", 0.2)
    agent, _ = driven
    project = tmp_path / "p"
    project.mkdir()
    session = agent.sessions[agent.session_new({"cwd": str(project)})["sessionId"]]

    request = Request(id="ask-2", kind="shell", prompt="Run this?",
                      options=["yes", "no"])
    session._ask(request)

    assert request.wait(timeout=3) == "no"


def test_closing_a_session_answers_anything_still_waiting(driven, tmp_path):
    """A worker blocked on a prompt nobody will ever answer is a process that
    does not exit."""
    from comodor.events import Request

    agent, _ = driven
    project = tmp_path / "p"
    project.mkdir()
    session = agent.sessions[agent.session_new({"cwd": str(project)})["sessionId"]]
    request = Request(id="ask-3", kind="shell", prompt="?", options=["yes", "no"])
    session._pending[request.id] = request

    session.close()

    assert request.answered is True


def test_an_attached_file_reaches_the_model_with_its_name(driven):
    """An editor sends a resource block when somebody attaches a file. A wall
    of code dropped into the middle of a sentence is worse than one that says
    what it is."""
    text = acp_agent._as_text([
        {"type": "text", "text": "why is this slow?"},
        {"type": "resource", "resource": {"uri": "file:///p/main.py",
                                          "text": "def f():\n    pass"}},
    ])

    assert "why is this slow?" in text
    assert "file:///p/main.py" in text
    assert "def f():" in text


def test_an_empty_prompt_is_refused_rather_than_started(driven, tmp_path):
    agent, _ = driven
    project = tmp_path / "p"
    project.mkdir()
    made = agent.session_new({"cwd": str(project)})

    with pytest.raises(RpcError, match="nothing in that prompt"):
        agent.session_prompt({"sessionId": made["sessionId"],
                              "prompt": [{"type": "text", "text": "   "}]})


def test_a_prompt_for_a_session_that_does_not_exist_says_so(driven):
    agent, _ = driven

    with pytest.raises(RpcError, match="no session"):
        agent.session_prompt({"sessionId": "nope", "prompt": []})


def test_sessions_can_be_listed_and_deleted(driven, tmp_path):
    agent, _ = driven
    project = tmp_path / "p"
    project.mkdir()
    made = agent.session_new({"cwd": str(project)})
    session = agent.sessions[made["sessionId"]]
    session.meta.title = "Something"
    session._persist()

    listed = agent.session_list({})
    assert made["sessionId"] in [item["sessionId"] for item in listed["sessions"]]

    agent.session_delete({"sessionId": made["sessionId"]})
    assert made["sessionId"] not in agent.sessions
    after = agent.session_list({})
    assert made["sessionId"] not in [item["sessionId"] for item in after["sessions"]]


def test_a_session_can_be_resumed_with_what_was_said(driven, tmp_path):
    from comodor.providers.base import Message, Role

    agent, out = driven
    project = tmp_path / "p"
    project.mkdir()
    made = agent.session_new({"cwd": str(project)})
    session = agent.sessions[made["sessionId"]]
    session.conversation.extend([
        Message(role=Role.USER, content="first thing"),
        Message(role=Role.ASSISTANT, content="done"),
    ])
    session._persist()

    out.lines.clear()
    agent.session_resume({"sessionId": made["sessionId"], "cwd": str(project),
                          "replayFrom": {"type": "start"}})

    replayed = [m["params"]["update"] for m in out.messages
                if m.get("method") == "session/update"]
    assert [u["sessionUpdate"] for u in replayed] == ["user_message", "agent_message"]
    assert replayed[0]["content"][0]["text"] == "first thing"


def test_resuming_without_asking_for_history_replays_nothing(driven, tmp_path):
    from comodor.providers.base import Message, Role

    agent, out = driven
    project = tmp_path / "p"
    project.mkdir()
    made = agent.session_new({"cwd": str(project)})
    agent.sessions[made["sessionId"]].conversation.extend(
        [Message(role=Role.USER, content="hello")])
    agent.sessions[made["sessionId"]]._persist()

    out.lines.clear()
    agent.session_resume({"sessionId": made["sessionId"], "cwd": str(project)})

    assert [m for m in out.messages if m.get("method") == "session/update"] == []


def test_resuming_something_that_never_existed_says_so(driven, tmp_path):
    agent, _ = driven
    project = tmp_path / "p"
    project.mkdir()

    with pytest.raises(RpcError, match="no session"):
        agent.session_resume({"sessionId": "never", "cwd": str(project)})


def test_cancelling_a_session_nobody_started_is_not_an_error(driven):
    """It is a notification: there is no way to report one, and a client is
    allowed to cancel something that has already finished."""
    agent, _ = driven

    agent.session_cancel({"sessionId": "gone"})     # must not raise


def test_it_says_so_when_no_provider_is_configured(config):
    """The client gets a code it can act on rather than a failure on the first
    turn with nothing on screen."""
    from comodor.acp.jsonrpc import AUTH_REQUIRED

    for entry in config.providers.values():
        entry.api_key = ""
        entry.configured = False
    out = Pipe()
    agent = acp_agent.ComodorAgent(config, Connection(reader=io.StringIO(""),
                                                      writer=out,
                                                      log=io.StringIO()))
    try:
        with pytest.raises(RpcError) as raised:
            agent.session_new({"cwd": "."})
        assert raised.value.code == AUTH_REQUIRED
        assert "comodor setup" in raised.value.message
    finally:
        agent.close()


def test_login_is_refused_because_none_is_offered(driven):
    """`authMethods` is empty, so a client must not call this — and one that
    does gets told why rather than a silent success."""
    agent, _ = driven

    with pytest.raises(RpcError):
        agent.login({})
