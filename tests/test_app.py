"""The application shell: key handling, commands, and event plumbing.

``App.run`` needs a real terminal, but everything inside it does not. These
tests build the app, feed it key and mouse events directly, and inspect the
state it produces — which is where the bugs that survive a manual click-through
actually live.
"""

from __future__ import annotations

import time

import pytest

from comodor.events import Event, Kind, Request
from comodor.providers.fake import Script
from comodor.ui import layout as layout_module
from comodor.ui.app import COMMANDS, App
from comodor.ui.input.keys import KeyEvent, MouseEvent, PasteEvent


@pytest.fixture
def app(config, monkeypatch):
    """An app wired to the offline provider, with a fixed terminal size."""
    instance = App(config, demo=True)
    instance.geometry = layout_module.compute(128, 36)
    return instance


def key(name: str, char: str = "", **flags) -> KeyEvent:
    return KeyEvent(name, char, **flags)


def type_text(app: App, text: str) -> None:
    for char in text:
        app._on_key(key("char", char))


# --------------------------------------------------------------------------- #
# editing and sending
# --------------------------------------------------------------------------- #


def test_typing_reaches_the_editor(app):
    type_text(app, "hello world")
    assert app.state.editor.text == "hello world"


def test_enter_sends_and_clears_the_editor(app, monkeypatch):
    sent = []
    monkeypatch.setattr(app, "_start_agent", lambda text: sent.append(text))

    type_text(app, "do the thing")
    app._on_key(key("enter"))

    assert sent == ["do the thing"]
    assert app.state.editor.text == ""
    assert app.state.entries[-1].kind == "user"


def test_ctrl_j_inserts_a_newline_instead_of_sending(app, monkeypatch):
    monkeypatch.setattr(app, "_start_agent", lambda text: pytest.fail("should not send"))
    type_text(app, "line one")
    app._on_key(key("char", "j", ctrl=True))
    type_text(app, "line two")

    assert app.state.editor.text == "line one\nline two"


def test_an_empty_prompt_does_nothing(app, monkeypatch):
    monkeypatch.setattr(app, "_start_agent", lambda text: pytest.fail("should not send"))
    assert app._on_key(key("enter")) is False


def test_paste_is_inserted_whole(app):
    app.state.editor.insert("before ")
    event = PasteEvent("pasted\ncontent")
    # The same path _pump_input takes for a paste event.
    app.state.editor.insert(event.text)
    assert app.state.editor.text == "before pasted\ncontent"


def test_history_recalls_the_previous_message(app, monkeypatch):
    monkeypatch.setattr(app, "_start_agent", lambda text: None)
    type_text(app, "first message")
    app._on_key(key("enter"))

    app._on_key(key("up"))
    assert app.state.editor.text == "first message"


# --------------------------------------------------------------------------- #
# global keys
# --------------------------------------------------------------------------- #


def test_f2_toggles_the_sidebar(app):
    before = app.state.sidebar_visible
    app._on_key(key("f2"))
    assert app.state.sidebar_visible is not before


def test_f3_cycles_the_mode(app):
    assert app.config.agent.mode == "act"
    app._on_key(key("f3"))
    assert app.config.agent.mode == "plan"
    app._on_key(key("f3"))
    assert app.config.agent.mode == "ask"
    app._on_key(key("f3"))
    assert app.config.agent.mode == "chat"
    app._on_key(key("f3"))
    assert app.config.agent.mode == "act"
    assert app.state.status.mode == "act"


def test_f4_toggles_the_loop_and_f5_the_gateway(app):
    app._on_key(key("f4"))
    assert app.config.agent.loop is False
    assert app.state.status.loop is False

    app._on_key(key("f5"))
    assert app.config.gateway.enabled is True
    assert app.state.status.gateway != "Disable"


def test_page_keys_scroll_the_transcript(app):
    app._on_key(key("pgup"))
    assert app.state.scroll > 0
    app._on_key(key("pgdn"))
    assert app.state.scroll == 0


def test_ctrl_c_needs_two_presses_to_quit_when_idle(app):
    app.running = True
    app._on_key(key("char", "c", ctrl=True))
    assert app.running is True, "one press must not quit"
    assert app.state.toasts.items, "the first press should warn"

    app._on_key(key("char", "c", ctrl=True))
    assert app.running is False


