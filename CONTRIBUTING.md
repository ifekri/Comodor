# Contributing to Comodor

Thanks for wanting to help. This document is short on purpose — the important
parts are the two conventions at the bottom, which are what actually make
review quick.

## Getting set up

```bash
git clone https://github.com/ifekri/Comodor && cd Comodor
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest -q
```

Python 3.11 or newer. `rich` is the only runtime dependency and `pytest` the
only development one; please keep it that way unless there is no alternative —
a terminal tool that drags in a dependency tree is a terminal tool people stop
installing.

The suite runs the whole agent against a scripted provider, so it needs no
network, no API key and no spend. It should stay that way: a test that talks to
a real provider is a test that fails for reasons unrelated to the change.

## Before you open a pull request

```bash
pytest -q                     # everything green
comodor preview 120x34        # the interface still renders
comodor preview 60x20         # …and still renders when it is small
```

`tests/test_performance.py` enforces timing ceilings on the memory layer. If a
change makes recall slower, that suite fails — that is the intent, not a flake.
If the new cost is genuinely necessary, say so in the pull request and move the
ceiling in the same commit, so the trade is visible in review.

## What gets merged quickly

**A change that comes with the test that would have caught the bug.** Not a test
of the fix — a test of the behaviour. The distinction matters: one of them
survives the next refactor.

**A change whose comments explain *why*, not *what*.** The code already says
what it does. What review cannot recover is the reason a thing is done the
awkward way — the platform that misbehaves, the ordering that matters, the
obvious approach that was tried and did not work. Look at the existing comments
before writing new ones; that is the house style.

## Reporting a bug

`comodor doctor` prints the configuration, the provider status, the terminal's
capabilities and the paths in use. Please include it. Terminal bugs in
particular are almost always about a specific terminal at a specific size, and
that output identifies both.

If it involves a provider, say which one and which model. The provider layer is
where behaviour differs most between backends.

## Scope

Comodor is deliberately small: one dependency, no framework, no plugin system
that has to be maintained forever. Features that make it larger need to earn it
against that. If you are planning something substantial, open an issue first —
it is a much cheaper conversation than a rejected pull request.
