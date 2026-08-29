"""WhatsApp: who it answers, what it will send, and what it never says.

The number is a phone number, so most of what matters here is refusal —
strangers message phone numbers as a matter of course, and a business number
is published on purpose.

The other half is Meta's limits. Three reply buttons, twenty characters a
label, ten rows in a list: every one of those is a hard API error rather than
something Meta trims for you, and a message that fails to send arrives as a bot
that answers nothing with the reason only in a log. So the limits are asserted
rather than remembered.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest

from comodor.config import Config, Paths
from comodor.whatsapp import menu as ui
from comodor.whatsapp import webhook as wh
from comodor.whatsapp.api import (
    BUTTON_ID,
    BUTTON_TITLE,
    MOST_BUTTONS,
    MOST_ROWS,
    ROW_TITLE,
    Cloud,
    WhatsAppError,
    split,
)

SECRET = "an-app-secret"


@pytest.fixture
def config(tmp_path):
    made = Config(paths=Paths(user=tmp_path / "home", project=tmp_path / "work"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    made.whatsapp.token = "EAA-token"
    made.whatsapp.phone_number_id = "1234567890"
    made.whatsapp.app_secret = SECRET
    made.whatsapp.verify_token = "verify-me"
    made.whatsapp.allowed = ["15550001111"]
    return made


# --------------------------------------------------------------------------- #
# the client
# --------------------------------------------------------------------------- #


def test_a_phone_number_is_not_a_phone_number_id():
    """Meta addresses the number by an id, and pasting the number itself is
    the first thing everybody does."""
    with pytest.raises(WhatsAppError, match="not the number itself"):
        Cloud("token", "+1 555 000 1111")


def test_no_token_is_refused_before_the_network():
    with pytest.raises(WhatsAppError, match="no access token"):
        Cloud("", "1234567890")


def test_the_token_is_not_in_the_repr():
    assert "SECRET" not in repr(Cloud("EAASECRET", "1234567890"))


def test_the_token_never_appears_in_an_error():
    cloud = Cloud("EAA-SUPER-SECRET", "1234567890")
    hidden = cloud._hide("failed calling ?access_token=EAA-SUPER-SECRET")
    assert "EAA-SUPER-SECRET" not in hidden


def test_an_expired_token_is_its_own_error(monkeypatch):
    from comodor.whatsapp import api

    class Refused:
        status_code = 401

        def json(self):
            return {"error": {"code": 190, "message": "Session expired"}}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Refused())
    monkeypatch.setattr(api.http, "get", lambda *a, **k: Refused())
    with pytest.raises(api.Unauthorised, match="twenty-four hours"):
        Cloud("t", "1234567890").me()


def test_the_day_long_window_is_its_own_error(monkeypatch):
    """Not a fault to retry. It means the conversation went cold, and only the
    person writing again reopens it."""
    from comodor.whatsapp import api

    class Closed:
        status_code = 400

        def json(self):
            return {"error": {"code": 131047, "message": "Re-engagement"}}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Closed())
    with pytest.raises(api.OutsideWindow):
        Cloud("t", "1234567890").send("15550001111", "hello")


def test_meta_error_details_are_kept_not_just_the_headline(monkeypatch):
    """Their `message` is "Unsupported post request" for almost everything;
    `error_data.details` is the part that says what went wrong."""
    from comodor.whatsapp import api

    class Vague:
        status_code = 400

        def json(self):
            return {"error": {"code": 100, "message": "Unsupported request",
                              "error_data": {"details": "button title is too "
                                                        "long"}}}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Vague())
    with pytest.raises(WhatsAppError, match="button title is too long"):
        Cloud("t", "1234567890").send("1", "x")


@pytest.mark.parametrize("length", [0, 1, 4095, 4096, 4097, 20000])
def test_every_piece_fits_what_whatsapp_will_take(length):
    pieces = split("x" * length)
    assert all(len(piece) <= 4096 for piece in pieces)
    assert "".join(pieces).replace(" ", "") == "x" * length


# --------------------------------------------------------------------------- #
# Meta's limits, which are errors and not trims
# --------------------------------------------------------------------------- #


def test_more_than_three_buttons_is_refused_here_not_by_meta(monkeypatch):
    from comodor.whatsapp import api

    monkeypatch.setattr(api.http, "post", lambda *a, **k: None)
    with pytest.raises(WhatsAppError, match="has to be a list message"):
        Cloud("t", "1234567890").send_buttons(
            "1", "pick", [(f"k{n}", f"L{n}") for n in range(4)])


def test_more_than_ten_rows_is_refused(monkeypatch):
    from comodor.whatsapp import api

    monkeypatch.setattr(api.http, "post", lambda *a, **k: None)
    with pytest.raises(WhatsAppError, match="not 11"):
        Cloud("t", "1234567890").send_list(
            "1", "pick", "Open",
            [(f"k{n}", f"row {n}", "") for n in range(11)])


def test_long_labels_are_clipped_rather_than_failing_the_message(monkeypatch):
    """Meta rejects the whole message for one over-long label, and a menu that
    fails to send is indistinguishable from a bot that is down."""
    from comodor.whatsapp import api

    sent: dict[str, Any] = {}

    class Ok:
        status_code = 200

        def json(self):
            return {"messages": [{"id": "wamid.x"}]}

    def post(url, json=None, **kw):
        sent.update(json or {})
        return Ok()

    monkeypatch.setattr(api.http, "post", post)
    Cloud("t", "1234567890").send_buttons(
        "1", "pick", [("k" * 400, "a label far longer than twenty")])

    button = sent["interactive"]["action"]["buttons"][0]["reply"]
    assert len(button["title"]) <= BUTTON_TITLE
    assert len(button["id"]) <= BUTTON_ID


def test_the_main_menu_fits_a_list_exactly():
    rows = ui.main_menu(busy=False, mode="plan", rules=11,
                        model="claude-sonnet-5", writes=False)

    assert len(rows) <= MOST_ROWS
    for row in rows:
        assert len(row.title) <= ROW_TITLE, row.title
        assert len(row.note) <= 72, row.note


def test_a_page_of_a_long_list_leaves_room_for_its_arrows():
    items = [ui.Row(f"skill:{n}", f"skill-{n}", "") for n in range(40)]
    middle = ui.page("skill", items, page_number=2)

    assert len(middle) <= MOST_ROWS
    labels = [row.title for row in middle]
    assert any("Previous" in label for label in labels)
    assert any("Next" in label for label in labels)


def test_the_three_button_screens_really_are_three():
    for choices in (ui.mode_menu("plan"), ui.permission("r1")):
        assert len(choices) <= MOST_BUTTONS
        assert ui.fits_as_buttons(choices), choices


def test_a_busy_menu_offers_stopping_and_nothing_else():
    """There is no room to keep a control around greyed out."""
    rows = ui.main_menu(busy=True, mode="act")

    assert [row.key for row in rows] == ["stop"]


# --------------------------------------------------------------------------- #
# the webhook
# --------------------------------------------------------------------------- #


def signed(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_an_unsigned_delivery_is_not_from_meta():
    body = b'{"entry":[]}'
    assert wh.signature_ok(body, "", SECRET) is False
    assert wh.signature_ok(body, signed(body), SECRET) is True


def test_a_delivery_signed_with_the_wrong_secret_is_refused():
    body = b'{"entry":[]}'
    assert wh.signature_ok(body, signed(body, "someone-elses"), SECRET) is False


def test_without_a_secret_nothing_verifies():
    """A check that passes because nothing was configured is worse than no
    check, because it looks like one."""
    body = b'{"entry":[]}'
    assert wh.signature_ok(body, signed(body), "") is False


def test_the_signature_covers_the_exact_bytes():
    """It has to be checked before the JSON is parsed and against what was
    sent — one different space and a genuine payload fails."""
    body = json.dumps({"a": 1}).encode()
    respaced = json.dumps({"a": 1}, indent=2).encode()

    assert wh.signature_ok(body, signed(body), SECRET) is True
    assert wh.signature_ok(respaced, signed(body), SECRET) is False


def test_a_text_message_is_flattened_out_of_metas_nesting():
    payload = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "15550001111", "profile": {"name": "Reza"}}],
        "messages": [{"from": "15550001111", "id": "wamid.A",
                      "timestamp": "1749416383", "type": "text",
                      "text": {"body": "why is the build failing?"}}]},
        "field": "messages"}]}]}

    found = wh.read(payload)
    assert len(found) == 1
    assert found[0].wa_id == "15550001111"
    assert found[0].text == "why is the build failing?"
    assert found[0].name == "Reza"
    assert found[0].tapped is False


def test_a_tapped_button_arrives_as_an_action():
    for shape in ("button_reply", "list_reply"):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "1555", "id": "wamid.B", "type": "interactive",
                          "interactive": {"type": shape,
                                          shape: {"id": "status",
                                                  "title": "Status"}}}]},
            "field": "messages"}]}]}
        found = wh.read(payload)
        assert found[0].action == "status"
        assert found[0].tapped is True


def test_a_delivery_receipt_is_not_a_message():
    """Meta posts sent/delivered/read through the same endpoint. Treating one
    as the other answers somebody's read receipt with an agent turn."""
    payload = {"entry": [{"changes": [{"value": {
        "statuses": [{"id": "wamid.C", "status": "delivered",
                      "recipient_id": "1555"}]}, "field": "messages"}]}]}

    assert wh.read(payload) == []