def test_escape_stops_a_running_agent_rather_than_quitting(app):
    app.state.status.busy = True
    stopped = []
    app.agent.interrupt = lambda: stopped.append(True)

    app._on_key(key("escape"))
    assert stopped == [True]


# --------------------------------------------------------------------------- #
# mouse
# --------------------------------------------------------------------------- #


def test_clicking_send_submits(app, monkeypatch):
    sent = []
    monkeypatch.setattr(app, "_start_agent", lambda text: sent.append(text))
    type_text(app, "click me")

    send = app.geometry.hints["send"]
    app._on_mouse(MouseEvent(send.x + 2, send.y, "press"))
    assert sent == ["click me"]


def test_clicking_send_while_busy_stops_the_agent(app):
    app.state.status.busy = True
    stopped = []
    app.agent.interrupt = lambda: stopped.append(True)

    send = app.geometry.hints["send"]
    app._on_mouse(MouseEvent(send.x + 2, send.y, "press"))
    assert stopped == [True]


def test_clicking_mode_cycles_it(app):
    mode = app.geometry.hints["mode"]
    app._on_mouse(MouseEvent(mode.x + 2, mode.y, "press"))
    assert app.config.agent.mode == "plan"


def test_the_wheel_scrolls(app):
    app._on_mouse(MouseEvent(50, 10, "scroll_up"))
    assert app.state.scroll == 3
    app._on_mouse(MouseEvent(50, 10, "scroll_down"))
    assert app.state.scroll == 0


def test_clicking_a_panel_moves_focus(app):
    app._on_mouse(MouseEvent(app.geometry.chat.x + 4, app.geometry.chat.y + 4, "press"))
    assert app.state.focus == "chat"


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def test_every_command_in_the_table_has_a_handler(app):
    for name, (handler, description) in COMMANDS.items():
        assert hasattr(app, handler), f"{name} points at a missing handler"
        assert description, f"{name} has no help text"


def test_slash_command_is_dispatched_not_sent_to_the_model(app, monkeypatch):
    monkeypatch.setattr(app, "_start_agent",
                        lambda text: pytest.fail("commands must not reach the model"))
    type_text(app, "/help")
    app._on_key(key("enter"))

    assert app.state.overlay is not None
    assert app.state.overlay.title == "Help"


def test_an_unknown_command_says_so(app):
    app._command("/nonsense", "")
    assert any("unknown command" in toast.text for toast in app.state.toasts.items)


def test_teach_records_a_lesson(app):
    app._command("/teach", "reviewing PRs: read the migration file first")
    lessons = app.memory.store.all_lessons()

    assert len(lessons) == 1
    assert lessons[0].pinned
    assert "migration" in lessons[0].guidance


def test_memory_command_lists_what_was_learned(app):
    app._command("/teach", "deploying: always run the smoke test after")
    app._command("/memory", "")

    assert app.state.overlay is not None
    assert app.state.overlay.kind == "select"
    assert any("deploying" in label for label, _ in app.state.overlay.items)


def test_mode_command_rejects_a_bad_value(app):
    app._command("/mode", "turbo")
    assert app.config.agent.mode == "act"
    assert any("act, plan, ask or chat" in toast.text
               for toast in app.state.toasts.items)


def test_clear_resets_the_conversation(app):
    app.state.entries.append(app.state.entries.__class__())  # placeholder entry type
    app._command("/clear", "")
    assert app.state.entries == []
    assert app.conversation.messages == []


def test_approve_toggles_auto_approval(app):
    assert app.config.safety.auto_approve_shell is True
    app._command("/approve", "shell")
    assert app.config.safety.auto_approve_shell is False


def test_completion_accepts_the_selected_command(app):
    type_text(app, "/mem")
    matches = app._completions()
    assert matches

    app._on_key(key("tab"))
    assert app.state.editor.text.startswith("/memory")


# --------------------------------------------------------------------------- #
# agent events
# --------------------------------------------------------------------------- #


def test_streamed_deltas_accumulate_into_one_entry(app):
    app.bus.emit(Kind.ASSISTANT_START)
    app.bus.emit(Kind.ASSISTANT_DELTA, text="Hello ")
    app.bus.emit(Kind.ASSISTANT_DELTA, text="world")
    app._pump_events()

    assert app.state.entries[-1].kind == "assistant"
    assert app.state.entries[-1].text == "Hello world"
    assert app.state.entries[-1].streaming


