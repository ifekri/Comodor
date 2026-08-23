"""A live check against a real provider, before a release.

The test suite never touches the network — it must run in CI, offline, on
somebody else's machine. That leaves one thing it cannot answer: does this
actually work against a real model? A release that passes 1100 offline tests and
fails on the first real request is exactly the failure a suite is supposed to
prevent and cannot.

So: a handful of end-to-end runs, deliberately, by hand, before a tag.

    uv run python scripts/live_check.py
    uv run python scripts/live_check.py --model anthropic/claude-sonnet-5

Credentials come from `src/.env`, which is git-ignored and belongs to whoever
is working on this. Nothing from it is printed - the key is redacted from every
line of output, and the endpoint is shown only as its host.

    XIAOMI_API_KEY=...
    XIAOMI_ENDPOINT=https://.../v1
    XIAOMI_MODEL=...

Any `<PROVIDER>_API_KEY` / `_ENDPOINT` / `_MODEL` trio works; the first one
found is used unless `--provider` names another.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ENV = ROOT / "src" / ".env"
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


# --------------------------------------------------------------------------- #
# credentials, read but never shown
# --------------------------------------------------------------------------- #


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        name, raw = match.group(1), match.group(2).strip()
        if raw[:1] in ("'", '"') and raw[-1:] == raw[:1]:
            raw = raw[1:-1]
        values[name] = raw.split(" #", 1)[0].strip()
    return values


def pick(values: dict[str, str], wanted: str = "") -> tuple[str, str, str, str]:
    """(provider, key, endpoint, model) from a `<NAME>_API_KEY` trio."""
    names = [name[: -len("_API_KEY")] for name in values
             if name.endswith("_API_KEY") and values[name]]
    if wanted:
        names = [name for name in names if name.lower() == wanted.lower()]
    if not names:
        raise SystemExit(
            f"no usable credentials in {ENV}. Expected a <NAME>_API_KEY, and "
            f"optionally <NAME>_ENDPOINT and <NAME>_MODEL.")
    name = names[0]
    return (name.lower(), values[f"{name}_API_KEY"],
            values.get(f"{name}_ENDPOINT", ""), values.get(f"{name}_MODEL", ""))


class Hidden:
    """Prints, with the secret taken out of whatever is being printed.

    Not a convenience. A live check is the script most likely to be pasted into
    an issue, and its whole job is to talk to a provider with a key.
    """

    def __init__(self, *secrets: str) -> None:
        self.secrets = [s for s in secrets if s and len(s) > 8]

    def __call__(self, text: str = "") -> None:
        for secret in self.secrets:
            text = text.replace(secret, f"<{len(secret)}-char key>")
        print(text, flush=True)


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #

CHECKS: list[tuple[str, str, str]] = [
    ("it answers at all",
     "Reply with exactly the word: ready", "ready"),
    ("it can read a file",
     "Read hello.txt in the workspace and tell me the single word inside it.",
     "pomegranate"),
    ("it can write a file",
     "Write a file called answer.txt containing exactly: 42", "42"),
    ("it can run a command",
     "Run `python -c \"print(6*7)\"` and tell me what it printed.", "42"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="",
                        help="which trio in src/.env to use")
    parser.add_argument("--model", default="", help="override the model")
    parser.add_argument("--only", default="", help="run one check by name")
    args = parser.parse_args(argv)

    provider, key, endpoint, model = pick(read_env(ENV), args.provider)
    model = args.model or model
    say = Hidden(key)

    host = urlparse(endpoint).netloc if endpoint else "the provider default"
    say(f"provider  {provider}")
    say(f"endpoint  {host}")
    say(f"model     {model or '(the provider default)'}")
    say()

    import os

    home = Path(tempfile.mkdtemp(prefix="live-"))
    (home / "project").mkdir()
    (home / "project" / "hello.txt").write_text("pomegranate\n", encoding="utf-8")
    os.environ.update(HOME=str(home), USERPROFILE=str(home),
                      COMODOR_HOME=str(home / ".comodor"), COMODOR_NO_IMPORT="1")
    for name in list(os.environ):
        if name.endswith("_API_KEY"):
            os.environ.pop(name)

    from comodor import config as config_module
    from comodor.agent.context import Conversation
    from comodor.agent.loop import AgentLoop
    from comodor.events import EventBus
    from comodor.learning import LearningEngine
    from comodor.providers.gateway import Gateway
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor
    from comodor.tools import ToolRegistry

    cfg = config_module.load(cwd=home / "project")
    cfg.use(provider if provider in cfg.providers else "custom",
            api_key=key, model=model, base_url=endpoint)
    cfg.agent.max_steps = 8
    cfg.agent.max_cost_usd = 0.50
    cfg.safety.auto_approve_writes = True
    cfg.safety.auto_approve_shell = True
    cfg.learning.reflect = False        # one call per check, not two

    failures = 0
    spent = 0.0
    for name, task, expected in CHECKS:
        if args.only and args.only not in name:
            continue

        bus = EventBus()
        bus.subscribe(lambda event: None)
        memory = LearningEngine(
            cfg, bus, Gateway(cfg),
            checkpoints=CheckpointStore(cfg.paths.checkpoints),
            redact=Redactor([key]))
        agent = AgentLoop(cfg, Gateway(cfg), ToolRegistry(config=cfg), bus,
                          PermissionEngine(cfg, bus), Conversation(), memory)

        started = time.monotonic()
        try:
            result = agent.run(task)
        except Exception as error:
            say(f"  FAIL  {name}: {type(error).__name__}: {error}")
            failures += 1
            continue
        elapsed = time.monotonic() - started
        spent += result.usage.cost_usd

        got = (result.text or "").lower()
        ok = expected.lower() in got
        failures += 0 if ok else 1
        say(f"  {'ok  ' if ok else 'FAIL'}  {name:<24} "
            f"{elapsed:5.1f}s  {result.steps} steps  "
            f"${result.usage.cost_usd:.4f}")
        if not ok:
            say(f"        wanted {expected!r} in the answer, got: "
                f"{(result.text or '')[:160]!r}")
        memory.close()

    say()
    say(f"{'all checks passed' if not failures else f'{failures} FAILED'}"
        f"   ${spent:.4f} spent")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
