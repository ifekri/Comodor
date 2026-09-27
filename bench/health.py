"""An unscored provider health probe: the real runtime shape, no benchmark task.

A one-line, no-tool health check passed while the real benchmark lost cells to
zero-output timeouts. The workload that fails is not a small prompt: it is the
normal system prompt, the full tool schema set, a large context, a read-only
tool turn, a mutation that triggers the mutation preflight, and several
sequential model calls under the normal output budget.

This probe builds a synthetic project and runs that shape against the
configured provider. It scores nothing, uses none of the benchmark tasks, and
exists only to decide whether the provider is stable enough to spend a scored
cohort on.

    python -m bench.health --provider xiaomi --model mimo-v2.5-pro
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import baseline
from .__main__ import ROOT, _load_env
from .runner import COST_CEILING, SOURCE, _bounded_output, _parse

#: A synthetic file big enough that reading it makes the context realistic.
FILLER_LINES = 1_500

#: A harmless, synthetic request that exercises read, write and preflight.
PROMPT = (
    "This is a synthetic health probe; nothing here is a real task.\n\n"
    "First call read_file on data.py and read it in full. Then append exactly "
    "this function to the end of data.py using edit_file or write_file:\n\n"
    "def probe_marker():\n    return 42\n\n"
    "Finally, reply with one short line summarising what you did."
)


@dataclass
class Probe:
    """One unscored probe turn and what it exercised."""

    index: int
    status: str = "unknown"     # complete | hard_timeout | provider_error | unreadable
    stopped: str = ""
    elapsed: float = 0.0
    steps: int = 0
    model_calls: int = 0
    preflight_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    written_tokens: int = 0
    tools: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def healthy(self) -> bool:
        return self.status == "complete"

    def line(self) -> str:
        return (
            f"probe {self.index}: {self.status}  {self.elapsed:.0f}s  "
            f"stopped={self.stopped or '-'}  steps={self.steps}  "
            f"model_calls={self.model_calls}  preflight_calls={self.preflight_calls}  "
            f"tool_calls={self.tool_calls}  "
            f"tokens={self.input_tokens}/{self.output_tokens}/"
            f"{self.cached_tokens}/{self.written_tokens}"
            + (f"  error={self.error}" if self.error else ""))


def _seed(work: Path) -> None:
    """A synthetic module with a large body, so a full read is a real context."""
    body = "\n".join(f"# synthetic filler line {i}" for i in range(FILLER_LINES))
    (work / "data.py").write_text(
        '"""Synthetic module for the health probe."""\n\n'
        f"{body}\n\n\ndef existing():\n    return 1\n", encoding="utf-8")


def _settings(home: Path, timeout: float) -> None:
    """The same agent shape the benchmark runs, without a task."""
    settings = {
        "agent": {
            "mode": "act",
            "max_steps": 25,
            "max_seconds": timeout,
            "max_cost_usd": COST_CEILING,
            **baseline.settings(baseline.CURRENT, ()),
        },
        "learning": {"enabled": False},
    }
    (home / "config.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


def run_probe(provider: str, model: str, *, timeout: float, index: int) -> Probe:
    """One synthetic agent turn against the configured provider. Never raises."""
    probe = Probe(index=index)
    root = Path(tempfile.mkdtemp(prefix="comodor-health-"))
    work = root / "work"
    home = root / "home"
    work.mkdir()
    home.mkdir()
    _seed(work)
    _settings(home, timeout)

    environment = dict(os.environ)
    environment.update({
        "COMODOR_HOME": str(home),
        "COMODOR_PROVIDER": provider,
        "COMODOR_MODEL": model,
        "PYTHONPATH": os.pathsep.join(
            [str(SOURCE)] + ([os.environ["PYTHONPATH"]]
                             if os.environ.get("PYTHONPATH") else [])),
        "COLUMNS": "200",
        "NO_COLOR": "1",
    })
    command = [sys.executable, "-m", "comodor", "run", PROMPT, "--json",
               "--max-steps", "25", "--yes"]

    started = time.monotonic()
    try:
        finished = subprocess.run(
            command, cwd=work, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        probe.status = "hard_timeout"
        probe.elapsed = time.monotonic() - started
        probe.error = f"hard timeout after {timeout:.0f}s; no final JSON captured"
        stdout = _bounded_output(getattr(expired, "stdout", None))
        stderr = _bounded_output(getattr(expired, "stderr", None))
        if stdout:
            probe.error += f"; partial stdout: {stdout}"
        if stderr:
            probe.error += f"; partial stderr: {stderr}"
        return probe
    except Exception as problem:                  # the child could not even start
        probe.status = "provider_error"
        probe.elapsed = time.monotonic() - started
        probe.error = f"{type(problem).__name__}: {problem}"
        return probe

    probe.elapsed = time.monotonic() - started
    report = _parse(finished.stdout)
    if report is None:
        probe.status = "unreadable"
        probe.error = (finished.stderr or "no JSON on stdout")[-400:]
        return probe

    usage = report.get("usage") or {}
    measurement = report.get("measurement") or {}
    probe.stopped = str(report.get("stopped", ""))
    probe.steps = int(report.get("steps", 0) or 0)
    probe.tools = [str(name) for name in report.get("tools", [])]
    probe.tool_calls = int(report.get("tool_calls", 0) or 0)
    probe.model_calls = int(measurement.get("model_turns", 0) or 0)
    probe.preflight_calls = int(measurement.get("preflight_calls", 0) or 0)
    probe.input_tokens = int(usage.get("input_tokens", 0) or 0)
    probe.output_tokens = int(usage.get("output_tokens", 0) or 0)
    probe.cached_tokens = int(usage.get("cached_tokens", 0) or 0)
    probe.written_tokens = int(usage.get("written_tokens", 0) or 0)
    if probe.stopped == "error":
        probe.status = "provider_error"
        probe.error = str(report.get("error", "") or "the turn ended in an error")
    else:
        probe.status = "complete"
    return probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.health",
        description="Unscored provider health probe: the real agent shape, no task.")
    parser.add_argument("--provider", default=os.environ.get("BENCH_PROVIDER", ""))
    parser.add_argument("--model", default=os.environ.get("BENCH_MODEL", ""))
    parser.add_argument("--turns", type=int, default=3,
                        help="independent probe turns (default 3)")
    parser.add_argument("--timeout", type=float, default=420.0,
                        help="per-turn ceiling in seconds (default 420)")
    args = parser.parse_args(argv)

    _load_env(ROOT / "src" / ".env")
    if not args.provider or not args.model:
        print("bench.health: --provider and --model are required", file=sys.stderr)
        return 2

    print(f"unscored health probe: {args.turns} turns against {args.model} "
          f"via {args.provider}")
    probes: list[Probe] = []
    for index in range(1, args.turns + 1):
        probe = run_probe(args.provider, args.model, timeout=args.timeout, index=index)
        probes.append(probe)
        print(probe.line(), flush=True)

    healthy = sum(1 for probe in probes if probe.healthy)
    print(f"health: {healthy}/{len(probes)} complete without hard timeout or "
          f"provider exception")
    return 0 if healthy == len(probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