def test_an_empty_assistant_turn_leaves_no_blank_entry(app):
    app.bus.emit(Kind.ASSISTANT_START)
    app.bus.emit(Kind.ASSISTANT_END, text="")
    app._pump_events()

    assert not [entry for entry in app.state.entries if entry.kind == "assistant"]


def test_tool_events_become_a_card_that_completes(app):
    app.bus.emit(Kind.TOOL_START, id="t1", name="read_file", summary="read a.py")
    app._pump_events()
    card = app.state.entries[-1]
    assert card.meta["running"] is True

    app.bus.emit(Kind.TOOL_END, id="t1", name="read_file", ok=True,
                 display="file contents", elapsed=0.4, meta={})
    app._pump_events()

    assert card.meta["running"] is False
    assert card.meta["elapsed"] == 0.4
    assert card.meta["preview"] == "file contents"


def test_usage_events_update_the_gauge(app):
    app.bus.emit(Kind.USAGE, context_used=250_000, context_limit=1_000_000,
                 cost_usd=0.12, input_tokens=1000, output_tokens=200)
    app._pump_events()

    assert app.state.status.context_used == 250_000
    assert app.state.status.cost_usd == 0.12
    assert app.state.status.fill == pytest.approx(0.25)


def test_todo_events_populate_the_sidebar(app):
    app.bus.emit(Kind.TODO, items=[{"text": "step one", "state": "done"}])
    app._pump_events()
    assert app.state.history.todos[0]["text"] == "step one"


def test_recalled_memory_is_shown_in_the_transcript(app):
    app.bus.emit(Kind.MEMORY, action="recalled",
                 items=[{"guidance": "a lesson"}, {"guidance": "another"}])
    app._pump_events()

    entry = app.state.entries[-1]
    assert entry.kind == "memory"
    assert "2 lesson" in entry.text


def test_errors_are_shown_and_mark_the_connection_down(app):
    app.bus.emit(Kind.ERROR, text="provider exploded")
    app._pump_events()

    assert app.state.entries[-1].kind == "error"
    assert app.state.status.connected is False


# --------------------------------------------------------------------------- #
# permission overlays
# --------------------------------------------------------------------------- #


def make_request(prompt: str = "write a.py") -> Request:
    return Request(id="p1", prompt=prompt, options=["allow", "allow_always", "deny"],
                   detail="--- a/a.py\n+++ b/a.py\n+new line\n", kind="permission",
                   meta={"tool": "write_file", "risk": 1})


def test_a_permission_request_opens_a_dialog(app):
    request = make_request()
    app.bus.ask(request)
    app._pump_events()

    assert app.state.overlay is not None
    assert app.state.overlay.kind == "permission"
    assert "write a.py" in app.state.overlay.body


@pytest.mark.parametrize("pressed,expected", [
    ("y", "allow"), ("a", "allow_always"), ("n", "deny"),
])
def test_the_dialog_answers_the_waiting_worker(app, pressed, expected):
    request = make_request()
    app.bus.ask(request)
    app._pump_events()

    app._on_key(key("char", pressed))
    assert request.answered
    assert request.wait(0.1) == expected
    assert app.state.overlay is None


def test_escape_denies_rather_than_leaving_the_worker_hanging(app):
    request = make_request()
    app.bus.ask(request)
    app._pump_events()

    app._on_key(key("escape"))
    assert request.wait(0.1) == "deny"


def test_a_second_request_queues_behind_the_first(app):
    first, second = make_request("first"), make_request("second")
    app.bus.ask(first)
    app.bus.ask(second)
    app._pump_events()

    assert app.state.overlay.body == "first"
    app._on_key(key("char", "y"))
    assert app.state.overlay is not None
    assert app.state.overlay.body == "second"


def test_keys_do_not_reach_the_editor_while_a_dialog_is_open(app):
    app.bus.ask(make_request())
    app._pump_events()

    type_text(app, "xqw")           # none of these are dialog hotkeys
    assert app.state.editor.text == ""
    assert app.state.overlay is not None, "the dialog must stay up"


# --------------------------------------------------------------------------- #
# mode-change proposals
# --------------------------------------------------------------------------- #

def make_mode_request(target: str = "act", current: str = "plan") -> Request:
    from comodor.tools.propose_mode import _options_for

    return Request(id="m1", prompt=f"Switch to {target} mode? The plan is done.",
                   options=_options_for(current, target),
                   kind="mode", meta={"current": current, "target": target})

