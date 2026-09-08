"""The two languages cannot disagree about the wire.

This is the whole mechanism behind that claim, so it is worth stating what it
does and does not prove. It proves the committed Python and TypeScript were
generated from the committed schema. It does not prove the schema is right —
that is what the protocol tests are for. What it removes is the failure where
somebody edits a type on one side, both sides still compile, and the
disagreement is found by a user.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "protocol" / "v1.json"
GENERATOR = ROOT / "tools" / "protocol-codegen.py"
PYTHON_OUT = ROOT / "src" / "comodor" / "protocol" / "_generated.py"
TS_OUT = ROOT / "packages" / "protocol" / "src" / "generated.ts"


def test_the_committed_types_match_the_schema():
    finished = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True, text=True, cwd=str(ROOT))

    assert finished.returncode == 0, (
        "the generated protocol types are out of date.\n"
        "run: python tools/protocol-codegen.py\n\n"
        f"{finished.stdout}{finished.stderr}")


def test_generating_twice_produces_the_same_bytes():
    # Determinism, so `--check` cannot fail for a reason that is not a real
    # difference — a set iterated in a different order would do it.
    once = PYTHON_OUT.read_bytes(), TS_OUT.read_bytes()
    subprocess.run([sys.executable, str(GENERATOR)], check=True,
                   capture_output=True, cwd=str(ROOT))
    twice = PYTHON_OUT.read_bytes(), TS_OUT.read_bytes()

    assert once == twice


def test_both_generated_files_say_they_are_generated():
    for path in (PYTHON_OUT, TS_OUT):
        head = path.read_text(encoding="utf-8")[:400]
        assert "Do not edit" in head
        assert "protocol-codegen.py" in head


def test_the_generated_files_use_one_newline_everywhere():
    # Pinned at write time. Without it a checkout on Windows regenerates with
    # CRLF, `--check` fails on that platform only, and the fix looks like a
    # mystery to whoever is not on it.
    for path in (PYTHON_OUT, TS_OUT):
        assert b"\r\n" not in path.read_bytes(), f"{path.name} has CRLF"


# --------------------------------------------------------------------------- #
# the schema itself
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_every_method_names_shapes_that_exist(schema):
    defs = schema["$defs"]
    for method, spec in schema["x-methods"].items():
        assert spec["params"] in defs, f"{method}: no shape {spec['params']}"
        assert spec["result"] in defs, f"{method}: no shape {spec['result']}"


def test_every_event_names_a_shape_that_exists(schema):
    defs = schema["$defs"]
    for event, shape in schema["x-events"].items():
        assert shape in defs, f"{event}: no shape {shape}"


def test_every_shape_is_reachable_from_a_method_or_an_event(schema):
    """A definition nothing refers to is a shape nobody sends.

    Not fatal, but it is how a schema accumulates types for features that were
    described and never built — which is exactly the architecture theatre this
    phase is meant to avoid.
    """
    defs = schema["$defs"]
    roots = {spec["params"] for spec in schema["x-methods"].values()}
    roots |= {spec["result"] for spec in schema["x-methods"].values()}
    roots |= set(schema["x-events"].values())
    roots.add("Error")

    reachable: set[str] = set()
    frontier = list(roots)
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in defs:
            continue
        reachable.add(name)
        frontier.extend(_referenced(defs[name]))

    assert set(defs) - reachable == set()


def _referenced(node) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        target = node.get("$ref")
        if isinstance(target, str) and target.startswith("#/$defs/"):
            found.append(target[len("#/$defs/"):])
        for value in node.values():
            found.extend(_referenced(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_referenced(value))
    return found


def test_the_modes_in_the_schema_are_the_modes_the_core_enforces(schema):
    # The schema is what a client is allowed to send; `safety.modes` is what
    # the core will act on. A name in one and not the other is a mode a client
    # can ask for and never get, or one it can never reach.
    from comodor.safety.modes import ALL

    assert tuple(schema["$defs"]["Mode"]["enum"]) == ALL


def test_the_error_codes_the_schema_lists_are_the_ones_the_core_raises(schema):
    from comodor import protocol as P

    assert set(schema["x-errors"]) == set(P.ERRORS)
