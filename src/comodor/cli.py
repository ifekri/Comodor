"""Command line entry point.

Three ways in:

* ``comodor`` — the full interface.
* ``comodor run "<task>"`` — one task, no interface, output to stdout or JSON.
  This is the mode CI and scripts use; it needs explicit ``--yes`` before it
  will change anything, because there is nobody there to approve a prompt.
* ``comodor setup`` — the first-run questions again, on demand.
* ``comodor doctor`` — what is configured, what is reachable, what the terminal
  can do. The first thing to run when something is not working.
* ``comodor skills`` — browse the library, and fetch the ones you want.
* ``comodor update`` — move to the newest published version, using whichever
  of uv, pipx or pip put this copy here.
* ``comodor uninstall`` — takes every file, folder and PATH line back off the
  machine, after showing you the list.

There is no configuration file to write by hand. The first run asks a handful
of questions and saves the answers to ``~/.comodor/config.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .config import load as load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comodor",
        description="Comodor — a terminal coding agent that learns as it works.",
        # argparse's own help is a list of flags. That answers "what arguments
        # does this take" and not "what is this, and what do I do now", which
        # is what somebody typing --help is asking. See `help.py`. Only the top
        # level is taken over: for one subcommand, the list of its flags really
        # is the answer.
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", dest="want_help",
                        help="this page, or `comodor help <topic>` for one part")
    parser.add_argument("--version", action="version", version=f"comodor {__version__}")

    parser.add_argument("--provider", help="provider to use (openrouter, anthropic, …)")
    parser.add_argument("--profile", help="run against a named profile — its own "
                        "brain, sessions and config under profiles/NAME")
    parser.add_argument("--model", help="model id")
    parser.add_argument("--mode", choices=("act", "plan", "ask", "chat"),
                        help="starting mode")
    parser.add_argument("--no-loop", action="store_true",
                        help="answer once instead of iterating autonomously")
    parser.add_argument("--theme", help="colour theme for what the commands print "
                                        "(ember, midnight, matrix, mono); the "
                                        "interface has its own")
    parser.add_argument("--ascii", action="store_true",
                        help="ASCII borders in what the commands print, for "
                             "terminals without box-drawing glyphs")
    parser.add_argument("--cwd", help="workspace directory (default: the project root)")
    parser.add_argument("--demo", action="store_true",
                        help="run the interface against a scripted offline provider")
    parser.add_argument("--resume", nargs="?", const="__pick__",
                        help="reopen the most recent session, or one by id")

    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run one task without the interface")
    run.add_argument("task", nargs="?", default="",
                     help="what to do (optional with --decision-answers)")
    run.add_argument("--json", action="store_true", help="emit a JSON result")
    run.add_argument("--yes", action="store_true",
                     help="approve file writes and commands automatically")
    run.add_argument("--max-steps", type=int, help="override the step limit")
    run.add_argument(
        "--interactions", default="",
        help="JSON list of what to do with each question form, one entry per "
             "form, in order: {\"action\": \"answer\", \"value\": ...} for a "
             "form of one question, {\"action\": \"answer\", \"values\": "
             "{header: answer}} for any form, or \"cancel\", \"expire\", "
             "\"unattended\". An answer must state its choice; nothing is "
             "chosen for you. A script of more than one entry names each "
             "entry's headers (\"values\", or \"headers\" for the other "
             "actions). A script that does not fit fails with exit 1. "
             "Nothing is scripted without it.")
    run.add_argument(
        "--decision-answers", default=None, metavar="PATH",
        help="answer decisions an earlier run stopped for: a JSON list of "
             "{\"decision_ref\", \"chosen\", \"written\"} objects, from PATH or "
             "from stdin with -. The refs alone find the stopped run; it must "
             "be resumed from the same workspace and in the same mode.")

    written = sub.add_parser(
        "help", help="what this is and how to use it, in full")
    written.add_argument("topic", nargs="?", default="",
                         help="one part of it, in more detail")

    sub.add_parser("setup", help="choose a provider and model, and save the answers")
    brought = sub.add_parser(
        "import", help="bring keys, model and skills over from another agent")
    brought.add_argument("--dry-run", action="store_true",
                         help="say what would come over, and change nothing")
    brought.add_argument("--keys-only", action="store_true",
                         help="leave the skills and the model where they are")
    doctor = sub.add_parser(
        "doctor", help="check everything, and repair what can be repaired")
    doctor.add_argument("--fix", action="store_true",
                        help="apply every repair the check found")

    upgrade = sub.add_parser(
        "update", help="upgrade to the newest published version")
    upgrade.add_argument("--check", action="store_true",
                         help="say what is available and change nothing")

    remove = sub.add_parser(
        "uninstall",
        help="remove Comodor and everything it has written, completely")
    remove.add_argument("--dry-run", action="store_true",
                        help="list what would go, and remove nothing")
    remove.add_argument("--yes", action="store_true",
                        help="do not ask; for scripts")

    insights = sub.add_parser(
        "insights", help="spend, activity and progress over recent days")
    insights.add_argument("--days", type=int, default=30,
                          help="how far back to look (default 30)")
    insights.add_argument("--json", action="store_true",
                          help="emit the numbers as JSON, for scripts")

    approvals = sub.add_parser(
        "approvals",
        help="propose an allowlist from the commands you keep approving")
    approvals.add_argument(
        "--apply", metavar="STEM", nargs="*", default=None,
        help="add the named stems (or every proposal with no names) to "
             "safety.allow_commands and save")


    from .acp.commands import register as register_acp
    from .cron.commands import register as register_cron
    from .discord.commands import register as register_discord
    from .github.commands import register as register_github
    from .learning.commands import register as register_curator
    from .learning.journey_commands import register as register_journey
    from .learning.providers.commands import register as register_memory_provider
    from .local.commands import register as register_local
    from .mcp.commands import register as register_mcp
    from .plugins.commands import register as register_plugins
    from .skills.commands import register as register_skills
    from .slack.commands import register as register_slack
    from .telegram.commands import register as register_telegram
    from .transport.commands import register as register_core
    from .web.commands import register as register_web
    from .webhook.commands import register as register_webhook
    from .whatsapp.commands import register as register_whatsapp

    register_mcp(sub)
    register_local(sub)
    register_cron(sub)
    register_curator(sub)
    register_telegram(sub)
    register_whatsapp(sub)
    register_slack(sub)
    register_discord(sub)
    register_github(sub)
    register_skills(sub)
    register_web(sub)
    register_webhook(sub)
    register_acp(sub)
    register_core(sub)
    register_memory_provider(sub)
    register_journey(sub)
    register_plugins(sub)

    serve = sub.add_parser(
        "serve", help="speak the OpenAI chat protocol, so other frontends "
                      "can drive the agent")
    serve.add_argument("--host", help="address to bind (default: the loopback, "
                                      "or api.bind in your config)")
    serve.add_argument("--port", type=int, help="port to listen on (default 8787)")
    serve.add_argument("--token", help="the access token; one is generated and "
                                       "printed when this is not given")

    return parser


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    if args.provider:
        config.provider = args.provider
        entry = config.providers.get(args.provider)
        if entry and not args.model:
            config.model = entry.model
    if args.model:
        config.model = args.model
    if args.mode:
        config.agent.mode = args.mode
    if args.no_loop:
        config.agent.loop = False
    if args.theme:
        config.ui.theme = args.theme
    if args.ascii:
        config.ui.ascii_borders = True
    return config


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #


def _greet_on_stderr(config: Config, memory: Any, skills: Any) -> None:
    """The wordmark, on the error stream with the progress.

    Same reason the progress is there: `comodor run … | jq` has to see the
    answer and nothing else, and a logo in the middle of a JSON document is
    somebody else's afternoon.
    """
    from rich.console import Console

    from .terminal import banner
    from .terminal import console as console_module

    theme = console_module.prepare_theme(config.ui.theme, config.ui.ascii_borders,
                                         no_color=False)
    errors = Console(stderr=True, theme=theme.rich_theme())
    banner.show(errors, theme, config,
                version=_release(), model=config.active_model(),
                project=str(config.paths.project),
                standing=banner.gather(memory, skills))


def _release() -> str:
    from . import __version__

    return __version__


def _load_plugins(config: Config, bus: Any) -> Any:
    """Discover and load the plugins, and wire their hooks to the bus.

    Kept in one place so every entry point — terminal, web, phone — gets
    the same plugins with the same rules. A hook callback that raises is
    its author's bug, but it must not break the event it was listening to,
    so each call is wrapped here rather than trusted.
    """
    try:
        from .plugins import load_for

        manager = load_for(config)
    except Exception:
        return None

    manager.load_all()

    def dispatch(event: Any) -> None:
        for _, callback in manager.hook_callbacks(event.kind.value):
            try:
                callback(event)
            except Exception:
                pass                       # a broken hook is not a broken turn

    # One subscription total, whatever the plugins registered; dispatch
    # filters by kind, and a bus event without listeners of its own is a
    # dictionary miss away.
    if any(state.ok and state.context and state.context.hooks
           for state in manager.states.values()):
        bus.subscribe(dispatch)
    return manager


#: What a scripted entry may do to a form — what a person could do to it.
_ACTIONS = ("answer", "cancel", "expire", "unattended")


class ScriptError(ValueError):
    """A scripted interaction the run cannot use, said plainly (D19)."""


def _scripted_interactions(raw: Any) -> list[dict[str, Any]]:
    """The caller's scripted entries, checked whole. Empty when none were given.

    The contract is a JSON list, one entry per question form, in order. An
    entry is an action name (`"cancel"`, `"expire"`, `"unattended"`) or an
    object with an `action`; an `answer` states its choice as a `value` (a
    form of one question) or as `values` keyed by header. A script of more
    than one entry names each entry's headers, so an entry cannot drift onto
    a form it was not written for. Anything else is refused here, before the
    run starts and before any model call: invalid JSON, a list that is not a
    list, an unknown action, an answer with no choice in it (D19).

    A headless run with no script behaves exactly as it always has: every form
    is unattended.
    """
    if raw is None or raw == "" or raw == []:
        return []
    if isinstance(raw, (list, tuple)):
        parsed: Any = list(raw)
    else:
        try:
            parsed = json.loads(str(raw))
        except ValueError as problem:
            raise ScriptError(f"it is not valid JSON ({problem})") from None
        if not isinstance(parsed, list):
            raise ScriptError("it must be a JSON list, one entry per question form")
    several = len(parsed) > 1
    return [_entry(item, index, several) for index, item in enumerate(parsed, start=1)]


def _entry(item: Any, index: int, several: bool) -> dict[str, Any]:
    """One scripted entry, normalised, or the reason it cannot be used."""
    if isinstance(item, str):
        item = {"action": item}
    if not isinstance(item, dict):
        raise ScriptError(f"entry {index} is neither an action name nor an object")
    action = str(item.get("action", "")).strip().lower()
    if action not in _ACTIONS:
        raise ScriptError(f"entry {index} has the unknown action {item.get('action')!r}; "
                          f"use one of {', '.join(_ACTIONS)}")
    entry: dict[str, Any] = {"index": index, "action": action,
                             "value": "", "values": {}, "headers": []}
    value, values, headers = item.get("value"), item.get("values"), item.get("headers")
    if value is not None:
        if not isinstance(value, str) or not value.strip():
            raise ScriptError(f"entry {index} has an empty `value`")
        entry["value"] = value.strip()
    if values is not None:
        if not isinstance(values, dict) or not values:
            raise ScriptError(f"entry {index}: `values` must map each question header "
                              f"to its answer")
        for header, answer in values.items():
            if not isinstance(answer, str) or not answer.strip():
                raise ScriptError(f"entry {index}: the answer for {header!r} is empty")
        entry["values"] = {str(header): answer.strip() for header, answer in values.items()}
    if headers is not None:
        if not isinstance(headers, list) or not headers or not all(
                isinstance(header, str) and header.strip() for header in headers):
            raise ScriptError(f"entry {index}: `headers` must list the headers of the "
                              f"form it is for")
        entry["headers"] = [header.strip() for header in headers]
    if action == "answer":
        if not entry["value"] and not entry["values"]:
            raise ScriptError(
                f"entry {index} is an `answer` that states no choice; give a `value`, "
                f"or `values` keyed by header — no option is ever chosen for you")
        if entry["value"] and entry["values"]:
            raise ScriptError(f"entry {index} gives both `value` and `values`; give one")
        if entry["headers"]:
            raise ScriptError(f"entry {index}: an `answer` names its headers through "
                              f"`values`")
    elif entry["value"] or entry["values"]:
        raise ScriptError(f"entry {index}: `{action}` takes no answer")
    if several and not (entry["values"] or entry["headers"]):
        raise ScriptError(
            f"entry {index} names no headers; in a script of more than one entry "
            f"every entry names the headers of the form it is for (`values`, or "
            f"`headers`)")
    return entry


def _mismatch(entry: dict[str, Any], request: Any, forms: Any) -> str:
    """Why `entry` does not fit this form, or an empty string."""
    shown = [question.header for question in forms.decode(request.meta.get("questions") or [])]
    named = list(entry["values"]) or list(entry["headers"])
    unknown = [header for header in named if header not in shown]
    if unknown:
        return (f"entry {entry['index']} names {unknown[0]!r}, which is not on the form "
                f"that was raised (its headers: {', '.join(shown)})")
    if entry["action"] == "answer" and not entry["values"] and len(shown) != 1:
        return (f"entry {entry['index']} is an `answer` without headers, which fits only "
                f"a form of one question; the form raised has {len(shown)}")
    return ""


def _apply_interaction(request: Any, entry: dict[str, Any], forms: Any) -> None:
    """Do to a form what a person would have done. The tool does the rest.

    Every branch resolves the *request* the way its surface would, so the ask
    tool, the ledger and the loop produce the same lifecycle they do for a
    real answer, a real dismissal, a real expiry or a real absence.
    """
    action = entry["action"]
    if action == "cancel":
        request.answer(forms.CANCELLED)
    elif action == "expire":
        request.expire()
    elif action == "answer":
        request.answer(_answers_from_form(request, entry["value"], forms,
                                          values=entry["values"]))
    else:
        request.answer(forms.UNATTENDED)


def _answers_from_form(request: Any, value: str, forms: Any,
                       values: dict[str, str] | None = None) -> str:
    """A real answer document, built from the form the model actually raised.

    The question headers are the model's, so an answer binds to them by
    header rather than guess. It answers exactly what it names: `values`
    answers each question by its header, and a lone `value` answers the one
    question of a one-question form. A question it does not name stays
    unanswered — never filled with a first option, and never handed a value
    meant for another question (D19).
    """
    questions = forms.decode(request.meta.get("questions") or [])
    keyed = dict(values or {})
    if value and not keyed:
        if len(questions) != 1:
            raise ScriptError("an `answer` without headers fits only a form of one "
                              "question")
        keyed = {questions[0].header: value}
    answers = []
    for question in questions:
        offered = [option.label for option in question.options if not option.free]
        given = keyed.get(question.header, "")
        if given and given in offered:
            chosen, written = [given], ""
        elif given:
            chosen, written = [], given
        else:
            chosen, written = [], ""
        answers.append(forms.Answer(header=question.header,
                                    prompt=question.prompt,
                                    chosen=chosen, written=written))
    return forms.encode_answers(answers)


def _report_script_error(problem: str, as_json: bool,
                         clarification: dict[str, Any] | None = None) -> None:
    """A scripted interaction that did not fit: what failed, said once."""
    print(f"error: --interactions: {problem}", file=sys.stderr)
    if as_json:
        body: dict[str, Any] = {"text": "", "ok": False, "stopped": "error",
                                "error": {"kind": "interactions", "message": problem}}
        if clarification is not None:
            body["clarification"] = clarification
        print(json.dumps(body, ensure_ascii=False, indent=2))


def run_headless(config: Config, args: argparse.Namespace) -> int:
    """One task, no TUI. Used by scripts, hooks and CI."""
    # Before anything can be printed. A Windows console is cp1252 by default,
    # and `print` of an answer containing an arrow, an em dash or a word in any
    # non-Latin script raises UnicodeEncodeError — which kills the run after
    # the work is done and returns nothing to whatever called it. The
    # interactive path has always done this when it builds its console; the
    # headless path never builds one, so it never did.
    from .terminal.console import force_utf8

    force_utf8()

    from . import catalogue

    retired = catalogue.RETIRED.get(config.provider)
    if retired:
        # Never send a prompt (or reuse a stored key) for a provider Comodor
        # no longer supports. Say so and require an explicit replacement.
        print(f"Error: the {retired} provider is no longer supported. "
              f"Run `comodor setup` to choose a replacement provider.",
              file=sys.stderr)
        return 1

    from . import questions as forms
    from .application import assemble
    from .context_refs import Refusal, expand
    from .events import EventBus, Kind
    from .safety import Redactor

    answers = None
    source = getattr(args, "decision_answers", None)
    if source is not None:
        try:
            answers = (sys.stdin.read() if source == "-"
                       else Path(source).read_text(encoding="utf-8"))
        except OSError as problem:
            print(f"error: the decision answers could not be read: {problem}",
                  file=sys.stderr)
            return 1
    elif not args.task:
        print("error: `comodor run` needs a task, or --decision-answers to "
              "resume a run that stopped for a decision", file=sys.stderr)
        return 2

    # The script is checked whole before anything runs: a script that cannot
    # be used ends the run here, before any model call, rather than being
    # quietly treated as no script at all (D19).
    try:
        interactions = _scripted_interactions(getattr(args, "interactions", ""))
    except ScriptError as problem:
        _report_script_error(str(problem), args.json)
        return 1

    if args.yes:
        config.safety.auto_approve_writes = True
        config.safety.auto_approve_shell = True
    if args.max_steps:
        config.agent.max_steps = args.max_steps

    # One wiring, shared. This block used to live here in full and be mirrored
    # in the previous interface, `web/session.py`, `acp/agent.py` and
    # `cron/runner.py` —
    # the same objects in the same order, five times, so that adding a front
    # end meant a sixth copy and changing how a session is built meant finding
    # all of them. `application.assemble` is that block, moved rather than
    # rewritten. Headless runs still learn from corrections, because the
    # learning engine is still wired in there.
    bus = EventBus()
    built = assemble(config, bus=bus, plugins=_load_plugins(config, bus))
    memory, skills, agent = built.memory, built.skills, built.agent

    # Two things every headless run needs, whatever it prints.
    #
    # *Nobody is there to fill in a form.* `ask` publishes a request and waits
    # half an hour for an answer that cannot arrive, so one ambiguous task used
    # to wedge a script for thirty minutes and then carry on anyway. The tool
    # already handles an unanswered form well — it tells the model to choose
    # sensible defaults and say which it chose — so the answer is given at once
    # rather than after the timeout. Permission requests are left alone: they
    # have their own deadline and refusing by default is the right end of it.
    #
    # *What it reached for is part of the result.* A caller checking whether a
    # task was done properly wants to know that `ask` was called before the
    # first edit, or that nothing was ever read. The count was already
    # reported; the names cost nothing and are what makes it checkable.
    used: list[str] = []
    mismatched: list[str] = []

    def observe(event: Any) -> None:
        if event.kind is Kind.TOOL_START:
            used.append(str(event.get("name", "")))
        elif event.kind is Kind.REQUEST:
            request = event.get("request")
            if request is not None and request.kind == "questions":
                # Nobody is here. Unless the caller scripted what a person
                # would do — answer, cancel, expire — the decision is reported
                # as unattended and the run ends needing it, rather than
                # carrying on without it. The scripted paths drive the same
                # tool and lifecycle the interactive surfaces do.
                if mismatched or not interactions:
                    request.answer(forms.UNATTENDED)
                    return
                why = _mismatch(interactions[0], request, forms)
                if why:
                    # The entry was written for another form. The form is
                    # closed as nobody-answered — never as a cancellation the
                    # person did not make — and nothing is applied to it; the
                    # run ends reporting the script error (D19).
                    mismatched.append(why)
                    request.answer(forms.UNATTENDED)
                    return
                _apply_interaction(request, interactions.pop(0), forms)

    bus.subscribe(observe)

    if not args.json:
        _greet_on_stderr(config, memory, skills)
        for note in config.complaints:
            print(f"config: {note}", file=sys.stderr)
        if config.project_refused:
            print(f"config: this project cannot set "
                  f"{', '.join(sorted(config.project_refused))} — only yours can",
                  file=sys.stderr)

        # Progress on stderr keeps stdout clean for the answer itself.
        def echo(event: Any) -> None:
            if event.kind is Kind.TOOL_START:
                print(f"· {event.get('summary', event.get('name'))}", file=sys.stderr)
            elif event.kind is Kind.ERROR:
                print(f"! {event.text}", file=sys.stderr)

        bus.subscribe(echo)

    # @ references expand before the run, with the same guards the interface
    # uses — a scheduled prompt asking for @diff should work, and a scheduled
    # prompt pointed at a credentials file should not.
    secrets = Redactor([entry.api_key for entry in config.providers.values()
                        if entry.api_key])
    task, warning = "", ""
    if args.task:
        try:
            task, warning = expand(args.task, config.paths.project,
                                   context_limit=config.agent.context_limit,
                                   redact=secrets)
        except Refusal as refusal:
            print(f"refused: {refusal}", file=sys.stderr)
            return 2
    if warning:
        print(f"warning: {warning}", file=sys.stderr)

    # A stateless run: it keeps nothing unless it stops for a decision, and
    # then only a hidden continuation a later `--decision-answers` resumes by
    # ref. `run_turn` owns both, and refuses a bad batch before any model call.
    from .application import Binding, DecisionRejected, run_turn
    from .session.store import SessionStore

    try:
        result = run_turn(agent, task, decision_answers=answers,
                          store=SessionStore(config.paths.user / "sessions"),
                          binding=Binding.of(config))
    except DecisionRejected as refused:
        _report_refusal(refused, args.json)
        built.close()
        return 1
    memory.wait_for_reflection(timeout=20.0)

    if mismatched or interactions:
        # An entry that did not fit its form, or one no form ever used: the
        # script was not what this run needed, and it is not quietly dropped.
        problem = mismatched[0] if mismatched else (
            f"entry {interactions[0]['index']} was never used: no form it fits "
            f"was raised")
        _report_script_error(problem, args.json, result.clarification)
        built.close()
        return 1

    if args.json:
        payload = {
            "text": result.text,
            "ok": result.ok,
            "stopped": result.stopped,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "tools": used,
            "error": result.error,
            # What the completion gate could not see delivered (FR-037). A
            # partial answer is qualified here rather than only on the
            # terminal, so a script that reads `stopped` sees the same thing
            # a person would.
            "annotation": result.annotation,
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                # What the provider served from its cache. Kept apart from
                # `input_tokens` because it is billed differently and because
                # the benchmark's paired report needs both halves (FR-076).
                "cached_tokens": result.usage.cached_tokens,
                # What the provider stored for next time. It is a separate,
                # non-overlapping part of the prompt and is billed for cache
                # creation, so a benchmark total that omits it understates the
                # read for the providers that use it.
                "written_tokens": result.usage.written_tokens,
                "cost_usd": round(result.usage.cost_usd, 6),
            },
            "elapsed": round(result.elapsed, 2),
            # The paired record: counts only, beside the outcome above.
            "measurement": result.measurement.as_dict(),
            # The mutation preflight's sanitized trace — fingerprints and
            # bounded excerpts — so a wrong `allow` can be explained from the
            # artifact without rerunning the model (spec 002, FR-013).
            "preflight_traces": list(getattr(result, "preflight_traces", []) or []),
        }
        if result.clarification is not None:
            # The structured clarification outcome rides its own block, so a
            # dismissed question is never indistinguishable from the user
            # cancelling the whole turn (contracts §C3; FR-123).
            payload["clarification"] = result.clarification
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(result.text)
        if result.annotation:
            print(f"\n{result.annotation}")
        if result.error:
            print(f"\nerror: {result.error}", file=sys.stderr)

    built.close()
    if result.stopped == "clarification_required":
        # A distinct code for "a decision is still needed": not success (0),
        # not an error (1), and not a cancelled turn (130).
        return 3
    return 0 if result.ok else 1


def _report_refusal(refused: Any, as_json: bool) -> None:
    """A refused DecisionAnswer batch: what failed, and nothing else happened."""
    print(f"error: decision answers refused ({refused.kind}): {refused}",
          file=sys.stderr)
    if refused.refs:
        print("  refs: " + ", ".join(refused.refs), file=sys.stderr)
    if as_json:
        print(json.dumps({"text": "", "ok": False, "stopped": "error",
                          "error": refused.as_dict()}, ensure_ascii=False, indent=2))


def run_setup_command(config: Config, args: Any = None) -> int:
    """`comodor setup` — run the wizard again, keeping what is already there.

    It used to end here, back at the shell prompt, with nothing running. That
    is the command the installer calls, so the last thing an install did was
    say `Ready.` and hand back a prompt — leaving somebody who had just
    answered six questions to work out that the next step was to type the
    program's name. So the wizard asks, and this acts on the answer.
    """
    from .setup import run_setup

    try:
        config = run_setup(config, offer=True)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled; nothing was changed.", file=sys.stderr)
        return 130

    if config.needs_setup:
        # The wizard stopped short of a usable configuration — it says why
        # itself, and the transaction left the machine exactly as it was.
        # Offering to start an interface with nothing to talk to would be
        # offering something that cannot work.
        return 1
    if config.start_after_setup in ("interface", "both"):
        # The same launcher the bare command uses, checks and all. Setup has
        # just run, so its own setup-aware branch has nothing to ask; what it
        # still does is confirm the renderer and Bun before spawning a core.
        from .transport.commands import run_tui

        return run_tui(config, args)
    return 0


def run_approvals(config: Config, args: argparse.Namespace) -> int:
    """Show — or apply — the allowlist the approval log supports."""
    from rich.console import Console

    from .safety.mining import MIN_APPROVALS, apply_proposals, propose

    console = Console()
    log = config.paths.approvals
    wanted = args.apply

    if wanted is None:                                    # plain suggest
        proposals = propose(log)
        if not proposals:
            console.print(
                f"No proposals yet — nothing in [dim]{log}[/dim] has been "
                f"approved {MIN_APPROVALS} times or more.")
            console.print(
                "[dim]Every command you approve is recorded there; check "
                "back after a couple of weeks of use.[/dim]")
            return 0
        console.print(f"[bold]Proposed allowlist entries[/bold] "
                      f"(from {log}):")
        for item in proposals:
            console.print(f"  [good]{item.stem}[/good]  — {item.reason}")
            for example in item.examples[:-1]:
                console.print(f"[dim]    {example}[/dim]")
        console.print(
            "\nApply them all with [dim]comodor approvals --apply[/dim], "
            "or name the ones you want: [dim]comodor approvals --apply "
            f"{' '.join(item.stem for item in proposals[:2])}[/dim]")
        return 0

    stems = wanted if wanted else \
        [item.stem for item in propose(log)]
    if not stems:
        console.print("Nothing to apply — there are no proposals.")
        return 1
    added = apply_proposals(config, stems)
    if not added:
        console.print("Nothing changed — every named stem was already "
                      "in safety.allow_commands.")
        return 0
    console.print(f"[good]added[/good] {', '.join(added)}")
    console.print(f"[dim]saved to {config.paths.config_file}[/dim]")
    return 0


def run_doctor(config: Config, fix: bool = False) -> int:
    from rich.table import Table

    from .learning import BrainStore
    from .terminal import console as console_module

    theme = console_module.prepare_theme(config.ui.theme, config.ui.ascii_borders,
                                         no_color=False)
    console = console_module.build(theme)

    console.print(f"[title]Comodor {__version__}[/title]\n")

    providers = Table(title="Providers", title_justify="left", box=theme.box,
                      border_style=theme.style("border.dim"), expand=False)
    providers.add_column("name", style=theme.style("value"))
    providers.add_column("model")
    providers.add_column("endpoint", style=theme.style("dim"))
    providers.add_column("key")
    for entry in config.providers.values():
        status = ("[good]ready[/good]" if entry.ready else
                  "[dim]local[/dim]" if entry.local else "[bad]missing[/bad]")
        marker = " ←" if entry.name == config.provider else ""
        providers.add_row(entry.name + marker, entry.model, entry.base_url, status)
    console.print(providers)

    brain = BrainStore(config.paths.brain_db)
    stats = brain.stats()
    console.print("\n[title]Brain[/title]")
    console.print(f"  reflex:  {stats['rules_active']} active rules of "
                  f"{stats['rules']} · {stats['signals']} signals observed")
    console.print(f"  memory:  {stats['lessons']} lessons · {stats['skills']} skills · "
                  f"{stats['episodes']} tasks "
                  f"({stats['success_rate']:.0%} succeeded)")
    console.print(f"  index:   {'FTS5' if stats['fts'] else 'python BM25 fallback'}, "
                  f"{stats['indexed']} records in memory")
    if config.learning.associative:
        vocabulary = brain.load_associations()
        console.print(f"  words:   {len(vocabulary.totals)} terms related "
                      f"{vocabulary.size} ways, from {vocabulary.episodes} tasks")
    console.print(f"  file:    [dim]{stats['path']}[/dim]")
    brain.close()

    console.print("\n[title]Terminal[/title]")
    console.print(f"  size: {console.size.width}×{console.size.height}")
    console.print(f"  colour: {console.color_system or 'none'}")
    console.print(f"  unicode: {console_module.supports_unicode()}")
    console.print(f"  windows console without VT sequences: {console.legacy_windows}")

    missing = "" if config.paths.config_file.exists() else \
        "  [bad](missing — run comodor setup)[/bad]"
    console.print("\n[title]Paths[/title]")
    console.print(f"  workspace: [dim]{config.paths.project}[/dim]")
    console.print(f"  config:    [dim]{config.paths.config_file}[/dim]{missing}")
    console.print(f"  skills:    [dim]{config.paths.skills}[/dim]")

    # -- checks, and repairs ---------------------------------------------- #

    from .doctor import Status, apply_fixes, run_checks

    report = run_checks(config)
    # Padded before the markup is added, not after: Rich tags are characters to
    # an f-string but nothing to the terminal, so formatting the tagged string
    # aligns the columns to the wrong width.
    marks = {Status.OK: ("ok", "good"), Status.WARN: ("warn", "warn"),
             Status.FAIL: ("fail", "bad")}
    label_width = max((len(f.name) for f in report.findings), default=12)

    console.print("\n[title]Checks[/title]")
    for finding in report.findings:
        word, style = marks[finding.status]
        console.print(f"  [{style}]{word:<4}[/{style}]  "
                      f"{finding.name:<{label_width}}  [dim]{finding.detail}[/dim]")
        if finding.status is not Status.OK and finding.remedy:
            console.print(f"  {'':<6}  [dim]{'':<{label_width}}  "
                          f"→ {finding.remedy}[/dim]")

    if fix and report.fixable:
        console.print("\n[title]Repairs[/title]")
        apply_fixes(report)
        for done in report.repaired:
            console.print(f"  [good]fixed[/good]   {done}")
        for failed in report.failed:
            console.print(f"  [bad]failed[/bad]  {failed}")

        # Re-checked, so what is printed is the state now rather than the state
        # that prompted the repair. A repair that did not take should say so.
        report = run_checks(config)
        remaining = report.problems
        if remaining:
            console.print(f"\n{len(remaining)} problem(s) still need you:")
            for finding in remaining:
                console.print(f"  [dim]{finding.name}: "
                              f"{finding.remedy or finding.detail}[/dim]")
        else:
            console.print("\n[good]Everything checks out.[/good]")

    elif report.fixable:
        console.print(f"\n{len(report.fixable)} of these can be repaired "
                      "automatically: [accent]comodor doctor --fix[/accent]")

    if config.needs_setup:
        console.print("\n[bad]No provider is configured.[/bad] Run "
                      "[accent]comodor setup[/accent] to choose one, or "
                      "[accent]comodor --demo[/accent] to try the interface "
                      "offline.")
        return 1

    return 1 if report.worst is Status.FAIL else 0


def run_update(config: Config, check_only: bool = False) -> int:
    """Move to the newest published version.

    Four steps, and each one can stop the run with something the user can act
    on: what is out there, whether it is newer than this, how this copy would
    be upgraded, and what version answers afterwards.
    """
    from . import update as updater
    from .terminal import console as console_module

    theme = console_module.prepare_theme(config.ui.theme, config.ui.ascii_borders,
                                         no_color=False)
    console = console_module.build(theme)
    here = updater.current()

    console.print(f"\n[title]Comodor {here}[/title]")

    release = updater.latest()
    if release is None:
        console.print("  [bad]Could not reach the package index.[/bad] "
                      "[dim]Check the connection and try again.[/dim]\n")
        return 1

    step = updater.plan()

    if not updater.is_newer(release.version, here):
        # Ahead of the index rather than behind it: a development build, which
        # is a different sentence from "up to date".
        ahead = updater.is_newer(here, release.version)
        console.print(
            f"  [good]{release.version} is the newest published version"
            f"[/good][dim], and this is "
            f"{'ahead of it' if ahead else 'it'}.[/dim]")
        if step.detail:
            console.print(f"  [dim]{step.detail}[/dim]")
        console.print("")
        return 0

    console.print(f"  [accent]{release.version}[/accent] is available."
                  f"  [dim]{release.url}[/dim]")

    if step.blocked:
        console.print(f"\n  [warn]{step.blocked}[/warn]\n")
        return 1

    if step.detail:
        console.print(f"  [dim]{step.detail}[/dim]")
    console.print(f"  [dim]{' '.join(step.command)}[/dim]")

    if check_only:
        console.print("\n[dim]Nothing was changed: this was --check.[/dim]\n")
        return 0

    console.print("\n  updating…")
    # Run it, then ask what version answers. Asked, not assumed.
    outcome = updater.upgrade(step, release.version)

    if not outcome.ok:
        console.print(f"  [bad]failed[/bad]  [dim]{outcome.message}[/dim]\n")
        return 1
    if outcome.deferred:
        console.print(f"  [good]{outcome.message}[/good]\n")
        return 0
    if outcome.forced:
        # Worth saying out loud: something was pinned, and now it is not.
        console.print("  [dim]the recorded requirement pinned the version, so it "
                      "was reinstalled from the index[/dim]")
    if outcome.version:
        console.print(f"  [good]now on {outcome.version}[/good]\n")
    else:
        console.print(f"  [good]done[/good] [dim]— {outcome.message}.[/dim]\n")
    return 0


def run_uninstall(config: Config, dry_run: bool = False,
                  assume_yes: bool = False) -> int:
    """Show everything that would go, then go.

    The prompt asks for the word rather than for a letter. `y` is what a hand
    presses on the way past; this deletes an API key, every rule the agent has
    learned and every conversation it has had, and none of it can be undone.
    Typing it out takes a second, and it is the difference between meaning to
    and not.
    """
    from rich.padding import Padding
    from rich.text import Text

    from .terminal import console as console_module
    from .uninstall import _size, apply, survey

    theme = console_module.prepare_theme(config.ui.theme, config.ui.ascii_borders,
                                         no_color=False)
    console = console_module.build(theme)

    def indented(text: str, indent: int) -> Padding:
        """Wrapped text whose second line lines up with its first.

        Rich wraps to the console width and starts the continuation at column
        zero, which turns a two-line note into something that looks like two
        notes. Padding wraps inside its own box instead.
        """
        return Padding(Text(text, style=theme.style("dim")), (0, 0, 0, indent))

    # The project this was run in counts whether or not a session recorded it:
    # somebody uninstalling from inside a project means that one.
    found = survey(config, config.paths.project)

    console.print(f"[title]Uninstalling Comodor {__version__}[/title]\n")

    if not found.items:
        console.print("Nothing to remove — there is no trace of it on this "
                      "machine to begin with.")
        return 0

    headings = {
        "data": "Your data",
        "project": "In your projects",
        "program": "The program",
        "launcher": "The command",
        "path": "Your shell",
    }
    for kind, heading in headings.items():
        group = [item for item in found.items if item.kind == kind]
        if not group:
            continue
        console.print(f"[title]{heading}[/title]")
        for item in group:
            size = f"  [dim]{_size(item.size)}[/dim]" if item.size else ""
            console.print(f"  {item.label}{size}")
            if item.path:
                console.print(indented(str(item.path), 4))
            if item.detail:
                console.print(indented(item.detail, 4))
        console.print("")

    for note in found.notes:
        console.print(indented(f"· {note}", 2))

    console.print(f"\n[warn]{_size(found.total_bytes)} across "
                  f"{len(found.items)} place(s). None of it can be undone.[/warn]")

    if dry_run:
        console.print("\n[dim]Nothing was removed: this was --dry-run.[/dim]")
        return 0

    if not assume_yes:
        console.print("\nType [accent]uninstall[/accent] to confirm, or "
                      "anything else to stop.")
        try:
            answer = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("\nStopped. Nothing was removed.")
            return 130
        if answer != "uninstall":
            console.print("Stopped. Nothing was removed.")
            return 1

    apply(found)

    console.print("")
    for done in found.removed:
        console.print(f"  [good]removed[/good]  [dim]{done}[/dim]")
    for failure in found.failed:
        console.print(f"  [bad]left[/bad]     [dim]{failure}[/dim]")

    if found.failed:
        console.print(f"\n[bad]{len(found.failed)} thing(s) could not be "
                      "removed.[/bad] They are listed above with the reason.")
        return 1

    console.print("\nGone. Thank you for trying it.")
    return 0


def _use_font(path: str, family: str) -> None:
    """Point the exported SVG at a font stack that covers Arabic script.

    Rich writes `font-family` into the embedded stylesheet in more than one
    place, and offers no option to choose it, so every declaration is rewritten
    afterwards. Cruder than an argument would be, and it is the only place this
    program picks a typeface at all.
    """
    import re
    from pathlib import Path

    file = Path(path)
    try:
        markup = file.read_text(encoding="utf-8")
    except OSError:
        return
    file.write_text(
        re.sub(r"font-family\s*:[^;}]*", f"font-family:{family}", markup),
        encoding="utf-8",
    )


def _skill_count(config: Config) -> int:
    """How many skills are loaded, or nothing if they cannot be read.

    Counted rather than assumed: the number is printed on the first screen
    somebody sees, and a wrong one there is the sort of small lie that makes
    people stop believing the rest of the panel.
    """
    try:
        from .skills import load_for

        return sum(1 for skill in load_for(config).all() if skill.enabled)
    except Exception:
        return 0


def run_insights(config: Config, args: argparse.Namespace) -> int:
    """The cross-session view: spend, activity, and whether the brain helps."""
    import json as jsonlib

    from .insights import collect, render, to_json

    days = max(1, int(getattr(args, "days", 30) or 30))
    result = collect(config, days=days)
    if getattr(args, "json", False):
        print(jsonlib.dumps(to_json(result), ensure_ascii=False, indent=2))
    else:
        from rich.console import Console

        from .terminal.console import force_utf8

        force_utf8()
        Console().print(render(result))
    return 0


def _say_what_the_copy_refused(console, found: list, already: dict) -> None:
    """Reasons the copy added after the listing was printed."""
    for entry in found:
        for note in entry.passed_over[already[id(entry)]:]:
            console.print(f"[dim]  not imported: {note}[/dim]")


def run_import(config: Config, args: argparse.Namespace) -> int:
    """Bring another agent's settings over, outside the first run.

    Same rules as the wizard's step: nothing already set here is replaced,
    nothing is moved, and what was deliberately left behind is said rather than
    skipped silently.
    """
    from . import migrate
    from .terminal import console as console_module

    theme = console_module.prepare_theme(config.ui.theme, config.ui.ascii_borders,
                                         no_color=False)
    console = console_module.build(theme)

    try:
        found = migrate.discover()
    except OSError as error:
        console.print(f"[bad]could not look: {error}[/bad]")
        return 1

    if not found:
        console.print("Nothing to import — no OpenClaw or Hermes installation "
                      "was found in your home directory.")
        return 0

    for entry in found:
        console.print(f"[accent]{entry.tool}[/accent]  {entry.summary()}")
        console.print(f"[dim]{entry.root}[/dim]")
        for note in entry.passed_over:
            console.print(f"[dim]  not imported: {note}[/dim]")

    # Anything the copy itself decides against - a skill folder holding a link
    # out of itself, one far larger than a skill - is added to this list while
    # applying, which is after the lines above. Remembering where each list
    # ended is what lets those reasons reach the screen, rather than leaving
    # the reader to wonder why a skill they can see did not arrive.
    already = {id(entry): len(entry.passed_over) for entry in found}

    if args.dry_run:
        console.print("\n[dim]--dry-run: nothing was changed.[/dim]")
        return 0

    took = migrate.Outcome()
    for entry in found:
        try:
            got = migrate.apply(entry, config, take_keys=True,
                                take_skills=not args.keys_only,
                                take_model=not args.keys_only)
        except OSError as error:
            console.print(f"[bad]could not read {entry.tool}: {error}[/bad]")
            continue
        took.keys += got.keys
        took.skills += got.skills
        took.skipped += got.skipped
        took.model = took.model or got.model

    if not took.anything:
        console.print("\nNothing new — everything it found is already set here.")
        for note in took.skipped:
            console.print(f"[dim]  {note}[/dim]")
        _say_what_the_copy_refused(console, found, already)
        return 0

    config.save()
    console.print()
    _say_what_the_copy_refused(console, found, already)
    if took.keys:
        console.print(f"[good]keys[/good]    {', '.join(took.keys)}")
    if took.model:
        console.print(f"[good]model[/good]   {took.model}")
    if took.skills:
        console.print(f"[good]skills[/good]  {', '.join(took.skills)}")
    for note in took.skipped:
        console.print(f"[dim]  kept as it was — {note}[/dim]")
    console.print(f"\n[dim]saved to {config.paths.config_file}[/dim]")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Before anything reads the environment. The profile decides where the
    # config itself comes from, so it has to be settled ahead of `load`, and
    # the environment variable is how every module that never sees these args
    # (the stores, the daemons) reaches the same decision.
    profile = getattr(args, "profile", None)
    if profile:
        import os

        os.environ["COMODOR_PROFILE"] = profile

    # Before the configuration is loaded: somebody who cannot get the program
    # to start is exactly the person who needs the help page, and loading a
    # broken config first would deny it to them.
    if getattr(args, "want_help", False) or args.command == "help":
        from .help import render

        return render(topic=getattr(args, "topic", "") or "")

    config = apply_overrides(load_config(args.cwd), args)

    # Demo mode is a contract, not a launcher's private patch: the production
    # interface spawns the core as a second process, and the only way that
    # process knows it is running offline is in the environment. Both the
    # flag and the variable land here, before any dispatch, so `comodor --demo`,
    # `comodor --demo run ...` and the spawned core all see the same scripted
    # provider.
    import os

    if getattr(args, "demo", False) or os.environ.get("COMODOR_DEMO"):
        from .config import ProviderConfig

        config.providers["fake"] = ProviderConfig(
            name="fake", kind="fake", base_url="offline", api_key="demo",
            model="comodor-demo", label="Demo (offline)", configured=True)
        config.provider = "fake"
        config.model = "comodor-demo"

    if args.command == "doctor":
        return run_doctor(config, fix=getattr(args, "fix", False))
    if args.command == "update":
        return run_update(config, check_only=args.check)
    if args.command == "uninstall":
        return run_uninstall(config, dry_run=args.dry_run, assume_yes=args.yes)
    if args.command == "mcp":
        from .mcp.commands import run as run_mcp

        return run_mcp(config, args)
    if args.command == "local":
        from .local.commands import run as run_local

        return run_local(config, args)
    if args.command == "cron":
        from .cron.commands import run as run_cron

        return run_cron(config, args)
    if args.command == "curator":
        from .learning.commands import run as run_curator

        return run_curator(config, args)
    if args.command == "telegram":
        from .telegram.commands import run as run_telegram

        return run_telegram(config, args)
    if args.command == "whatsapp":
        from .whatsapp.commands import run as run_whatsapp

        return run_whatsapp(config, args)
    if args.command == "slack":
        from .slack.commands import run as run_slack

        return run_slack(config, args)
    if args.command == "github":
        from .github.commands import run as run_github

        return run_github(config, args)

    if args.command == "discord":
        from .discord.commands import run as run_discord

        return run_discord(config, args)
    if args.command == "skills":
        from .skills.commands import run as run_skills

        return run_skills(config, args)
    if args.command == "web":
        from .web.commands import run as run_web

        return run_web(config, args)
    if args.command == "webhook":
        from .webhook.commands import run as run_webhook

        return run_webhook(config, args)
    if args.command == "acp":
        from .acp.commands import run as run_acp

        return run_acp(config, args)
    if args.command == "core":
        from .transport.commands import run as run_core

        return run_core(config, args)
    if args.command == "tui-v2":
        from .transport.commands import run_tui

        return run_tui(config, args)
    if args.command == "memory-provider":
        from .learning.providers.commands import run as run_memory_provider

        return run_memory_provider(config, args)
    if args.command == "journey":
        from .learning.journey_commands import run as run_journey

        return run_journey(config, args)
    if args.command == "plugins":
        from .plugins.commands import run as run_plugins

        return run_plugins(config, args)
    if args.command == "serve":
        from .api.server import run as run_api

        return run_api(config, args)
    if args.command == "insights":
        return run_insights(config, args)
    if args.command == "approvals":
        return run_approvals(config, args)
    if args.command == "setup":
        return run_setup_command(config, args)
    if args.command == "import":
        return run_import(config, args)
    if args.command == "run":
        return run_headless(config, args)

    # The default route is the production interface, and it is handed the
    # configuration as found. The launcher owns the first run: it checks its
    # own requirements — a renderer, a Bun that is new enough — and only then
    # asks the setup questions. Asking them here first, as this used to,
    # meant a fresh machine without Bun answered everything and was refused
    # afterwards, which is the order the launcher exists to prevent.
    from .transport.commands import run_tui

    return run_tui(config, args)


if __name__ == "__main__":
    raise SystemExit(main())
