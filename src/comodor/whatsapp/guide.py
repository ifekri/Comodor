"""`comodor whatsapp connect`, walked through rather than documented.

WhatsApp needs eight things done in a browser and a terminal, in order, and
getting any one of them wrong produces a failure somewhere else entirely: a
phone *number* pasted where the number *id* goes fails at the first send with
"Unsupported post request"; a token from the dashboard works today and stops
tomorrow; an app secret that never got saved makes every webhook unverified,
which looks exactly like a bot nobody is talking to.

So each value is taken one at a time and checked the moment it arrives — the
token against Meta, the id for being an id, the secret for being a secret — and
the two hard parts are done for you: the tunnel is started here, and Meta's
verification callback is *waited for* rather than assumed, so the step ends
when Meta has actually reached the endpoint and not when somebody has pressed
enter.

The wizard is the whole of `connect` when it is given no arguments. With them
it is the one-line form, which is what a second machine or a script wants.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from rich.panel import Panel
from rich.text import Text

from ..config import Config
from .api import Cloud, Unauthorised, WhatsAppError
from .webhook import Endpoint, make_verify_token

#: How long to wait for Meta to call the webhook back after somebody saves it.
#: Meta calls within a second or two; a minute allows for reading the screen.
VERIFY_PATIENCE = 180.0

APPS = "https://developers.facebook.com/apps"


@dataclass
class Step:
    """One thing to do, and where."""

    title: str
    body: str


def _panel(console, theme, title: str, body: str) -> None:
    console.print(Panel(Text.from_markup(body),
                        title=Text(f" {title} ",
                                   style=theme.style("title")),
                        title_align="left", box=theme.box,
                        border_style=theme.style("border"), padding=(1, 2)))


def walk(console, theme, config: Config,
         ask: Callable[[str], str],
         save: Callable[[Config], None]) -> int:
    """The whole of it, one step at a time. Returns an exit code."""
    settings = config.whatsapp

    # -- 1. the app ------------------------------------------------------- #
    console.print()
    _panel(console, theme, "1 of 5 — a Meta app",
           f"Open [bold]{APPS}[/bold] and:\n\n"
           "  • [bold]Create app[/bold] → type [bold]Business[/bold]\n"
           "  • inside it, [bold]Add product[/bold] → [bold]WhatsApp[/bold] "
           "→ Set up\n\n"
           "Meta then makes you a [bold]test business number[/bold] and a test "
           "account\nautomatically. No real number, no card, no business "
           "verification —\nthe test number messages up to five people, which "
           "is four more than\nyou need.\n\n"
           "[dim]On that page you will see 'Phone number ID' and a temporary "
           "token.[/dim]")
    if ask("press enter when the WhatsApp product is added") is None:
        return 130

    # -- 2. the number id -------------------------------------------------- #
    console.print()
    _panel(console, theme, "2 of 5 — the phone number id",
           "On [bold]WhatsApp → API Setup[/bold], copy [bold]Phone number ID"
           "[/bold].\n\n"
           "[dim]It is a long number under 'From'. Not the phone number "
           "itself —\nthat is the single most common mistake here, and it "
           "fails later\nwith an error that does not mention it.[/dim]")
    number_id = ""
    while True:
        number_id = (ask("phone number id") or "").strip()
        if not number_id:
            console.print("  [dim]Nothing entered — stopping here. Run "
                          "`comodor whatsapp connect` again when ready.[/dim]\n")
            return 1
        if number_id.isdigit() and len(number_id) >= 10:
            break
        bare = number_id.replace("+", "").replace(" ", "").replace("-", "")
        if number_id.lstrip("+").replace(" ", "").replace("-", "").isdigit() \
                and 7 <= len(bare) <= 15 and not number_id.isdigit():
            # Written the way a phone number is written — spaces, dashes, a
            # leading plus — which is the mistake worth naming, because it
            # otherwise fails much later with an error about a "post request".
            console.print("  [red]That looks like the phone number.[/red] "
                          "The id is the long number beside it.")
        elif not bare.isdigit():
            console.print("  [red]An id is digits only.[/red]")
        else:
            console.print(f"  [red]Too short for an id[/red] [dim]({len(bare)} "
                          f"digits; they are fifteen or so).[/dim]")

    # -- 3. the token ------------------------------------------------------ #
    console.print()
    _panel(console, theme, "3 of 5 — an access token",
           "The token on the API Setup page works, and [bold]expires in "
           "twenty-four\nhours[/bold] — fine for trying this out, and it will "
           "look like a bug tomorrow.\n\n"
           "For one that does not expire:\n"
           "  • [bold]business.facebook.com[/bold] → Business settings → "
           "[bold]System users[/bold]\n"
           "  • add one, [bold]Generate token[/bold], pick your app\n"
           "  • tick [bold]whatsapp_business_messaging[/bold] and "
           "[bold]whatsapp_business_management[/bold]\n\n"
           "[dim]Either will do now; you can paste a permanent one later with"
           "\n`comodor whatsapp connect --token …`.[/dim]")

    token = ""
    while True:
        token = (ask("access token") or "").strip()
        if not token:
            console.print("  [dim]Stopping here.[/dim]\n")
            return 1
        console.print("  [dim]checking it with Meta…[/dim]")
        try:
            me = Cloud(token, number_id,
                       version=settings.api_version).me()
        except Unauthorised as problem:
            console.print(f"  [red]Meta refused it.[/red] {problem}")
            continue
        except WhatsAppError as problem:
            console.print(f"  [red]{problem}[/red]")
            continue
        shown = me.get("display_phone_number") or number_id
        named = me.get("verified_name") or ""
        console.print(f"  [green]Works.[/green] {shown}"
                      + (f" ([dim]{named}[/dim])" if named else ""))
        break

    # -- 4. the app secret -------------------------------------------------- #
    console.print()
    _panel(console, theme, "4 of 5 — the app secret",
           "In the same app: [bold]Settings → Basic[/bold], then [bold]Show"
           "[/bold] beside App secret.\n\n"
           "[dim]Every webhook Meta sends is signed with it, and Comodor "
           "refuses any\ndelivery it cannot verify. Without one, anything that "
           "reaches the\nendpoint could hand the agent instructions with your "
           "number on them.[/dim]")
    secret = ""
    while True:
        secret = (ask("app secret") or "").strip()
        if not secret:
            console.print("  [red]Without this nothing can be verified.[/red] "
                          "[dim]Stopping here.[/dim]\n")
            return 1
        if len(secret) >= 24 and all(c in "0123456789abcdefABCDEF"
                                     for c in secret):
            break
        console.print("  [red]That does not look like an app secret[/red] "
                      "[dim](32 hex characters).[/dim]")

    settings.token = token
    settings.phone_number_id = number_id
    settings.app_secret = secret
    if not settings.verify_token:
        settings.verify_token = make_verify_token()
    settings.enabled = True
    save(config)
    console.print("  [dim]saved[/dim]")

    # -- 5. somewhere for Meta to deliver to -------------------------------- #
    return _webhook_step(console, theme, config, ask, save)


def _webhook_step(console, theme, config: Config,
                  ask: Callable[[str], str],
                  save: Callable[[Config], None]) -> int:
    """The hard one: a public HTTPS address, and Meta actually reaching it."""
    from . import tunnel as tunnel_mod

    settings = config.whatsapp
    console.print()
    _panel(console, theme, "5 of 5 — where Meta delivers",
           "Meta posts each message to a URL, so something has to be "
           "reachable from\nthe internet over HTTPS. Comodor listens on "
           f"[bold]{settings.host}:{settings.port}[/bold];\nthe usual answer "
           "is a Cloudflare tunnel, which needs no open port and\nno domain.")

    started: Any = None
    where = settings.public_url

    binary = tunnel_mod.find_binary()
    if binary is None:
        console.print(f"  [dim]cloudflared is not installed — "
                      f"{tunnel_mod.how_to_install()}[/dim]")
        console.print("  [dim]Or use any address that already reaches this "
                      "machine over HTTPS.[/dim]")
        where = (ask(f"public https address for {settings.path}")
                 or "").strip()
        if not where:
            return _unfinished(console, config, save)
    else:
        console.print(f"  [dim]cloudflared: {binary}[/dim]")
        console.print("  [dim]starting a tunnel…[/dim]")
        started, why = tunnel_mod.start_quick(settings.port, settings.host)
        if started is None:
            console.print(f"  [red]{why}[/red]")
            where = (ask(f"public https address for {settings.path}")
                     or "").strip()
            if not where:
                return _unfinished(console, config, save)
        else:
            where = started.webhook(settings.path)
            console.print(f"  [green]tunnel up[/green]  {where}")
            console.print(Text(
                "  This address is temporary — a quick tunnel gets a new one "
                "every time it\n  starts, so Meta would have to be told again "
                "after a restart. For a bot\n  meant to keep running, make a "
                "named tunnel once:",
                style=theme.style("dim")))
            console.print(Text(
                "    cloudflared tunnel login && cloudflared tunnel create "
                "comodor",
                style=theme.style("accent")))

    settings.public_url = where
    save(config)

    console.print()
    _panel(console, theme, "Paste these into Meta",
           "[bold]WhatsApp → Configuration[/bold], the [bold]Edit[/bold] "
           "button beside Webhook:\n\n"
           f"  [dim]Callback URL[/dim]\n  [bold]{where}[/bold]\n\n"
           f"  [dim]Verify token[/dim]\n  [bold]{settings.verify_token}"
           "[/bold]\n\n"
           "Save it, then [bold]Manage[/bold] and tick [bold]messages[/bold].")

    # The endpoint is stood up here so Meta's verification has something to
    # reach: waiting for a callback that nothing is listening for would be a
    # wizard that hangs, blaming the user for its own gap.
    heard: list[str] = []
    endpoint = Endpoint(verify_token=settings.verify_token,
                        app_secret=settings.app_secret,
                        path=settings.path, host=settings.host,
                        port=settings.port,
                        announce=lambda line: heard.append(line))
    try:
        endpoint.start()
    except OSError as problem:
        console.print(f"\n  [red]Could not listen on {settings.host}:"
                      f"{settings.port}: {problem}[/red]")
        console.print("  [dim]Something else may be using that port; change "
                      "it with `whatsapp.port` in your config.[/dim]\n")
        if started is not None:
            started.stop()
        return 1

    console.print()
    console.print(Text("  waiting for Meta to call it back…",
                       style=theme.style("dim")))

    ok = _wait_for_meta(heard)
    endpoint.stop()
    if started is not None:
        started.stop()

    console.print()
    if not ok:
        console.print(Text(
            "  Meta has not called it yet.", style=theme.style("bad")))
        console.print(Text(
            "  Everything is saved. `comodor whatsapp webhook` shows the two "
            "values\n  again, and `comodor whatsapp start` will answer the "
            "check whenever it comes.",
            style=theme.style("dim")))
        console.print()
        return 0

    console.print(Text(f"  {theme.glyphs.check} Meta reached the webhook.",
                       style=theme.style("good")))
    console.print(Text(
        "\n  One thing left — say who may talk to it:",
        style=theme.style("dim")))
    console.print(Text("    comodor whatsapp pair",
                       style=theme.style("accent")))
    console.print(Text(
        "  then                     comodor whatsapp start --background",
        style=theme.style("dim")))
    console.print()
    return 0


def _wait_for_meta(heard: list[str], patience: float | None = None) -> bool:
    """Whether the verification handshake actually arrived.

    The default is read here rather than bound as a parameter default: bound,
    it is captured when this module is imported, and nothing that changes
    `VERIFY_PATIENCE` afterwards — a test, a setting — has any effect at all.
    """
    if patience is None:
        patience = VERIFY_PATIENCE
    deadline = time.time() + patience
    while time.time() < deadline:
        if any("verified by Meta" in line for line in heard):
            return True
        time.sleep(0.5)
    return False


def _unfinished(console, config: Config,
                save: Callable[[Config], None]) -> int:
    save(config)
    console.print("\n  [dim]Saved what there was. `comodor whatsapp webhook` "
                  "when you have an address.[/dim]\n")
    return 0
