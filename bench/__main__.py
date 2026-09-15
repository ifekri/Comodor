"""`python -m bench` — run the suite and write the table.

The credentials come from the environment, or from a `.env` beside the source.
Nothing here reads the config of whoever is running it: a benchmark that
inherited somebody's settings would produce a number about their machine.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import baseline
from .report import write, write_paired
from .runner import run_task
from .task import TaskError, load_tasks

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench",
        description="Run the Comodor task benchmark and write the results.")
    parser.add_argument("--provider", default=os.environ.get("BENCH_PROVIDER", ""),
                        help="provider id, e.g. xiaomi, anthropic, openrouter")
    parser.add_argument("--model", default=os.environ.get("BENCH_MODEL", ""),
                        help="model id, as the provider names it")
    parser.add_argument("--tries", type=int, default=3,
                        help="attempts per task (default 3)")
    parser.add_argument("--only", nargs="*", default=[],
                        help="run only these tasks, by name or prefix")
    parser.add_argument("--keep", default="",
                        help="directory to move failed workspaces into")
    parser.add_argument("--dry-run", action="store_true",
                        help="load every task and print the suite, run nothing")
    parser.add_argument("--strategy", choices=baseline.STRATEGIES,
                        default=baseline.CURRENT,
                        help="the context strategy to measure (default: current)")
    parser.add_argument("--paired", action="store_true",
                        help="run every task under both strategies and write the "
                             "paired baseline report")
    parser.add_argument("--learning", action="store_true",
                        help="switch the learning engine on for every attempt (off "
                             "by default; each attempt still starts with an empty brain)")
    parser.add_argument("--without", nargs="*", default=[],
                        help="context optimizations to switch off, by name "
                             "(dedup delta budget ranking summary_provenance log_summary)")
    parser.add_argument("--label", default="",
                        help="a name for this run, carried into the result files")
    args = parser.parse_args(argv)

    _load_env(ROOT / "src" / ".env")

    try:
        tasks = load_tasks(HERE / "tasks", only=args.only or None)
    except TaskError as problem:
        print(f"bench: {problem}", file=sys.stderr)
        return 2

    if not tasks:
        print("bench: no tasks matched", file=sys.stderr)
        return 2

    if args.dry_run:
        for task in tasks:
            writes = "act" if task.writes else "plan"
            print(f"{task.category:9} {task.name:34} {writes:5} "
                  f"{task.max_steps} steps, {task.timeout:.0f}s")
        print(f"\n{len(tasks)} tasks")
        return 0

    if not args.provider or not args.model:
        print("bench: --provider and --model are required (or BENCH_PROVIDER "
              "and BENCH_MODEL in the environment)", file=sys.stderr)
        return 2

    keep = Path(args.keep).resolve() if args.keep else None

    strategies = list(baseline.STRATEGIES) if args.paired else [args.strategy]
    print(f"{len(tasks)} tasks, {args.tries} attempts each, "
          f"against {args.model} via {args.provider}, "
          f"strategy {' and '.join(strategies)}\n")
    started = time.monotonic()
    by_strategy: dict[str, list] = {}
    for strategy in strategies:
        outcomes = by_strategy.setdefault(strategy, [])
        for index, task in enumerate(tasks, start=1):
            print(f"[{strategy}] [{index}/{len(tasks)}] {task.category}/{task.name}",
                  flush=True)
            outcomes.append(run_task(task, provider=args.provider, model=args.model,
                                     tries=args.tries, keep=keep, strategy=strategy,
                                     learning=args.learning,
                                     without=tuple(args.without)))

    outcomes = by_strategy[strategies[0]]
    if args.paired:
        json_file, markdown_file = write_paired(
            by_strategy[baseline.CURRENT], by_strategy[baseline.NAIVE],
            HERE / "results", provider=args.provider, model=args.model,
            tries=args.tries)
    else:
        json_file, markdown_file = write(outcomes, HERE / "results",
                                         provider=args.provider, model=args.model,
                                         tries=args.tries, label=args.label)

    total = sum(one.passed for one in outcomes)
    of = sum(one.tries for one in outcomes)
    clean = sum(1 for one in outcomes if one.passed == one.tries)
    print(f"\n{clean}/{len(outcomes)} tasks passed every attempt "
          f"({total}/{of} attempts) in {(time.monotonic() - started) / 60:.0f} "
          f"minutes")
    print(f"{markdown_file}")

    kept = [path for group in by_strategy.values() for one in group for path in one.kept]
    if kept:
        print(f"\n{len(kept)} failed workspace(s) kept:")
        for path in kept[:10]:
            print(f"  {path}")
    return 0


def _load_env(path: Path) -> None:
    """Fill in credentials from a `.env`, without overriding the environment.

    Anything already set wins, so a CI secret is never quietly replaced by a
    file somebody left in their checkout.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
