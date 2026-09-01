"""@ references: expansion, refusals, and the budget rules."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from comodor.context_refs import (
    HEADER,
    Refusal,
    expand,
    find_references,
)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "app.py").write_text(
        "import os\n" * 5 + "def main():\n    pass\n")
    (tmp_path / "notes.md").write_text("# Notes\n\nsome prose\n")
    (tmp_path / ".env").write_text("SECRET_KEY=abc123\n")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a = 1\n")
    (tmp_path / "src" / "b.py").write_text("b = 2\n")
    (tmp_path / "src" / ".hidden").write_text("hidden\n")
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def git_workspace(workspace):
    def git(*args):
        subprocess.run(["git", *args], cwd=str(workspace), capture_output=True,
                       check=True)
    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("add", "-A")
    git("commit", "-qm", "first commit")
    (workspace / "app.py").write_text("import os\n" * 5 + "def changed():\n")
    return workspace


# -- parsing ----------------------------------------------------------------- #

def test_the_forms_are_found():
    text = ("look at @file:app.py:3-5 and @folder:src then @diff "
            "@staged @git:3 @url:https://example.com")
    forms = find_references(text)
    assert ("file", "app.py:3-5") in forms
    assert ("folder", "src") in forms
    assert ("diff", "") in forms
    assert ("staged", "") in forms
    assert ("git", "3") in forms
    assert ("url", "https://example.com") in forms


def test_an_unknown_at_word_is_left_alone():
    assert find_references("ping @somebody about it") == []


def test_text_without_references_passes_through():
    message, warning = expand("plain question", Path.cwd())
    assert message == "plain question"
    assert warning == ""


# -- expansion ---------------------------------------------------------------- #

def test_a_file_is_inlined_under_the_header(workspace):
    message, _ = expand("explain @file:app.py", workspace)
    assert message.startswith("explain @file:app.py")
    assert HEADER in message
    assert "def main():" in message
    # the reference stays in the user's words; the material is added after
    assert message.index("explain") < message.index(HEADER)


def test_a_line_range_is_sliced(workspace):
    message, _ = expand("@file:app.py:6-7", workspace)
    assert "def main():" in message
    assert "import os" not in message.split(HEADER)[1]


def test_a_folder_listing_is_shaped_and_skips_hidden(workspace):
    message, _ = expand("@folder:src", workspace)
    body = message.split(HEADER)[1]
    assert "a.py" in body
    assert ".hidden" not in body


def test_diff_and_git_use_the_repository(git_workspace):
    message, _ = expand("@diff", git_workspace)
    assert "def changed():" in message
    log, _ = expand("@git:1", git_workspace)
    assert "first commit" in log


def test_redaction_applies_to_expanded_material(workspace):
    (workspace / "leak.txt").write_text("token: sk-abc123\n")
    message, _ = expand(
        "@file:leak.txt", workspace, redact=lambda text: text.replace(
            "sk-abc123", "[redacted]"))
    assert "sk-abc123" not in message
    assert "[redacted]" in message


# -- refusals ------------------------------------------------------------------ #

@pytest.mark.parametrize("target", [
    "app.py:99-200",
    "app.py:9-3",
    "app.py:ten",
])
def test_a_bad_range_is_refused(workspace, target):
    with pytest.raises(Refusal):
        expand(f"@file:{target}", workspace)


def test_a_range_ending_past_the_file_means_to_the_end(workspace):
    message, _ = expand("@file:app.py:6-99", workspace)
    assert "def main():" in message


def test_a_credentials_file_is_refused_by_name(workspace):
    with pytest.raises(Refusal) as refused:
        expand("@file:.env", workspace)
    assert "credentials" in str(refused.value)


def test_a_home_credential_is_refused(workspace):
    with pytest.raises(Refusal):
        expand("@file:~/.ssh/config", workspace)


def test_binary_content_is_refused(workspace):
    with pytest.raises(Refusal) as refused:
        expand("@file:blob.bin", workspace)
    assert "binary" in str(refused.value)


def test_a_url_outside_http_is_refused(workspace):
    with pytest.raises(Refusal):
        expand("@url:file:///etc/passwd", workspace)


def test_a_git_argument_that_is_not_a_number_is_refused(workspace):
    with pytest.raises(Refusal):
        expand("@git:lots", workspace)


# -- the budget ---------------------------------------------------------------- #

def test_over_half_the_window_refuses_the_send(workspace):
    huge = "\n".join(f"line {number}" for number in range(20_000))
    (workspace / "big.txt").write_text(huge)
    with pytest.raises(Refusal) as refused:
        expand("@file:big.txt", workspace, context_limit=1000)
    assert "context window" in str(refused.value)


def test_a_quarter_to_a_half_warns_but_sends(workspace):
    body = "\n".join(f"line {number}" for number in range(400))
    (workspace / "medium.txt").write_text(body)
    message, warning = expand("@file:medium.txt", workspace, context_limit=2000)
    assert message                       # sent
    assert "context window" in warning   # and warned


def test_without_a_known_window_nothing_is_claimed(workspace):
    body = "x" * 100_000
    (workspace / "wide.txt").write_text(body)
    _, warning = expand("@file:wide.txt", workspace, context_limit=0)
    assert warning == ""