def test_a_mode_proposal_opens_a_mode_dialog(app):
    request = make_mode_request()
    app.bus.ask(request)
    app._pump_events()

    assert app.state.overlay is not None
    assert app.state.overlay.kind == "mode"
    assert "Switch to act mode" in app.state.overlay.body

def test_the_mode_dialog_answers_and_updates_the_status_bar(app):
    app.config.agent.mode = "plan"
    request = make_mode_request()
    app.bus.ask(request)
    app._pump_events()

    app._on_key(key("char", "a"))       # the proposal is the first choice
    assert request.wait(0.1) == "act"
    assert app.state.overlay is None
    # The switch shows immediately, not only once the tool reads the answer.
    assert app.state.status.mode == "act"
    assert app.config.agent.mode == "act"

def test_the_mode_dialog_declines_on_the_last_choice(app):
    app.config.agent.mode = "plan"
    request = make_mode_request()
    app.bus.ask(request)
    app._pump_events()

    app._on_key(key("char", "c"))       # the current mode is the last choice
    assert request.wait(0.1) == "plan"
    assert app.config.agent.mode == "plan"


# --------------------------------------------------------------------------- #
# rendering the live state
# --------------------------------------------------------------------------- #


def test_the_app_renders_at_a_range_of_sizes(app):
    for width, height in ((40, 12), (80, 24), (128, 36), (200, 50)):
        app.console.size = (width, height)
        frame = app._frame()
        assert frame is not None


