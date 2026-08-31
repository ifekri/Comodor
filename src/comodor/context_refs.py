"""@ references: the user's way to hand the agent context before it asks.

`@diff explain this change` should work in one turn with no tool calls. The
user knows which files matter; making the agent find them with read_file
first is a round trip that buys nothing. So the prompt is expanded before it
reaches the model: each reference is replaced by the material itself, under
one clear header, and the expansion is part of the message — the transcript
shows exactly what the model was told, which is the whole of the
transparency rule.

The forms, and what each costs:

    @file:path[:10-25]   a file, or lines 10-25 of one
    @folder:path         a directory listing, capped
    @diff  @staged       the working tree's or the index's changes
    @git:N               the last N commits, message plus patch (N ≤ 10)
    @url:https://…       a page, fetched once

Three limits keep an @ from becoming a budget accident:

* **Credential paths are refused outright** — key material, shell profiles,
  Comodor's own brain. No size limit makes them safe to paste into a prompt,
  so there is no size that works.
* **Binary files are refused**, by content, not by extension — a renamed
  database must not ride into the conversation because it was called .txt.
* **25% of the context window warns; 50% refuses.** A prompt that eats half
  the window before the work starts is a failed task waiting to happen, and
  the send is stopped while the user can still see why.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

#: Soft budget: past this share of the context window, the interface warns.
WARN_SHARE = 0.25
#: Hard budget: past this, the message is refused at send time.
HARD_SHARE = 0.50

FOLDER_FILE_CAP = 200
FOLDER_CHARS_CAP = 8_000
GIT_COMMIT_CAP = 10
FILE_CHARS_CAP = 60_000

#: The header everything expanded lands under. One header, so a glance at the
#: transcript tells expanded material from what the user actually typed.
HEADER = "--- Attached context ---"

#: Paths that hold credentials, not code. Refused before any size check,
#: because the answer to "may I read your private key" is never a size.
_BLOCKED_PATH_PARTS = (
    ".ssh", ".aws", ".gnupg", ".kube", ".netrc", ".env",
    "id_rsa", "id_ed25519", "id_ecdsa", ".pem", ".p12", ".pfx",
    "credentials", ".git-credentials", ".npmrc", ".pypirc",
    "config.json", "brain.db", ".history", "shadow",
)
_BLOCKED_EXACT = {".netrc", ".bashrc", ".bash_profile", ".zshrc", ".profile",
                  ".zprofile", ".zsh_history", ".bash_history"}


class Refusal(Exception):
    """A reference that must not be expanded, with the reason shown to the
    user before the message is sent."""


# --------------------------------------------------------------------------- #
# the parser
# --------------------------------------------------------------------------- #

def find_references(text: str) -> list[tuple[str, str]]:
    """Every reference in the draft, as (form, argument) pairs.

    A reference is an @ followed by one of the known forms and a value of
    non-space characters (path values may contain none of the forms' own
    delimiters). Unknown @words are left alone — @handles in ordinary prose
    are none of this module's business.
    """
    found: list[tuple[str, str]] = []
    for word in text.split():
        if not word.startswith("@"):
            continue
        body = word[1:]
        form, _, argument = body.partition(":")
        if form in ("file", "folder", "url"):
            if argument:
                found.append((form, argument))
        elif body in ("diff", "staged"):
            found.append((body, ""))
        elif form == "git" and argument:
            found.append(("git", argument))
    return found


def expand(text: str, cwd: Path, context_limit: int = 0,
           redact: Any = None) -> tuple[str, str]:
    """Expand every reference. Returns (message, warning).

    The message is what the model should receive: the user's own words first,
    the material under the header after. ``warning`` is empty or a caution
    shown after the send went through. A :class:`Refusal` is raised for
    anything that must stop the send instead.
    """
    references = find_references(text)
    if not references:
        return text, ""

    blocks: list[str] = []
    for form, argument in references:
        if form == "file":
            blocks.append(_file(argument, cwd))
        elif form == "folder":
            blocks.append(_folder(argument, cwd))
        elif form in ("diff", "staged"):
            blocks.append(_git(cwd, ["diff", "--staged" if form == "staged"
                                     else "HEAD"]))
        elif form == "git":
            blocks.append(_git_log(argument, cwd))
        elif form == "url":
            blocks.append(_url(argument))

    joined = "\n\n".join(block for block in blocks if block)
    if redact is not None:
        joined = redact(joined)

    warning = _check_budget(text, joined, context_limit)
    return f"{text}\n\n{HEADER}\n\n{joined}", warning


# --------------------------------------------------------------------------- #
# the forms
# --------------------------------------------------------------------------- #

def _file(argument: str, cwd: Path) -> str:
    """`@file:path[:10-25]` — a whole file, or a 1-based line range."""
    argument, _, span = argument.partition(":")
    path = _resolve(argument, cwd)
    _guard(path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Refusal(f"@file:{argument}: {error}") from None
    if _looks_binary(raw):
        raise Refusal(f"@file:{argument} looks like a binary file — "
                      "read it with tools instead of pasting it into a prompt.")
    content = raw.decode("utf-8", "replace")
    if span:
        content = _slice(content, span, argument)
    if len(content) > FILE_CHARS_CAP:
        content = (content[:FILE_CHARS_CAP]
                   + f"\n… [{len(content) - FILE_CHARS_CAP:,} more characters — "
                   f"the file is at {argument}; ask the agent to read the rest]")
    return f"### {argument}\n{content}"


def _slice(content: str, span: str, name: str) -> str:
    try:
        start_text, _, end_text = span.partition("-")
        start = max(1, int(start_text or 1))
        end = int(end_text) if end_text else start
    except ValueError:
        raise Refusal(f"@file:{name}:{span} is not a line range like :10-25") \
            from None
    if end < start:
        raise Refusal(f"@file:{name}:{span}: the range ends before it starts")
    lines = content.splitlines()
    if start > len(lines):
        raise Refusal(f"@file:{name}:{span}: the file has {len(lines)} lines — "
                      f"line {start} does not exist")
    # A range ending past the last line is fine: it reads as "to the end".
    picked = lines[start - 1:end]
    header = f"lines {start}-{min(end, len(lines))}" if end - start > 0 \
        else f"line {start}"
    return f"[{header} of {len(lines)}]\n" + "\n".join(picked)


def _folder(argument: str, cwd: Path) -> str:
    """`@folder:path` — a capped directory listing, so the model sees shape."""
    path = _resolve(argument, cwd)
    _guard(path)
    if not path.is_dir():
        raise Refusal(f"@folder:{argument} is not a directory")
    entries: list[str] = []
    for item in sorted(path.rglob("*")):
        if _blocked(item) or any(part.startswith(".") and part != "."
                                 for part in item.relative_to(path).parts):
            continue
        suffix = "/" if item.is_dir() else ""
        entries.append(f"{item.relative_to(path)}{suffix}")
        if len(entries) >= FOLDER_FILE_CAP:
            entries.append(f"… [{FOLDER_FILE_CAP}-entry cap reached]")
            break
    listing = "\n".join(entries)
    if len(listing) > FOLDER_CHARS_CAP:
        listing = (listing[:FOLDER_CHARS_CAP]
                   + "\n… [listing cut — use @file for the parts that matter]")
    return f"### {argument}/ (listing)\n{listing}"


def _git(cwd: Path, args: list[str]) -> str:
    done = _git_run(cwd, *args)
    if not done.strip():
        return f"### {args[-1]}\n(no changes)"
    return f"### git {args[-1]}\n{done[:FILE_CHARS_CAP]}"


def _git_log(argument: str, cwd: Path) -> str:
    """`@git:N` — the last N commits, message plus patch, N ≤ 10."""
    try:
        count = int(argument)
    except ValueError:
        raise Refusal(f"@git:{argument} is not a number") from None
    count = max(1, min(count, GIT_COMMIT_CAP))
    done = _git_run(cwd, "log", f"-{count}", "--patch", "--stat")
    if not done.strip():
        raise Refusal("@git found no commits — is this a git repository?")
    return f"### git log (last {count})\n{done[:FILE_CHARS_CAP]}"


def _url(argument: str) -> str:
    """`@url:https://…` — a page, fetched once, reduced to text.

    Only http(s): the file scheme would make `@url:` a way around the
    credential-path blocklist, which would be a hole wearing the wrong hat.
    """
    if not argument.startswith(("http://", "https://")):
        raise Refusal(f"@url:{argument} — only http and https are supported")
    from .net import http
    from .safety.ssrf import UnsafeURL, assert_url_safe
    from .tools.web import USER_AGENT, html_to_text

    try:
        assert_url_safe(argument)
    except UnsafeURL as error:
        raise Refusal(f"@url:{argument} — {error}") from None
    try:
        response = http.get(argument, headers={"User-Agent": USER_AGENT},
                            timeout=(10.0, 30.0))
    except http.RequestError as exc:
        raise Refusal(f"@url:{argument} could not be fetched: {exc}") from None
    with response:
        if not response.ok:
            raise Refusal(f"@url:{argument} returned "
                          f"{response.status_code} {response.reason}")
        body = response.text
    text = html_to_text(body) if body.lstrip().startswith("<") else body
    return f"### {argument}\n{text[:FILE_CHARS_CAP]}"


# --------------------------------------------------------------------------- #
# the guards
# --------------------------------------------------------------------------- #

def _resolve(argument: str, cwd: Path) -> Path:
    path = Path(argument).expanduser()
    if not path.is_absolute():
        path = cwd / path
    try:
        return path.resolve()
    except OSError:
        return path


def _guard(path: Path) -> None:
    if _blocked(path):
        raise Refusal(
            f"@{path.name} is refused: it looks like a credentials or config "
            "file, and prompt content is not a safe place for secrets. If the "
            "agent needs it, it can ask for the specific value instead.")


def _blocked(path: Path) -> bool:
    text = str(path)
    name = path.name.lower()
    if name in _BLOCKED_EXACT:
        return True
    return any(part in text.lower() for part in _BLOCKED_PATH_PARTS)


def _looks_binary(raw: bytes) -> bool:
    """Nulls are the honest signal: text files do not contain them."""
    if not raw:
        return False
    sample = raw[:8192]
    return b"\x00" in sample


def _check_budget(original: str, expanded: str, context_limit: int) -> str:
    """The 25% warn / 50% refuse rule, measured against the context window.

    Returns the warning to show after the send, if any. Without a known
    window there is no share to compute, so nothing is measured rather than a
    made-up percentage being shown.
    """
    added = len(expanded) - len(original)
    if context_limit <= 0:
        return ""
    # A token is a little over four characters of code and prose, measured.
    tokens = added // 4
    share = tokens / context_limit
    if share > HARD_SHARE:
        raise Refusal(
            f"the attached context is about {share:.0%} of the context window "
            f"(~{tokens:,} tokens). Trim the references — a line range on a "
            "large file helps more than the whole file — and send again.")
    if share > WARN_SHARE:
        return (f"attached context is about {share:.0%} of the context "
                f"window (~{tokens:,} tokens)")
    return ""


def _git_run(cwd: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, timeout=30.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    return done.stdout.decode("utf-8", "replace")
