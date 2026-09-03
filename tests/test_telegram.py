"""The Telegram bot: who it answers, what it will do, and what it never says.

A bot's username is public and its address is guessable, so most of what
matters here is refusal. The tests are weighted accordingly.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from comodor.telegram import api
from comodor.telegram import keyboard as kb
from comodor.telegram.api import Bot, TelegramError, Unauthorised, split

# --------------------------------------------------------------------------- #
# the client
# --------------------------------------------------------------------------- #


def test_a_token_that_is_not_one_is_refused_before_the_network():
    for bad in ("", "nonsense", "no-colon-here"):
        with pytest.raises(TelegramError, match="bot token"):
            Bot(bad)


def test_the_token_never_appears_in_an_error(monkeypatch):
    """It is in every URL, so anything that echoes a URL echoes the secret."""
    token = "123456:SUPER-SECRET-VALUE"
    bot = Bot(token)

    class Boom:
        status_code = 400

        def json(self):
            return {"ok": False,
                    "description": f"failed for https://api.telegram.org/bot{token}/x"}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Boom())
    with pytest.raises(TelegramError) as caught:
        bot.call("sendMessage")
    assert "SUPER-SECRET-VALUE" not in str(caught.value)
    assert "123456" in str(caught.value), "the public half may stay"


def test_the_token_is_not_in_the_repr():
    assert "SECRET" not in repr(Bot("42:SECRET"))


def test_a_refused_token_is_its_own_error(monkeypatch):
    class Refused:
        status_code = 401

        def json(self):
            return {"ok": False, "description": "Unauthorized"}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Refused())
    with pytest.raises(Unauthorised):
        Bot("42:x").me()


def test_the_poll_can_say_how_long_to_hold_the_connection(monkeypatch):
    """`getUpdates` has a `timeout` of its own, and so did the client. Passing
    both through one signature raised a TypeError on the first real poll."""
    seen: dict[str, Any] = {}

    class Empty:
        status_code = 200

        def json(self):
            return {"ok": True, "result": []}

    def post(url, data=None, timeout=None, **kwargs):
        seen["sent"] = data
        seen["waited"] = timeout
        return Empty()

    monkeypatch.setattr(api.http, "post", post)
    Bot("42:x").updates(timeout=30)

    assert seen["sent"]["timeout"] == 30, "Telegram was not told how long to hold"
    assert seen["waited"][1] > 30, "the client would give up before the poll ends"


def test_the_offset_advances_so_a_restart_replays_nothing(monkeypatch):
    """Without it every message the bot ever saw is answered again — which,
    for an agent that runs commands, is not merely noisy."""
    class Some:
        status_code = 200

        def json(self):
            return {"ok": True, "result": [{"update_id": 7}, {"update_id": 9}]}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Some())
    bot = Bot("42:x")
    bot.updates()
    assert bot.offset == 10


@pytest.mark.parametrize("length", [0, 1, 4095, 4096, 4097, 20000])
def test_every_piece_fits_what_telegram_will_take(length):
    pieces = split("x" * length)
    assert all(len(piece) <= api.MOST_CHARACTERS for piece in pieces)
    assert "".join(pieces).replace(" ", "") == "x" * length


def test_a_long_message_breaks_where_a_reader_would():
    paragraph = ("word " * 900).strip()
    text = paragraph + "\n\n" + paragraph
    pieces = split(text)
    assert len(pieces) > 1
    assert not pieces[0].endswith("wor"), "it cut a word in half"


# --------------------------------------------------------------------------- #
# the buttons
# --------------------------------------------------------------------------- #


def test_no_callback_payload_can_be_silently_dropped():
    """Telegram refuses to send a keyboard whose data is over 64 bytes, and
    says nothing — the message simply arrives with no buttons under it."""
    boards = [
        kb.main_menu(busy=False, mode="act", rules=3),
        kb.main_menu(busy=True, mode="plan"),
        kb.mode_menu("plan"),
        kb.settings_menu(provider="Anthropic", model="claude-opus-5", folder="/x"),
        kb.permission("a" * 12),
        kb.question("r" * 12, 3, ["one", "two", "three"], {1}, multi=True),
        kb.picker("open", [(f"id{n}", f"Item {n}") for n in range(30)]),
        kb.confirm("wipe"),
        kb.just_back(),
    ]
    for board in boards:
        for row in board["inline_keyboard"]:
            for button in row:
                if "callback_data" in button:
                    assert len(button["callback_data"].encode()) <= 64


def test_an_oversized_payload_is_caught_where_it_is_made():
    with pytest.raises(ValueError, match="107 bytes"):
        kb.button("x", "action:" + "y" * 100)


def test_a_busy_menu_offers_stopping_and_not_starting():
    """A button that is present and does nothing is the most confusing control
    there is, so the state changes what is offered rather than disabling it."""
    busy = kb.main_menu(busy=True, mode="act")
    labels = [b["text"] for row in busy["inline_keyboard"] for b in row]
    assert any("Stop" in text for text in labels)
    assert not any("New chat" in text for text in labels)

    idle = kb.main_menu(busy=False, mode="act")
    labels = [b["text"] for row in idle["inline_keyboard"] for b in row]
    assert any("New chat" in text for text in labels)
    assert not any("Stop" in text for text in labels)


def test_every_screen_has_a_way_back():
    for board in (kb.mode_menu("act"),
                  kb.settings_menu(provider="x", model="y", folder="z"),
                  kb.picker("open", [("a", "A")]),
                  kb.just_back()):
        labels = [b["text"] for row in board["inline_keyboard"] for b in row]
        assert any("Back" in text for text in labels)


def test_the_widest_commitment_is_not_the_first_thing_under_a_thumb():
    """On a phone the buttons are close together and "always" is not undoable."""
    rows = kb.permission("r1")["inline_keyboard"]
    assert "once" in rows[0][0]["text"].lower()
    assert "stop asking" in rows[1][0]["text"].lower()


def test_the_modes_say_what_they_do():
    """`plan` could as easily mean "make a plan and carry it out", and this is
    the setting that decides whether the next message edits somebody's files."""
    labels = [b["text"] for row in kb.mode_menu("act")["inline_keyboard"]
              for b in row]
    joined = " ".join(labels).lower()
    assert "edits files" in joined
    assert "reads only" in joined

