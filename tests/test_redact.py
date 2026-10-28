"""Credential coverage and bounded work on untrusted file contents."""

from __future__ import annotations

import subprocess
import sys

import pytest

from comodor.safety.redact import MASK, contains_credential, redact


def jwt(size: int) -> str:
    return "eyJ" + "A" * size + "." + "B" * size + "." + "C" * size


@pytest.mark.parametrize("credential", [
    jwt(10), jwt(5000),
    "-----BEGIN PRIVATE KEY----------END PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----\nbody\n-----END RSA PRIVATE KEY-----",
    "-----BEGIN " + "RSA " * 20 + "PRIVATE KEY-----" + "X" * 20000
    + "-----END PRIVATE KEY-----",
])
def test_normal_and_oversized_credentials_are_detected_and_fully_masked(credential):
    text = "before: " + credential + " after"
    assert contains_credential(text)
    assert redact(text) == "before: " + MASK + " after"


@pytest.mark.parametrize("text", [
    "eyJ" + "A" * 10 + "." + "B" * 10,
    "eyJ" + "A" * 9 + "." + "B" * 10 + "." + "C" * 10,
    "-----BEGIN RSA PRIVATE KEY-----\nbody without an end marker",
    "-----END PRIVATE KEY-----",
])
def test_incomplete_shapes_still_pass_through(text):
    assert not contains_credential(text)
    assert redact(text) == text


def test_jwt_can_start_inside_a_run_and_later_valid_tokens_are_still_masked():
    text = "prefix" + jwt(10) + " / eyJtoo.short / " + jwt(20)
    assert redact(text) == "prefix" + MASK + " / eyJtoo.short / " + MASK
    # A token's consumed signature cannot be the start of an overlapping match.
    text = jwt(10) + jwt(10) + " / " + jwt(10)
    assert redact(text) == MASK + "." + "B" * 10 + "." + "C" * 10 + " / " + MASK


def test_private_keys_use_the_first_begin_and_next_end_without_losing_surrounding_text():
    begin = "-----BEGIN RSA PRIVATE KEY-----"
    end = "-----END EC PRIVATE KEY-----"
    text = "before " + begin + begin + "body" + end + " middle " + begin + end + " after"
    assert redact(text) == "before " + MASK + " middle " + MASK + " after"
    # A stray END must not consume the dashes that start a subsequent BEGIN.
    text = end[:-5] + begin + end
    assert redact(text) == end[:-5] + MASK


@pytest.mark.performance
@pytest.mark.parametrize("shape", ["jwt", "private-key", "short-runs"])
def test_repeated_unmatched_prefixes_do_not_stall_the_synchronous_scan(shape):
    # A subprocess deadline makes the regression safe even if the old quadratic
    # matcher is restored; it exercises both detection and shared redaction.
    script = '''
import sys
from comodor.safety.redact import contains_credential, redact
prefix = {"jwt": "eyJ", "private-key": "-----BEGIN PRIVATE KEY-----",
          "short-runs": "A."}[sys.argv[1]]
text = (prefix * (2_000_000 // len(prefix)))[:2_000_000]
assert not contains_credential(text)
assert redact(text) == text
'''
    subprocess.run([sys.executable, "-c", script, shape], check=True, timeout=5)