def test_a_photo_is_named_rather_than_dropped():
    """Silence from a bot is indistinguishable from a bot that is off."""
    payload = {"entry": [{"changes": [{"value": {
        "messages": [{"from": "1555", "id": "wamid.D", "type": "image",
                      "image": {"id": "x"}}]}, "field": "messages"}]}]}

    found = wh.read(payload)
    assert found[0].action == "unsupported:image"


def test_a_verify_token_is_generated_not_chosen():
    """It is a shared secret, and people choose badly."""
    first, second = wh.make_verify_token(), wh.make_verify_token()

    assert first != second
    assert len(first) >= 24


def test_a_redelivered_message_does_not_become_a_second_turn():
    """Meta re-sends anything it did not get a 200 for."""
    endpoint = wh.Endpoint(verify_token="v", app_secret=SECRET)

    assert endpoint.fresh("wamid.A") is True
    assert endpoint.fresh("wamid.A") is False
    assert endpoint.fresh("wamid.B") is True


# --------------------------------------------------------------------------- #
# who it answers
# --------------------------------------------------------------------------- #


def test_the_same_number_written_three_ways_is_one_person(config):
    """It reaches us as +9715…, 009715… and 9715… depending on where it came
    from, and three spellings is three people to a naive comparison."""
    config.whatsapp.allowed = ["+1 (555) 000-1111"]

    for spelling in ("15550001111", "+15550001111", "0015550001111",
                     "+1 555 000 1111"):
        assert config.whatsapp.may(spelling), spelling