def test_a_full_turn_through_the_real_agent_updates_the_screen(config, bus):
    """The whole pipeline, from a scripted provider to rendered entries."""
    from comodor.providers.base import ToolCall

    app = App(config, demo=True)
    app.gateway._scripts = None
    app.gateway._instances.clear()
    from comodor.providers.fake import FakeProvider

    app.gateway._instances["fake"] = FakeProvider([
        Script(text="Listing files.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="There are a few files."),
    ])

    app.agent.run("what is in this project?")
    app._pump_events()

    kinds = [entry.kind for entry in app.state.entries]
    assert "assistant" in kinds
    assert "tool" in kinds
    assert app.state.status.busy is False


# --------------------------------------------------------------------------- #
# Reflex in the interface
# --------------------------------------------------------------------------- #


def test_a_learned_rule_appears_in_the_transcript_with_a_way_out(app):
    """Silent adaptation is the version of this feature nobody trusts."""
    app.bus.emit(Kind.MEMORY, action="rule",
                 items=[{"id": 7, "statement": "Use single quotes.",
                         "support": 3, "source": "correction"}])
    app._pump_events()

    entry = app.state.entries[-1]
    assert entry.kind == "memory"
    assert "learned: Use single quotes." in entry.text
    assert "/rules forget 7" in entry.meta["hint"]


def test_rules_command_reports_an_empty_brain_honestly(app):
    app._command("/rules", "")
    assert app.state.overlay is not None
    assert "Nothing learned yet" in app.state.overlay.body


def test_rules_can_be_stated_outright_and_take_effect(app):
    app._command("/rules", "teach Never add comments unless asked.")
    statements = [rule.statement for rule in app.memory.active_rules()]
    assert any("comments" in statement for statement in statements)


def test_rules_export_writes_a_committable_file(app):
    app._command("/rules", "teach Prefer composition over inheritance.")
    app._command("/rules", "export")

    exported = app.config.paths.project_dir / "house-rules.md"
    assert exported.exists()
    assert "composition" in exported.read_text(encoding="utf-8")


def test_a_learned_rule_can_be_dropped_again(app):
    rule = app.memory.teach_rule("Always use tabs.")
    app._command("/rules", f"forget {rule.id}")
    assert not app.memory.all_rules()


def test_progress_opens_and_says_when_there_is_too_little_data(app):
    app._command("/progress", "")
    assert app.state.overlay is not None
    assert app.state.overlay.title == "Progress"
    assert app.state.overlay.meta.get("renderable") is not None


def test_undo_is_recorded_as_a_rejection(app, workspace):
    target = workspace / "a.py"
    target.write_text("original\n", encoding="utf-8")
    app.checkpoints.snapshot(target, action="edit", after="changed\n")
    target.write_text("changed\n", encoding="utf-8")

    app._command("/undo", "")
    app.memory.store.flush()

    assert target.read_text() == "original\n"
    assert any(signal.kind == "undo" for signal in app.memory.store.recent_signals())


def test_a_denied_permission_teaches_a_rule(app):
    app.permissions.on_denied("run_shell", "run: rm -rf build")
    statements = [rule.statement for rule in app.memory.active_rules()]
    assert any("rm" in statement for statement in statements)


def test_prefetch_warms_recall_while_typing(app, monkeypatch):
    warmed: list[str] = []
    monkeypatch.setattr(app.memory, "prefetch", lambda query: warmed.append(query))

    type_text(app, "add a health endpoint")
    app._last_keystroke = 0.0                 # pretend the pause has elapsed
    app._maybe_prefetch()
    time.sleep(0.05)

    assert warmed == ["add a health endpoint"]


def test_prefetch_ignores_commands_and_short_drafts(app, monkeypatch):
    warmed: list[str] = []
    monkeypatch.setattr(app.memory, "prefetch", lambda query: warmed.append(query))
    app._last_keystroke = 0.0

    type_text(app, "/help")
    app._maybe_prefetch()
    app.state.editor.clear()
    type_text(app, "hi")
    app._maybe_prefetch()
    time.sleep(0.05)

    assert warmed == []


# --------------------------------------------------------------------------- #
# the question form
#
# Driven through the same key path a person uses, because the bugs here are in
# which handler sees a key first: escape inside the write-your-own editor
# reached the generic overlay handler and threw the whole form away.
# --------------------------------------------------------------------------- #


def a_form_request() -> Request:
    from comodor.questions import encode, parse

    questions = parse([
        {"question": "Which database?", "header": "Database",
         "options": [{"label": "PostgreSQL"}, {"label": "SQLite"}]},
        {"question": "Keep the old API?", "header": "Old API",
         "options": [{"label": "Keep it"}, {"label": "Replace it"}]},
    ])
    return Request(id="ask-1", prompt="2 questions", options=[],
                   kind="questions", meta={"questions": encode(questions)})


@pytest.fixture
def asked(app):
    request = a_form_request()
    app.bus.publish(Event(kind=Kind.REQUEST, payload={"request": request}))
    app._pump_events()
    return request


def test_a_question_request_opens_a_form_not_a_permission_prompt(app, asked):
    assert app.state.overlay is not None
    assert app.state.overlay.kind == "questions"
    assert app.state.overlay.form is not None


def test_arrows_move_within_a_question_and_across_questions(app, asked):
    form = app.state.overlay.form
    app._on_key(key("down"))
    assert form.cursor == 1
    app._on_key(key("right"))
    assert form.current == 1
    app._on_key(key("left"))
    assert form.current == 0
    # And the cursor was kept where it was left.
    assert form.cursor == 1


def test_space_picks_and_enter_moves_to_the_next_unanswered(app, asked):
    form = app.state.overlay.form
    app._on_key(key("char", " "))
    assert form.answers()[0].chosen == ["PostgreSQL"]
    app._on_key(key("enter"))
    assert form.current == 1


def test_enter_on_the_last_answer_sends_the_form(app, asked):
    from comodor.questions import decode_answers

    app._on_key(key("char", " "))
    app._on_key(key("enter"))
    app._on_key(key("char", " "))
    app._on_key(key("enter"))

    assert asked.answered
    assert app.state.overlay is None
    answers = decode_answers(asked.wait(0.1))
    assert answers is not None
    assert [answer.text for answer in answers] == ["PostgreSQL", "Keep it"]


def test_escape_inside_the_editor_stops_typing_and_keeps_the_form(app, asked):
    form = app.state.overlay.form
    form.cursor = len(form.question.options) - 1
    app._on_key(key("char", " "))
    assert form.writing
    type_text(app, "DuckDB")

    app._on_key(key("escape"))
    assert not form.writing
    assert app.state.overlay is not None, "the form was thrown away"
    assert form.answers()[0].written == "DuckDB"


def test_escape_outside_the_editor_dismisses_the_form(app, asked):
    from comodor.questions import CANCELLED, decode_answers

    app._on_key(key("escape"))
    assert app.state.overlay is None
    assert asked.wait(0.1) == CANCELLED
    assert decode_answers(asked.wait(0.1)) is None


def test_typing_a_letter_that_is_a_shortcut_reaches_the_editor(app, asked):
    """A form whose answer contains "s" must not be unanswerable."""
    form = app.state.overlay.form
    form.cursor = len(form.question.options) - 1
    app._on_key(key("char", " "))
    type_text(app, "sqlite")
    assert form.answers()[0].written == "sqlite"
    assert app.state.overlay is not None


def test_ctrl_s_sends_from_anywhere(app, asked):
    from comodor.questions import decode_answers

    app._on_key(key("char", " "))
    app._on_key(key("char", "s", ctrl=True))
    assert asked.answered
    answers = decode_answers(asked.wait(0.1))
    assert answers is not None and len(answers) == 2
    assert answers[0].text == "PostgreSQL"
    assert answers[1].text == "", "the unanswered one comes back unanswered"


def test_a_second_request_waits_its_turn(app, asked):
    second = a_form_request()
    second.id = "ask-2"
    app.bus.publish(Event(kind=Kind.REQUEST, payload={"request": second}))
    app._pump_events()
    assert app.state.overlay.request is asked
    assert second in app.pending_requests

    app._on_key(key("escape"))
    assert app.state.overlay is not None
    assert app.state.overlay.request is second


# --------------------------------------------------------------------------- #
# the two screens, and moving between them
# --------------------------------------------------------------------------- #


def stage_of(app: App) -> str:
    """The stage the next frame would be drawn at.

    Read by drawing one. Asking the predicate directly would test the
    predicate; this tests the thing the application does with it.
    """
    app._frame()
    return app.geometry.stage


def test_a_fresh_session_starts_on_the_opening_screen(app):
    assert stage_of(app) == layout_module.NEW
    assert app.geometry.sidebar is None
    assert app.geometry.composer is not None


def test_a_startup_warning_does_not_start_the_session(app):
    """`_complain_about_the_config` and a failed MCP server both speak before
    the user does. Neither is a conversation."""
    app.bus.emit(Kind.NOTICE, text="config: max_cost_usd cannot be enforced")
    app.bus.emit(Kind.ERROR, text="mcp: filesystem did not start")
    app._pump_events()

    assert app.state.entries, "the warnings were dropped"
    assert stage_of(app) == layout_module.NEW


def test_the_first_message_moves_to_the_active_session(app, monkeypatch):
    monkeypatch.setattr(app, "_start_agent", lambda text: None)
    assert stage_of(app) == layout_module.NEW

    type_text(app, "add a health endpoint")
    app._on_key(key("enter"))

    assert stage_of(app) == layout_module.ACTIVE


def test_the_first_message_survives_the_move(app, monkeypatch):
    """The composer on the opening screen is the same editor the active
    session uses. If it were a second widget, the text typed into it would be
    lost at exactly the moment it stopped being drawn."""
    monkeypatch.setattr(app, "_start_agent", lambda text: None)

    type_text(app, "add a health endpoint")
    app._on_key(key("enter"))

    said = [entry for entry in app.state.entries if entry.kind == "user"]
    assert [entry.text for entry in said] == ["add a health endpoint"]


def test_the_first_message_is_not_delivered_twice(app):
    """One entry, and one run. A transition that re-submits looks identical on
    screen to one that does not, until the bill arrives."""
    started: list[str] = []
    app._start_agent = lambda text: started.append(text)

    type_text(app, "hello")
    app._on_key(key("enter"))
    app._frame()                      # the frame that changes screens
    app._frame()                      # and the one after it

    assert started == ["hello"]
    assert [entry.text for entry in app.state.entries
            if entry.kind == "user"] == ["hello"]


def test_the_move_happens_once_and_stays(app, monkeypatch):
    """No flicker back to the opening screen while the answer streams in."""
    monkeypatch.setattr(app, "_start_agent", lambda text: None)
    type_text(app, "hello")
    app._on_key(key("enter"))

    stages = [stage_of(app)]
    app.bus.emit(Kind.ASSISTANT_START)
    app._pump_events()
    stages.append(stage_of(app))
    app.bus.emit(Kind.ASSISTANT_DELTA, text="wor")
    app._pump_events()
    stages.append(stage_of(app))
    app.bus.emit(Kind.ASSISTANT_END)
    app._pump_events()
    stages.append(stage_of(app))

    assert stages == [layout_module.ACTIVE] * 4


def test_keystrokes_during_the_move_are_not_lost(app, monkeypatch):
    """Typing the next question while the first is still running goes into the
    same buffer. Nothing is re-created between the screens, so there is
    nowhere for it to fall."""
    monkeypatch.setattr(app, "_start_agent", lambda text: None)
    type_text(app, "first")
    app._on_key(key("enter"))
    app._frame()
    type_text(app, "second")

    assert app.state.editor.text == "second"


def test_clearing_a_conversation_returns_to_the_opening_screen(app, monkeypatch):
    monkeypatch.setattr(app, "_start_agent", lambda text: None)
    type_text(app, "hello")
    app._on_key(key("enter"))
    assert stage_of(app) == layout_module.ACTIVE

    app.cmd_clear("")

    assert stage_of(app) == layout_module.NEW


def test_a_resumed_session_never_shows_the_opening_screen(app):
    """Restoring fills the transcript in the constructor, before the first
    frame. A session with history must not flash a welcome at somebody who
    asked to carry on."""
    from comodor.providers.base import Message, Role

    for message in (Message(role=Role.USER, content="add a health endpoint"),
                    Message(role=Role.ASSISTANT, content="I'll add the route.")):
        app.sessions.append("resumed-session", message)

    app._resume("resumed-session")

    assert stage_of(app) == layout_module.ACTIVE
    assert any(entry.kind == "user" for entry in app.state.entries)


# --------------------------------------------------------------------------- #
# the footer has to describe the keyboard that exists
# --------------------------------------------------------------------------- #


#: How to press each stroke the status line advertises.
STROKES = {
    "/": lambda: key("char", "/"),
    "ctrl+d": lambda: key("char", "d", ctrl=True),
    "ctrl+o": lambda: key("char", "o", ctrl=True),
    "ctrl+l": lambda: key("char", "l", ctrl=True),
    "esc": lambda: key("escape"),
    "ctrl+s": lambda: key("char", "s", ctrl=True),
    "[TAB]": lambda: key("tab"),
}


def test_every_key_the_footer_advertises_is_actually_bound(app):
    """The test that would have caught this, and will catch the next one.

    Asserting that one wrong string is gone only proves that one wrong string
    is gone. This presses each stroke the status line names, on an idle Active
    Session, and requires the application to handle it — which is what a hint
    is promising. `Setting : [ctrl + s]` failed exactly here: nothing in the
    program binds ctrl+s outside an open question form, so the advertised key
    did nothing at all.
    """
    from comodor.ui.widgets.statusbar import KEY_HINTS

    unbound = []
    for name, stroke in KEY_HINTS:
        assert stroke in STROKES, f"no way to press {stroke!r} in this test"
        app.state.overlay = None
        app.state.editor.clear()
        app.state.scroll = 0
        app.state.status.busy = False
        if not app._on_key(STROKES[stroke]()):
            unbound.append(f"{name} : {stroke}")

    assert not unbound, f"the footer advertises keys that do nothing: {unbound}"


def test_control_s_does_nothing_so_it_is_not_advertised(app):
    """Both halves, because either alone is half a proof: the key really is
    unbound, and the footer really does not name it."""
    from comodor.ui.widgets.statusbar import KEY_HINTS

    app.state.overlay = None
    assert app._on_key(key("char", "s", ctrl=True)) is False

    assert not any(stroke == "ctrl+s" for _, stroke in KEY_HINTS)
    assert not any(name.lower().startswith("setting") for name, _ in KEY_HINTS)


def test_escape_does_not_exit_which_is_why_the_footer_stopped_saying_so(app):
    """It stops a running turn and clears a scrollback position. On an idle
    session it is not handled at all, so `Exit : esc` was a second promise the
    keyboard did not keep."""
    app.running = True
    app.state.status.busy = False
    app.state.scroll = 0

    assert app._on_key(key("escape")) is False
    assert app.running is True, "escape must not end the session"

    # And the key that does.
    assert app._on_key(key("char", "d", ctrl=True)) is True
    assert app.running is False


def test_the_settings_are_still_reachable(app):
    """Removing the hint must not remove the route. There is no keyboard
    shortcut, and none was invented; `/settings` is the control, and the
    footer's `Command : /` is how you get to it."""
    assert "/settings" in COMMANDS

    app.state.overlay = None
    app._command("/settings", "")
    assert app.state.overlay is not None