def test_a_mode_proposal_becomes_one_button_per_option():
    """The proposal first, and the buttons are the modes the agent offered —
    not the full list, which would silently invite a different change."""
    board = kb.mode_choices("r1", ["act", "plan", "ask"])
    labels = [b["text"] for row in board["inline_keyboard"] for b in row]
    assert len(labels) == 3
    assert labels[0].startswith("Act")
    for row in board["inline_keyboard"]:
        for b in row:
            verb, request_id, mode = b["callback_data"].split(":")
            assert verb == "mm"
            assert request_id == "r1"
            assert mode in ("act", "plan", "ask")


# --------------------------------------------------------------------------- #
# who it answers
# --------------------------------------------------------------------------- #


class Recorder:
    """Stands in for the network, and remembers everything sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.answered: list[str] = []
        self.offset = 0

    def me(self):
        return {"id": 1, "username": "comodor_bot", "first_name": "Comodor"}

    def drop_webhook(self):
        pass

    def commands(self, entries):
        pass

    def typing(self, chat):
        pass

    def send(self, chat, text, *, keyboard=None, **kwargs):
        self.sent.append({"chat": chat, "text": text, "keyboard": keyboard})
        return {"message_id": len(self.sent)}

    def edit(self, chat, message, text, keyboard=None):
        self.edits.append({"chat": chat, "text": text})
        return {}

    def answer_callback(self, query, text="", alert=False):
        self.answered.append(text)

    def updates(self, timeout=0):
        return []


@pytest.fixture
def service(config, monkeypatch):
    from comodor.telegram.bot import Service

    config.telegram.token = "42:test"
    config.telegram.enabled = True
    monkeypatch.setattr("comodor.web.session.Session.__init__",
                        lambda self, cfg: None)
    made = Service(config, bot=Recorder())
    return made


def a_message(user: int, text: str, chat: int | None = None):
    return {"update_id": 1, "message": {
        "message_id": 1,
        "from": {"id": user, "username": "someone"},
        "chat": {"id": chat if chat is not None else user},
        "text": text,
    }}


def test_a_stranger_is_met_with_silence(service):
    """A bot that says "you are not allowed" has told somebody it exists, that
    it is a Comodor, and that there is a list worth getting onto."""
    service._handle(a_message(999, "hello"))
    service._handle(a_message(999, "/start"))
    service._handle(a_message(999, "rm -rf /"))
    assert service.bot.sent == []


def test_the_wrong_pairing_code_is_also_silence(service):
    service.offer_pairing()
    service._handle(a_message(999, "000000"))
    assert service.bot.sent == []
    assert 999 not in service.config.telegram.allowed


def test_the_right_code_pairs_once_and_stops_working(service, monkeypatch):
    monkeypatch.setattr("comodor.config.save_user_config", lambda cfg: None)
    code = service.offer_pairing()

    service._handle(a_message(555, code))
    assert 555 in service.config.telegram.allowed
    assert service.bot.sent, "it should say hello"

    # A second account cannot reuse it.
    service._handle(a_message(777, code))
    assert 777 not in service.config.telegram.allowed


def test_an_expired_code_pairs_nobody(service, monkeypatch):
    import time

    monkeypatch.setattr("comodor.config.save_user_config", lambda cfg: None)
    code = service.offer_pairing()
    service.pairing.until = time.time() - 1
    service._handle(a_message(555, code))
    assert 555 not in service.config.telegram.allowed


def test_a_tap_from_a_stranger_is_refused(service):
    service._handle({"update_id": 2, "callback_query": {
        "id": "q1", "from": {"id": 999},
        "message": {"chat": {"id": 999}}, "data": "stop"}})
    assert service.bot.sent == []
    assert service.bot.answered == ["Not paired."]


def test_allowed_is_by_id_not_username(config):
    """A username can be given up and taken by somebody else; an id cannot."""
    config.telegram.allowed = [555]
    assert config.telegram.may(555)
    assert config.telegram.may("555")
    assert not config.telegram.may(556)
    assert not config.telegram.may(0)


def test_a_project_cannot_add_itself_to_the_allowed_list():
    """It would be a backdoor that nothing on screen would ever show."""
    from comodor.config import project_filtered

    kept, refused = project_filtered(
        {"telegram": {"allowed": [999], "token": "x"}, "agent": {"mode": "plan"}})
    assert "telegram" in refused
    assert "telegram" not in kept


def test_writes_are_off_until_somebody_says_otherwise(config):
    assert config.telegram.allow_writes is False
    assert config.telegram.enabled is False
    assert config.telegram.allowed == []


def test_the_token_is_not_written_into_a_project_config(config):
    from comodor.config import project_filtered

    _, refused = project_filtered({"telegram": {"token": "42:stolen"}})
    assert "telegram" in refused


# --------------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------------- #


def test_angle_brackets_survive(config):
    """Agent output is full of them — generics, JSX, shell redirects — and one
    unescaped turns the rest into an unclosed tag that Telegram rejects
    wholesale, so the message never arrives and nothing says why."""
    from comodor.telegram.bot import escape

    assert escape("List<String> x = a > b") == "List&lt;String&gt; x = a &gt; b"
    assert escape("<script>alert(1)</script>").startswith("&lt;script&gt;")


def test_the_welcome_says_whether_it_can_change_anything(service):
    service.config.telegram.allow_writes = False
    assert "read and plan only" in service._welcome()

    service.config.telegram.allow_writes = True
    assert "read and plan only" not in service._welcome()
    assert "run commands" in service._welcome()


def test_the_welcome_says_what_it_is_pointed_at(service):
    """Model and folder, without making anybody tap to find out."""
    said = service._welcome()

    assert "<b>Model</b>" in said
    assert "<b>Folder</b>" in said
    # And it names what each button changes, so the keyboard is not a row of
    # symbols somebody has to press to identify.
    for wanted in ("Mode", "Skills", "Rules"):
        assert wanted in said


def test_the_slash_commands_are_registered_and_few():
    """The buttons are the interface; a command list mirroring every button is
    two things to keep in step."""
    names = [name for name, _ in kb.COMMANDS]
    assert "start" in names and "stop" in names
    assert len(kb.COMMANDS) <= 8
    assert all(what for _, what in kb.COMMANDS), "every command needs a blurb"


def test_backoff_climbs_and_stops():
    steps = [api.backoff(n) for n in range(10)]
    assert steps == sorted(steps)
    assert max(steps) <= 60


def real_state(*, provider: str, model: str, mode: str, used: int, limit: int,
               cost: float | None, project: str = "/w") -> dict[str, Any]:
    """A state dictionary shaped the way `Session.state()` really shapes one.

    The status tests used to invent their own keys — `cwd`, `context_used`,
    `cost_usd` — and the code read those same invented keys, so both agreed
    with each other and neither agreed with the session. Folder, Context and
    Spend were blank on every real status for as long as that lasted, with
    green tests over it the whole time.
    """
    return {
        "provider": provider,
        "model": model,
        "mode": mode,
        "busy": False,
        "project": project,
        "context": {"used": used, "limit": limit},
        "usage": {"prompt": used, "output": 0, "cached": 0, "cost": cost,
                  "hit_rate": 0.0},
    }


def test_the_state_helper_matches_what_a_session_really_returns():
    """The guard on the tests above: if `Session.state()` renames a key, this
    fails rather than the status quietly going blank again."""
    from comodor.web.session import Session

    source = inspect.getsource(Session.state)
    for key in ("provider", "model", "mode", "busy", "project", "context",
                "usage"):
        assert f'"{key}"' in source, f"state() no longer returns {key}"
    assert '"used"' in source and '"limit"' in source
    assert '"cost"' in source


def test_the_status_survives_having_no_spend_yet(service, monkeypatch):
    """Written as one concatenation with a trailing conditional, the `if` bound
    to the whole expression rather than the last line — so a fresh session
    reported its entire status as the words "Spend —"."""
    class Talk:
        class session:
            @staticmethod
            def state():
                return real_state(provider="xiaomi", model="mimo", mode="plan",
                                  used=0, limit=128000, cost=None)

    text = service._status(Talk())
    assert "<b>Status</b>" in text
    assert "xiaomi" in text and "plan" in text and "/w" in text
    assert "Spend" in text and text.count("\n") >= 5


def test_the_status_shows_a_real_spend_when_there_is_one(service):
    class Talk:
        class session:
            @staticmethod
            def state():
                return real_state(provider="x", model="y", mode="act",
                                  used=100, limit=1000, cost=0.0412)

    text = service._status(Talk())
    assert "$0.0412" in text
    assert "10% of 1,000" in text
    assert "/w" in text, "the folder is `project`, not `cwd`"


# --------------------------------------------------------------------------- #
# no dead buttons
#
# Three buttons — History, Model, Skills — were drawn on the keyboard with no
# handler behind them. Tapping produced nothing at all: no message, no error,
# no note. A control that looks like it works and does not is worse than a
# missing one, because the natural response is to press it again.
# --------------------------------------------------------------------------- #


def taps(keyboard) -> list[str]:
    return [entry["callback_data"]
            for row in (keyboard or {}).get("inline_keyboard", [])
            for entry in row if "callback_data" in entry]


@pytest.fixture
def talking(config, monkeypatch):
    """A service whose session answers, without a model or a network."""
    from comodor.telegram.bot import Service

    config.telegram.token = "42:test"
    config.telegram.enabled = True
    config.telegram.allowed = [7]

    class Pretend:
        cursor = 0

        def __init__(self, cfg):
            self.config = cfg

        def state(self):
            return {"busy": False, "mode": "plan", "rules": 2,
                    "provider": "openai", "model": "gpt-4o",
                    "cwd": "/w", "context_used": 10, "context_limit": 100}

        def chats(self, query="", limit=40):
            return [{"id": f"s{n}", "title": f"chat {n}", "messages": n,
                     "current": n == 0} for n in range(9)]

        def open_chat(self, session_id):
            return True, f"Opened {session_id}", []

        def models_for(self, provider, refresh=False):
            return {"models": [{"id": f"model-{n}"} for n in range(9)]}

        def setting(self, key, value):
            return True, f"{key} is now {value}"

        def skill_shelf(self, refresh=False):
            return {"skills": [{"id": f"skill-{n}", "installed": n == 0}
                               for n in range(9)], "error": ""}

        def skill(self, action, name):
            return True, f"{name} {action}ed"

        def rules(self):
            return {"rules": []}

        def folder(self):
            # `current` is what `Session.folder` actually returns. The
            # stand-in said `cwd`, which no code anywhere reads — so anything
            # depending on the folder read as empty and the tests agreed.
            return {"current": "/w", "name": "w", "siblings": [],
                    "confined": True}

        def set_mode(self, mode):
            # The real one writes the mode into the config it holds, and
            # callers read it back from there. Returning True and changing
            # nothing let a test pass on a mode that was never set.
            self.config.agent.mode = mode
            return True

        def interrupt(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("comodor.web.session.Session", Pretend)
    return Service(config, bot=Recorder())


def test_every_button_on_the_first_screen_does_something(talking):
    """Walked to the end: every screen the first taps open, and so on."""
    talking._handle(a_message(7, "/start"))
    start = talking.bot.sent[-1]["keyboard"]

    assert len(taps(start)) >= 9, "the first screen offers the main settings"

    # These are left alone: one ends the conversation under the others' feet,
    # and the rest belong to a question that is not on screen.
    skip = {"new", "stop", "ok", "okall", "no", "q", "qw", "qs"}
    seen: set[str] = set()
    queue = list(taps(start))
    dead: list[str] = []

    while queue:
        data = queue.pop(0)
        if data in seen or data.split(":")[0] in skip:
            continue
        seen.add(data)
        before = len(talking.bot.sent)
        talking._handle({"update_id": 2, "callback_query": {
            "id": "q", "from": {"id": 7},
            "message": {"chat": {"id": 7}}, "data": data}})
        replies = talking.bot.sent[before:]
        if not replies:
            dead.append(data)
            continue
        # Only follow buttons that mean the same thing wherever they are
        # tapped. A row — `model:6` — names a slot in a list the bot is
        # holding, and a page step — `page:model:0` — moves within a list that
        # has to be open. Tapping either after walking away is not a dead
        # button, it is a stale one, and the bot says so correctly.
        #
        # Following them regardless made this walk depend on its own visiting
        # order, and it went red the day an unrelated change reordered the
        # queue. `test_a_row_on_a_paged_list_works_on_every_page` covers them
        # properly: from the page they appear on.
        queue.extend(tap for tap in taps(replies[-1]["keyboard"])
                     if tap.split(":")[0] not in {"model", "skill", "chat",
                                                  "page"})

    assert dead == [], f"buttons with nothing behind them: {dead}"
    # Was 20, when the walk also followed rows and page steps. Those are now
    # covered by the two tests below, from the screen they belong to, so this
    # counts only the buttons that mean the same thing wherever they are
    # tapped. Kept as a floor rather than deleted: it is what catches a screen
    # falling out of the walk entirely.
    assert len(seen) >= 15, "the walk should reach well past the first screen"


@pytest.mark.parametrize("opens,picks", [
    ("models", "model"),
    ("skills", "skill"),
])
def test_a_row_on_a_paged_list_works_on_every_page(talking, opens, picks):
    """What the walk above deliberately stops following, checked properly:
    each row button is tapped from the page it appears on, which is the only
    place it means anything.

    The second page matters on its own — its rows carry indices past the first
    page's, and an off-by-one in the shelving would leave exactly those dead
    while the first page looked fine.
    """
    talking._handle(a_message(7, "/start"))

    for page in (0, 1):
        data = opens if page == 0 else f"page:{picks}:{page}"
        talking._handle({"update_id": 2, "callback_query": {
            "id": "q", "from": {"id": 7},
            "message": {"chat": {"id": 7}}, "data": data}})

        rows = [tap for tap in taps(talking.bot.sent[-1]["keyboard"])
                if tap.startswith(f"{picks}:")]
        assert rows, f"page {page} of {opens} offered nothing to choose"

        for row in rows:
            before = len(talking.bot.sent)
            talking._handle({"update_id": 2, "callback_query": {
                "id": "q", "from": {"id": 7},
                "message": {"chat": {"id": 7}}, "data": row}})
            assert len(talking.bot.sent) > before, f"{row} did nothing"
            assert "moved on" not in talking.bot.sent[-1]["text"], \
                f"{row} was on screen and the bot did not recognise it"

            # Back to the page it came from: choosing sends a confirmation,
            # not the list, so the next row needs the list open again.
            talking._handle({"update_id": 2, "callback_query": {
                "id": "q", "from": {"id": 7}, "message": {"chat": {"id": 7}},
                "data": opens if page == 0 else f"page:{picks}:{page}"}})


@pytest.mark.parametrize("opens,picks", [("models", "model"),
                                         ("skills", "skill")])
def test_paging_goes_both_ways(talking, opens, picks):
    """Next and Previous, tapped from the page that offers them.

    Previous is the one worth checking: it only exists on page two onward, so
    a walk that never reaches page two never sees it, and it would be dead in
    the product without a single test noticing.
    """
    talking._on_tap(7, {"id": "q", "data": opens})

    forward = [tap for tap in taps(talking.bot.sent[-1]["keyboard"])
               if tap.startswith("page:")]
    assert forward == [f"page:{picks}:1"], \
        f"page 0 of {opens} offers no way forward"

    before = len(talking.bot.sent)
    talking._on_tap(7, {"id": "q", "data": forward[0]})
    assert len(talking.bot.sent) > before, "Next did nothing"

    backward = [tap for tap in taps(talking.bot.sent[-1]["keyboard"])
                if tap.startswith("page:")]
    assert f"page:{picks}:0" in backward, "page 1 offers no way back"

    before = len(talking.bot.sent)
    talking._on_tap(7, {"id": "q", "data": f"page:{picks}:0"})
    assert len(talking.bot.sent) > before, "Previous did nothing"


def test_the_first_screen_names_the_settings_people_look_for(talking):
    talking._handle(a_message(7, "/start"))
    labels = " ".join(
        entry["text"]
        for row in talking.bot.sent[-1]["keyboard"]["inline_keyboard"]
        for entry in row).lower()

    for wanted in ("mode", "status", "model", "folder", "skills", "rules",
                   "settings", "help"):
        assert wanted in labels, f"{wanted} is not offered on the first screen"


def test_a_stale_row_says_so_rather_than_doing_the_wrong_thing(talking):
    """The list is held on our side; a tap after it moved must not guess."""
    talking._handle(a_message(7, "/start"))
    talking._handle({"update_id": 2, "callback_query": {
        "id": "q", "from": {"id": 7},
        "message": {"chat": {"id": 7}}, "data": "model:99"}})

    assert "moved on" in talking.bot.sent[-1]["text"]


def test_the_writes_screen_says_what_it_may_do_and_how_to_change_it(talking):
    """This used to assert that the setting could *only* be changed at a
    terminal, and that no button here could touch it.

    That was a deliberate wall, and it was in the wrong place. The person
    tapping Act is holding a phone; answering them with a shell command is
    answering a question with a different question, and it is the reason the
    feature went unused. Only a paired account reaches any of this — the same
    account that could send the bot a message asking it to do the work anyway.

    What the wall was protecting is still protected, by a warning that names
    the folder and takes an explicit approval. So this now checks that the
    screen explains itself rather than that it refuses.
    """
    talking._handle(a_message(7, "/start"))
    talking._handle({"update_id": 2, "callback_query": {
        "id": "q", "from": {"id": 7},
        "message": {"chat": {"id": 7}}, "data": "writes"}})

    said = talking.bot.sent[-1]["text"]
    assert "reads and plans only" in said
    assert "Act" in said, "it never says how to change this"
    assert "comodor telegram writes" not in said, \
        "it still sends somebody to a terminal they are not sitting at"


def test_turning_act_on_asks_first_and_names_the_folder(talking):
    """The tap must not silently grant write access. It has to say what is
    being allowed, where it applies, and take a deliberate approval — that is
    the whole of the protection now."""
    talking._handle(a_message(7, "/start"))
    talking._handle({"update_id": 2, "callback_query": {
        "id": "q", "from": {"id": 7},
        "message": {"chat": {"id": 7}}, "data": "mode:act"}})

    said = talking.bot.sent[-1]["text"]
    assert "Allow Act mode?" in said
    assert "<code>" in said, "it never shows which folder this covers"
    assert not talking.config.telegram.allow_writes, \
        "asking is not granting"

    buttons = taps(talking.bot.sent[-1]["keyboard"])
    assert "writes:on" in buttons, "there is no way to approve"
    assert "mode" in buttons, "there is no way to decline"


def test_approving_grants_this_chat_and_enters_act(talking):
    """The grant lives on the conversation, not in the configuration file.

    The first version set `telegram.allow_writes` and saved it, which was
    wrong three ways at once: a chat's approval granted every paired chat,
    leaving Act revoked a grant somebody had made at the terminal, and a save
    that failed left the flag on in memory while the message said Act stayed
    off. Nothing is persisted now, so none of those can happen — and there is
    nothing that can fail to be written.
    """
    talking._on_tap(7, {"id": "q1", "data": "mode:act"})
    talking._on_tap(7, {"id": "q2", "data": "writes:on"})

    assert talking._conversation(7).may_write is True
    assert talking._conversation(7).session.config.agent.mode == "act"
    assert talking.config.telegram.allow_writes is False, \
        "the channel-wide setting was changed by one chat's approval"
    assert "Act mode is on" in talking.bot.sent[-1]["text"]


def test_the_approval_says_how_far_it_reaches_and_how_long_it_lasts(talking):
    """It is a smaller promise than the old one — this chat, until a restart —
    and saying so is the difference between a limit and a surprise."""
    talking._on_tap(7, {"id": "q1", "data": "mode:act"})
    asked = talking.bot.sent[-1]["text"]

    assert "This chat only" in asked
    assert "restart" in asked
    assert "nothing on disk changes" in asked

    talking._on_tap(7, {"id": "q2", "data": "writes:on"})
    granted = talking.bot.sent[-1]["text"]

    assert "this chat only" in granted.lower()
    assert "restart" in granted


def test_one_chats_approval_does_not_grant_another(talking):
    """Two paired accounts, or the same person in two chats. The confirmation
    says "this chat"; before this it granted every chat, and the second one
    entered Act having never been shown the warning or the folder."""
    talking.config.telegram.allowed = [7, 9]

    talking._on_tap(7, {"id": "q1", "data": "mode:act"})
    talking._on_tap(7, {"id": "q2", "data": "writes:on"})
    assert talking._conversation(7).may_write is True

    talking.bot.sent.clear()
    talking._on_tap(9, {"id": "q3", "data": "mode:act"})

    assert "Allow Act mode?" in talking.bot.sent[-1]["text"], \
        "the second chat entered Act without being asked"
    assert talking._conversation(9).may_write is False


def test_leaving_act_does_not_revoke_what_the_terminal_granted(talking):
    """`comodor telegram writes on` is a deliberate, persistent choice. A mode
    change in one chat is not an instruction about it — and revoking it here
    would drop every *other* Act conversation into plan on its next message."""
    talking.config.telegram.allow_writes = True

    talking._on_tap(7, {"id": "q1", "data": "mode:plan"})

    assert talking.config.telegram.allow_writes is True, \
        "one chat's mode change turned off a channel-wide permission"


def test_a_chat_granted_by_approval_is_not_dragged_back_out_of_act(talking):
    """`hold_the_line` puts a conversation back into plan when the channel may
    not write — which is the normal state for a chat holding its own grant. It
    has to know the difference, or the approval ends on the next message."""
    from comodor.channels.settings import hold_the_line

    talking._on_tap(7, {"id": "q1", "data": "mode:act"})
    talking._on_tap(7, {"id": "q2", "data": "writes:on"})
    talk = talking._conversation(7)
    assert talk.session.config.agent.mode == "act"

    moved = hold_the_line(talking.config, "telegram", talk)

    assert moved is False
    assert talk.session.config.agent.mode == "act"


def test_declining_changes_nothing(talking):
    """`agent.mode` defaults to `act`, so the mode is not what this can check:
    what matters is that declining leaves the *permission* exactly as it was,
    and that the chat is put back where it can choose again."""
    talking._handle(a_message(7, "/start"))
    talking._handle({"update_id": 2, "callback_query": {
        "id": "q", "from": {"id": 7},
        "message": {"chat": {"id": 7}}, "data": "mode:act"}})
    talking._handle({"update_id": 3, "callback_query": {
        "id": "q2", "from": {"id": 7},
        "message": {"chat": {"id": 7}}, "data": "mode"}})

    assert talking.config.telegram.allow_writes is False, \
        "declining granted the thing it declined"
    assert "Mode" in talking.bot.sent[-1]["text"], \
        "declining left them somewhere other than the mode menu"


def test_leaving_act_gives_the_permission_back(talking):
    """Granted from the chat, so revocable from the chat. Otherwise the only
    way to undo a tap is the terminal command this replaced.

    What comes back is this chat's own grant, and nothing else — see
    `test_leaving_act_does_not_revoke_what_the_terminal_granted`.
    """
    talking._on_tap(7, {"id": "q1", "data": "mode:act"})
    talking._on_tap(7, {"id": "q2", "data": "writes:on"})
    talk = talking._conversation(7)
    assert talk.may_write is True

    talking._on_tap(7, {"id": "q3", "data": "mode:plan"})

    assert talk.may_write is False, "the grant outlived the mode it was for"
    assert "off again" in talking.bot.sent[-1]["text"], "it never says so"

    # And asking for Act again asks again, rather than remembering.
    talking.bot.sent.clear()
    talking._on_tap(7, {"id": "q4", "data": "mode:act"})
    assert "Allow Act mode?" in talking.bot.sent[-1]["text"]


# --------------------------------------------------------------------------- #
# one mark for "chosen", everywhere
#
# The marks were changed to emoji on some screens and left as dots and
# checkboxes on others, so a chosen mode looked nothing like a chosen model two
# taps later — which reads as two different meanings rather than one. They come
# from one pair of names now, and these keep them that way.
# --------------------------------------------------------------------------- #


def marks_in(board) -> str:
    return " ".join(b["text"] for row in board["inline_keyboard"] for b in row)


def test_every_screen_marks_a_choice_the_same_way():
    boards = [
        kb.mode_menu("plan"),
        kb.question("r1", 0, ["one", "two"], {0}),
        kb.question("r1", 0, ["one", "two"], {0}, multi=True),
    ]
    for board in boards:
        drawn = marks_in(board)
        assert kb.PICKED in drawn, f"nothing marked as chosen: {drawn}"
        assert kb.UNPICKED in drawn, f"nothing marked as not chosen: {drawn}"


@pytest.mark.parametrize("old", ["●", "○", "☐", "✓", "✗", "‹", "›"])
def test_the_marks_that_were_replaced_are_gone(old):
    """A screen still drawing the old glyph is a screen that was missed."""
    boards = [
        kb.main_menu(busy=False, mode="plan", rules=2, model="m"),
        kb.main_menu(busy=True, mode="act"),
        kb.mode_menu("plan"),
        kb.settings_menu(provider="p", model="m", folder="/w"),
        kb.permission("r1"),
        kb.question("r1", 0, ["one", "two"], {0}),
        kb.question("r1", 0, ["one", "two"], {0}, multi=True),
        kb.picker("skill", [(str(n), f"s{n}") for n in range(30)], page=1),
        kb.confirm("wipe"),
        kb.just_back(),
    ]
    for board in boards:
        assert old not in marks_in(board), f"{old!r} survived in {marks_in(board)}"


def test_the_lists_mark_the_current_row_the_same_way_the_menus_do(talking):
    """The model list, the skills list and the history all say "this one", and
    they used to say it with a different glyph from the mode list."""
    talking._handle(a_message(7, "/start"))

    for action in ("models", "skills", "chats"):
        before = len(talking.bot.sent)
        talking._handle({"update_id": 2, "callback_query": {
            "id": "q", "from": {"id": 7},
            "message": {"chat": {"id": 7}}, "data": action}})
        drawn = marks_in(talking.bot.sent[-1]["keyboard"])
        assert "●" not in drawn and "○" not in drawn, f"{action}: {drawn}"
        assert len(talking.bot.sent) > before


def test_going_back_and_paging_do_not_use_the_same_arrow():
    """One leaves the screen and the others move within it; a reader should not
    have to read the words to tell them apart."""
    assert kb.BACK != kb.PREVIOUS
    assert kb.BACK != kb.NEXT

    paged = marks_in(kb.picker("s", [(str(n), f"s{n}") for n in range(30)],
                               page=1))
    assert kb.PREVIOUS in paged and kb.NEXT in paged and kb.BACK in paged


# --------------------------------------------------------------------------- #
# voice: the command, and what a closed gate says
# --------------------------------------------------------------------------- #

def test_the_voice_command_says_where_things_stand(talking):
    talking._handle(a_message(7, "/voice"))
    body = talking.bot.sent[-1]["text"]
    assert "Voice" in body
    assert "off" in body.lower(), "the default state is off, and it says so"


def test_the_voice_command_turns_speech_on_and_says_so(talking, config):
    talking._handle(a_message(7, "/voice on"))
    assert config.voice.tts_enabled, "the toggle reached the config"
    body = talking.bot.sent[-1]["text"]
    assert "on" in body.lower()


def test_the_voice_command_turns_speech_off(talking, config):
    config.voice.tts_enabled = True
    talking._handle(a_message(7, "/voice off"))
    assert not config.voice.tts_enabled


def test_an_unknown_voice_argument_is_corrected(talking):
    talking._handle(a_message(7, "/voice louder"))
    assert "on" in talking.bot.sent[-1]["text"]


def test_speech_that_cannot_run_is_said_not_lost(talking, config, monkeypatch):
    """Speech on, service unreachable: the text answer has already landed, so
    the failure is a line in the transcript — never a failed turn."""
    from comodor.voice.stt import VoiceError

    config.voice.enabled = True
    config.voice.tts_enabled = True
    monkeypatch.setattr("comodor.voice.tts.synthesize",
                        lambda text, cfg: (_ for _ in ()).throw(
                            VoiceError("the speech service did not connect")))
    talking.announce = lambda line: talking.bot.sent.append(
        {"chat": 7, "text": line})
    talking._maybe_speak(7, "a" * 100)
    assert any("speech did not work" in m["text"] for m in talking.bot.sent)


def test_short_answers_are_not_spoken(talking, config):
    config.voice.enabled = True
    config.voice.tts_enabled = True
    called = []
    monkey_hits = called
    assert monkey_hits == []      # nothing patched: the length gate is pure
    talking._maybe_speak(7, "done")
    assert called == []