def test_a_stranger_is_not_on_the_list(config):
    assert config.whatsapp.may("15559998888") is False
    assert config.whatsapp.may("") is False


def test_a_project_may_not_add_itself_to_the_list():
    """A repository that could would be a backdoor, and nothing on screen
    would ever show it happening."""
    from comodor.config import project_filtered

    kept, refused = project_filtered({
        "whatsapp": {"allowed": ["15559998888"], "allow_writes": True}})

    assert "whatsapp" not in kept
    assert "whatsapp" in refused


# --------------------------------------------------------------------------- #
# no dead buttons
#
# In the Telegram bot three menu rows were drawn with no handler behind them,
# and tapping produced nothing at all — no message, no error. The same walk
# runs here, before anybody meets it.
# --------------------------------------------------------------------------- #


class Recorder:
    """Meta, remembered rather than called."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def me(self):
        return {"display_phone_number": "+1 555 000 2222",
                "verified_name": "Comodor"}

    def mark_read(self, message_id): pass

    def send(self, to, text, preview=False):
        self.sent.append({"to": to, "text": text, "rows": [], "buttons": []})
        return {"messages": [{"id": "wamid.out"}]}

    def send_buttons(self, to, text, buttons, footer=""):
        self.sent.append({"to": to, "text": text, "rows": [],
                          "buttons": list(buttons)})
        return {"messages": [{"id": "wamid.out"}]}

    def send_list(self, to, text, open_label, rows, header="", footer="",
                  section=""):
        self.sent.append({"to": to, "text": text, "rows": list(rows),
                          "buttons": []})
        return {"messages": [{"id": "wamid.out"}]}


class Pretend:
    """A session that answers without a model or a network."""

    cursor = 0

    def __init__(self, cfg):
        self.config = cfg

    def state(self):
        return {"busy": False, "mode": "plan", "provider": "openai",
                "model": "gpt-4o", "project": "/w",
                "context": {"used": 10, "limit": 100},
                "usage": {"cost": 0.5}}

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
        return {"skills": [{"id": f"skill-{n}", "installed": n == 0,
                            "description": "does a thing"}
                           for n in range(9)], "error": ""}

    def skill(self, action, name):
        return True, f"{name} {action}ed"

    def rules(self):
        return {"rules": [{"statement": "Use double quotes."}], "active": 1}

    def folder(self):
        return {"current": "/w", "confined": True}

    def set_mode(self, mode): return True
    def interrupt(self): pass
    def close(self): pass


@pytest.fixture
def talking(config, monkeypatch):
    from comodor.whatsapp.bot import Service

    monkeypatch.setattr("comodor.web.session.Session", Pretend)
    return Service(config, cloud=Recorder(),
                   endpoint=wh.Endpoint(verify_token="v", app_secret=SECRET),
                   announce=lambda line: None)


def keys(sent: dict[str, Any]) -> list[str]:
    return ([row[0] for row in sent["rows"]]
            + [key for key, _ in sent["buttons"]])


def arriving(text: str = "", action: str = "") -> wh.Inbound:
    return wh.Inbound(wa_id="15550001111", message_id=f"wamid.{text}{action}",
                      text=text, action=action)


def test_a_stranger_is_met_with_silence(talking):
    """A stranger who gets an answer of any kind has learned that this number
    is a Comodor and that there is a list worth getting onto."""
    talking._handle(wh.Inbound(wa_id="15559998888", message_id="w1",
                               text="hello"))
    talking._handle(wh.Inbound(wa_id="15559998888", message_id="w2",
                               text="/start"))

    assert talking.cloud.sent == []


def test_every_button_does_something(talking):
    talking._handle(arriving(text="/start"))
    first = talking.cloud.sent[-1]

    assert len(keys(first)) >= 8, "the first screen should offer the settings"

    skip = {"stop", "new", "ok", "okall", "no", "q", "qw", "qs"}
    seen: set[str] = set()
    queue = list(keys(first))
    dead: list[str] = []

    while queue:
        action = queue.pop(0)
        if action in seen or action.split(":")[0] in skip:
            continue
        seen.add(action)
        before = len(talking.cloud.sent)
        talking._handle(arriving(action=action))
        replies = talking.cloud.sent[before:]
        if not replies:
            dead.append(action)
            continue
        queue.extend(keys(replies[-1]))

    assert dead == [], f"buttons with nothing behind them: {dead}"
    assert len(seen) > 15, "the walk should reach past the first screen"


def test_every_message_it_sends_is_within_metas_limits(talking):
    """One over-long label and Meta rejects the whole message, which arrives
    as a bot that answers nothing."""
    talking._handle(arriving(text="/start"))
    for action in ("models", "skills", "chats", "mode", "rules", "folder",
                   "help", "status", "writes"):
        talking._handle(arriving(action=action))

    for sent in talking.cloud.sent:
        assert len(sent["rows"]) <= MOST_ROWS
        assert len(sent["buttons"]) <= MOST_BUTTONS
        for _, title, note in sent["rows"]:
            assert len(title) <= ROW_TITLE, title
            assert len(note) <= 72, note
        for _, label in sent["buttons"]:
            assert len(label) <= BUTTON_TITLE, label


def test_a_stale_row_says_so_rather_than_guessing(talking):
    talking._handle(arriving(text="/start"))
    talking._handle(arriving(action="model:99"))

    assert "moved on" in talking.cloud.sent[-1]["text"]


def test_the_phone_cannot_widen_its_own_permissions(talking):
    talking._handle(arriving(text="/start"))
    talking._handle(arriving(action="mode:act"))

    said = " ".join(s["text"] for s in talking.cloud.sent)
    assert "comodor whatsapp writes on" in said
    assert "reads and plans only" in said.lower()


def test_a_photo_is_answered_rather_than_ignored(talking):
    talking._handle(arriving(action="unsupported:image"))

    assert "only read text" in talking.cloud.sent[-1]["text"]


def test_the_welcome_says_what_it_is_pointed_at(talking):
    talking._handle(arriving(text="/start"))
    said = talking.cloud.sent[-1]["text"]

    assert "*Model*" in said
    assert "*Folder*" in said


# --------------------------------------------------------------------------- #
# the guided connect
#
# Eight things done in a browser and a terminal, in order, where getting one
# wrong fails somewhere else entirely — a phone number pasted where the number
# id goes fails at the first send with "Unsupported post request".
# --------------------------------------------------------------------------- #


def a_wizard(config, answers: list[str], monkeypatch, *, tunnel: bool = False):
    """Run the guide with Meta and the tunnel stood in for."""
    import io

    from rich.console import Console

    from comodor.ui import console as console_module
    from comodor.whatsapp import api as wapi
    from comodor.whatsapp import guide
    from comodor.whatsapp import tunnel as tunnel_mod

    class FakeCloud:
        def __init__(self, token, number_id, version="v21.0", timeout=20.0):
            if token != "EAA-good-token":
                raise wapi.Unauthorised("Session expired")

        def me(self):
            return {"display_phone_number": "+1 555 000 2222"}

    class FakeTunnel:
        url = "https://kind-words-99.trycloudflare.com"

        def webhook(self, path):
            return self.url + path

        def stop(self):
            pass

    monkeypatch.setattr(guide, "Cloud", FakeCloud)
    monkeypatch.setattr(guide, "VERIFY_PATIENCE", 0.4)
    if tunnel:
        monkeypatch.setattr(tunnel_mod, "find_binary", lambda: "cloudflared")
        monkeypatch.setattr(tunnel_mod, "start_quick",
                            lambda port, host="127.0.0.1": (FakeTunnel(), ""))
    else:
        monkeypatch.setattr(tunnel_mod, "find_binary", lambda: None)

    console = Console(width=88, force_terminal=False, no_color=True,
                      file=io.StringIO())
    theme = console_module.prepare_theme("ember", False, no_color=True)
    replies = iter(answers)
    code = guide.walk(console, theme, config,
                      ask=lambda message: next(replies, ""),
                      save=lambda cfg: None)
    return code, console.file.getvalue()


def test_the_phone_number_is_refused_where_the_id_belongs(config, monkeypatch):
    """The single most common mistake, and it otherwise fails much later with
    an error that does not mention it."""
    _, said = a_wizard(config, ["", "+1 555 000 2222", ""], monkeypatch)

    assert "looks like the phone number" in said


def test_a_token_meta_refuses_is_caught_at_the_time(config, monkeypatch):
    """Not days later, when the temporary one quietly expires."""
    _, said = a_wizard(
        config, ["", "123456789012345", "EAA-wrong", ""], monkeypatch)

    assert "refused it" in said.lower()


def test_a_good_token_is_confirmed_against_meta(config, monkeypatch):
    _, said = a_wizard(
        config,
        ["", "123456789012345", "EAA-good-token", ""], monkeypatch)

    assert "Works." in said
    assert "+1 555 000 2222" in said


def test_something_that_is_not_an_app_secret_is_refused(config, monkeypatch):
    _, said = a_wizard(
        config,
        ["", "123456789012345", "EAA-good-token", "nope", ""], monkeypatch)

    assert "does not look like an app secret" in said


def test_it_will_not_finish_without_a_secret(config, monkeypatch):
    """Without one nothing verifies, and that is not a state to leave somebody
    in quietly."""
    config.whatsapp.app_secret = ""
    code, said = a_wizard(
        config, ["", "123456789012345", "EAA-good-token", ""], monkeypatch)

    assert code == 1
    assert "nothing can be verified" in said.lower()


def test_the_tunnel_is_started_and_its_address_used(config, monkeypatch):
    good = ["", "123456789012345", "EAA-good-token",
            "0a1b2c3d4e5f60718293a4b5c6d7e8f9"]
    _, said = a_wizard(config, good, monkeypatch, tunnel=True)

    assert "tunnel up" in said
    assert "kind-words-99.trycloudflare.com/whatsapp" in said
    assert config.whatsapp.public_url.endswith("/whatsapp")


def test_a_quick_tunnel_is_said_to_be_temporary(config, monkeypatch):
    """It gets a new hostname every start, and Meta keeps delivering to the
    old one — a bot that works until the first reboot."""
    good = ["", "123456789012345", "EAA-good-token",
            "0a1b2c3d4e5f60718293a4b5c6d7e8f9"]
    _, said = a_wizard(config, good, monkeypatch, tunnel=True)

    assert "temporary" in said
    assert "named tunnel" in said


def test_without_cloudflare_it_asks_for_an_address_rather_than_stopping(
        config, monkeypatch):
    good = ["", "123456789012345", "EAA-good-token",
            "0a1b2c3d4e5f60718293a4b5c6d7e8f9", "https://mine.example/whatsapp"]
    _, said = a_wizard(config, good, monkeypatch)

    assert "not installed" in said
    assert config.whatsapp.public_url == "https://mine.example/whatsapp"


def test_a_verify_token_is_made_if_there_is_not_one(config, monkeypatch):
    config.whatsapp.verify_token = ""
    good = ["", "123456789012345", "EAA-good-token",
            "0a1b2c3d4e5f60718293a4b5c6d7e8f9", "https://mine.example/whatsapp"]
    a_wizard(config, good, monkeypatch)

    assert len(config.whatsapp.verify_token) >= 24
