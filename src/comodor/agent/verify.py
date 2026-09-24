"""Running the project's own check when the agent says it is finished.

The system prompt asks the model to run the tests after a change. Asking is not
getting: the benchmark found a task reported as complete by a model that had
run nothing, and that is the ordinary case rather than the exceptional one.

`agent.verify_command` closes it. Whatever the project's own check is — `pytest
-q`, `npm test`, `cargo check`, `make` — it runs once at the end of a turn that
changed a file, and a failure is handed back with one turn to fix it. "Done"
then means "done, and the project still works", which is a different claim and
the one people actually want.

Four rules, and each is a way this could be worse than nothing.

*Only when something changed.* A turn that read files and answered a question
has nothing to verify, and running a suite for it is a minute of somebody's
time for no information.

*Once, then hand it back.* Not a loop. A model that cannot fix the failure on
its first try will not fix it on its fifth, and the user is better off being
told plainly than watching it spend their money.

*Bounded.* A command with no ceiling can hang a turn forever, which is worse
than a failing check.

*It never becomes the error.* If the command cannot be run at all — not found,
no shell, no permission — that is said once and the turn ends as it would have.
A verifier that turns a finished task into a failure is a verifier people
switch off.
"""

from __future__ import annotations

import ast
import os
import re
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

#: How long the project's own check may take before it is given up on. Long
#: enough for a real suite, short enough that a hung command is reported rather
#: than waited on.
PATIENCE = 600.0

#: How much of the output travels back to the model. A failing suite can print
#: megabytes, and the useful part is at the end.
MOST = 6000


@dataclass(frozen=True)
class Outcome:
    """What the project's own check said."""

    ran: bool
    passed: bool
    output: str
    #: Set when the command could not be run at all, as opposed to failing.
    unusable: str = ""

def _end_the_group(child: "subprocess.Popen") -> None:
    """Kill the check and everything it started. Never raises.

    `pytest` starting workers, `npm` starting a bundler: killing only the
    shell leaves those behind, running against the user's project after the
    turn that started them has been abandoned.
    """
    try:
        if hasattr(os, "killpg"):
            group = os.getpgid(child.pid)
            # Only a group the check has to itself. `start_new_session` above
            # gives it one, but if that ever stops happening the child shares
            # ours, and killing that group would end the agent along with the
            # command it was running. The signal cannot be taken back, so the
            # condition is checked rather than trusted.
            if group != os.getpgid(0):
                os.killpg(group, signal.SIGKILL)
                return
    except (OSError, AttributeError, ProcessLookupError):
        pass
    try:
        # Windows: taskkill walks the tree, which Popen.kill does not.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(child.pid)],
                       capture_output=True, timeout=10)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        child.kill()
    except OSError:
        pass


def run(command: str, cwd: Path, patience: float = PATIENCE) -> Outcome:
    """Run the project's check and say what happened. Never raises."""
    if not command.strip():
        return Outcome(ran=False, passed=True, output="")

    environment = dict(os.environ)
    # A check that shells out to the agent would be a loop with a bill on it.
    environment["COMODOR_VERIFYING"] = "1"

    # `shell=True` means the process started here is a shell, and the check is
    # its child. Killing the shell on a timeout leaves that child running and
    # holding the pipes open, so the read below goes on blocking — `patience`
    # was a ceiling on nothing, and the message said "no result within 2s"
    # after waiting twenty. The whole group has to go, which needs the platform
    # to have been told to make one.
    # Written out rather than gathered into a dict and splatted: this argument
    # is the difference between ending the check and ending the agent, and it
    # should be readable as such at the call — by a person, and by anything
    # checking that every `Popen` beside a `killpg` has one.
    try:
        child = subprocess.Popen(
            command, shell=True, cwd=str(cwd), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
            start_new_session=(os.name != "nt"),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                           if os.name == "nt" else 0))
    except (OSError, ValueError) as problem:
        return Outcome(ran=False, passed=True, output="",
                       unusable=f"{type(problem).__name__}: {problem}")

    try:
        finished_out, finished_err = child.communicate(timeout=patience)
    except subprocess.TimeoutExpired:
        _end_the_group(child)
        # Drained after the group is gone, so nothing is still writing into a
        # pipe nobody will read. It cannot block now: every writer is dead.
        try:
            child.communicate(timeout=10)
        except Exception:
            pass
        return Outcome(ran=True, passed=False,
                       output=f"(no result within {patience:.0f}s)")
    except (OSError, ValueError) as problem:
        _end_the_group(child)
        return Outcome(ran=False, passed=True, output="",
                       unusable=f"{type(problem).__name__}: {problem}")

    finished = subprocess.CompletedProcess(
        command, child.returncode, finished_out, finished_err)
    output = ((finished.stdout or "") + (finished.stderr or "")).strip()
    if len(output) > MOST:
        output = "…\n" + output[-MOST:]
    return Outcome(ran=True, passed=finished.returncode == 0, output=output)


def as_correction(command: str, outcome: Outcome) -> str:
    """What the model is told when the project's check fails.

    Phrased as a fact and a request, not as an accusation. The model is not
    being told it lied — it is being shown the output of something it did not
    run, which is exactly the information it was missing.
    """
    return (
        f"`{command}` fails after your changes:\n\n"
        f"{outcome.output}\n\n"
        f"Fix the cause. If the failure is not something your change caused, "
        f"say so plainly and leave it alone — do not change unrelated code to "
        f"make a command pass."
    )


# --------------------------------------------------------------------------- #
# the completion gate: request versus delivery (IP-4, FR-036 to FR-043,
# FR-124 to FR-127)
# --------------------------------------------------------------------------- #
#
# This is a return value computed at the end of a turn, never durable state.
# The default authority is to *annotate*: unresolved work is named beside the
# answer and the user is never denied what the agent did produce. The one
# blocking case is an answer that explicitly claims completion while the
# gathered evidence contradicts it (FR-125); blocking costs at most one
# correction turn (FR-127). A gate that cannot reach a verdict annotates.

#: A line that names one requested thing: a bullet or a numbered item.
_ELEMENT = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<what>.+?)\s*$")

#: Words too common to identify an element by.
_UNINFORMATIVE = frozenset("""
a an and are as at be by do does for from get in into is it its make made of on or
please should so that the their them then there these this to up us use used with
you your add added fix fixed change changed update updated new
""".split())

#: Verbs that ask for an artifact to change. An observation of the file is not
#: evidence that the change happened: reading `foo.py` does not delete it
#: (FR-036, FR-116).
_MUTATION = re.compile(
    r"(?i)\b(create|write|add|change|replace|rename|move|copy|duplicate|delete|"
    r"remove|update|fix|implement|refactor|migrate|generate)\b")

#: Verbs whose evidence has to match the operation, not just the path: an edit
#: to `foo.py` is not a delete of it, and a write is not a rename.
_DESTRUCTIVE = re.compile(r"(?i)\b(delete|remove)\b")
_MOVE = re.compile(r"(?i)\b(rename|move)\b")
#: A `run_python` rename/move, for move evidence. Shell moves go through the
#: structured scanner below; Python keeps its reviewed text reading.
_MOVE_COMMAND = re.compile(r"(?i)\b(mv|move|rename|git mv)\b")

#: Tools that only look. Their output cannot satisfy a mutation request, so
#: it is not counted as delivery for one.
_READ_ONLY_TOOLS = frozenset({
    "read_file", "list_dir", "glob", "grep", "web_fetch", "web_search",
    "browse", "search_history", "read_skill_file", "mcp_read_resource",
})

#: Commands that change the filesystem, for destructive and move evidence.
_COMMAND_TOOLS = frozenset({"run_shell", "run_python"})

#: Tools whose result is a change to a file.
_WRITER_TOOLS = frozenset({"write_file", "edit_file"})


#: A Python statement that writes. `run_python` is not a shell, so the shell
#: operators do not describe it. An `open()` writes in any mode that can
#: write: `w`, `a`, `x` with their `b`, `t` and `+` suffixes, and `r+`.
_PYTHON_MUTATION = re.compile(
    r"(?i)(\.write_text\s*\(|\.write_bytes\s*\(|\.writelines\s*\(|"
    r"\.unlink\s*\(|\.rename\s*\(|\.replace\s*\(|\.touch\s*\(|\.mkdir\s*\(|"
    r"\bopen\s*\([^)]*['\"](?:[wax][bt+]*|r[bt]*\+[bt]*)['\"]|"
    r"\bos\.(remove|unlink|rename|replace|rmdir|mkdir|makedirs)\s*\(|"
    r"\bshutil\.(move|copy|copy2|copyfile|rmtree|make_archive)\s*\()")

#: A path-looking target: a token with a file extension or a path separator.
_PATH_ISH = re.compile(r"(?:[\w.-]*[/\\][\w./\\-]*)|\b[\w-]+\.[A-Za-z0-9]{1,8}\b")


def _unquoted(command: str) -> str:
    """The command with quoted spans and comments removed, for operator detection.

    `grep '> ' foo.py` searches for a string, and `cat foo.py # > backup`
    never redirects: a `>` counts only outside quotes and outside a comment.
    A comment starts at a `#` that begins a word (after whitespace or an
    operator) outside quotes — `$#` and `foo#bar` are not comments.
    """
    kept: list[str] = []
    for line in (command or "").splitlines(keepends=True):
        single = double = False
        previous = " "
        out: list[str] = []
        for char in line:
            if char == "'" and not double:
                single = not single
                out.append(" ")
            elif char == '"' and not single:
                double = not double
                out.append(" ")
            elif single or double:
                out.append(" ")
            elif char == "#" and previous in " \t;|&(":
                out.append("\n" if line.endswith("\n") else "")
                break
            else:
                out.append(char)
            previous = char
        kept.append("".join(out))
    return "".join(kept)


#: Characters that may follow a heredoc delimiter word: end of line, whitespace
#: or a shell separator. A character outside this set means the delimiter word
#: continues past what this bounded reader parses — `<<E-O-F` is not `<<E` — so
#: the declaration is left unplaced rather than truncated.
_HEREDOC_BOUNDARY = frozenset(" \t\r\n\v\f;|&()<>")


def _heredoc_marker(line: str, start: int) -> tuple[str, bool, int] | None:
    """`(delimiter, strip_tabs, end)` for the heredoc operator at `start`.

    `start` is the first `<` of a `<<`; `end` is the index just past the
    delimiter. The `-` form (`<<-`) is returned with `strip_tabs` true. A
    delimiter that cannot be read — an expansion, a bare operator, a `<<<`
    here-string, or a word this bounded reader would have to truncate — is
    `None`, so the caller leaves the form unplaced and discards its body.
    """
    index = start + 2
    strip_tabs = False
    if index < len(line) and line[index] == "-":
        strip_tabs = True
        index += 1
    while index < len(line) and line[index] in " \t":
        index += 1
    quote = ""
    if index < len(line) and line[index] in "'\"":
        quote = line[index]
        index += 1
    begin = index
    while index < len(line) and (line[index].isalnum() or line[index] == "_"):
        index += 1
    delimiter = line[begin:index]
    if not delimiter or not (delimiter[0].isalpha() or delimiter[0] == "_"):
        return None
    if quote:
        if index >= len(line) or line[index] != quote:
            return None
        index += 1
    if index < len(line) and line[index] not in _HEREDOC_BOUNDARY:
        # `<<E-O-F` continues with a character not read here. Accepting the
        # prefix `E` would let a body line `E` end the heredoc early and expose
        # the rest of the body as commands, so the declaration is unplaced.
        return None
    return delimiter, strip_tabs, index


def _heredoc_declarations(line: str) -> list[tuple[str, bool]]:
    """The `(delimiter, strip_tabs)` of every heredoc declared on one line.

    Scanned outside quotes and comments, so `echo "<<EOF"` and `# cat <<EOF`
    declare nothing. A `<<` whose delimiter cannot be read is returned as
    `("", False)`: an unplaceable declaration, whose body the caller discards
    rather than reads as commands.
    """
    found: list[tuple[str, bool]] = []
    index = 0
    length = len(line)
    previous = " "
    while index < length:
        char = line[index]
        if char == "\\":
            index += 2
            previous = char
            continue
        if char in "'\"":
            end = line.find(char, index + 1)
            index = length if end < 0 else end + 1
            previous = char
            continue
        if char == "#" and previous in " \t;|&(":
            break
        if char == "<" and line.startswith("<<", index) \
                and not line.startswith("<<<", index):
            parsed = _heredoc_marker(line, index)
            if parsed is None:
                return [*found, ("", False)]
            delimiter, strip_tabs, index = parsed
            found.append((delimiter, strip_tabs))
            previous = " "
            continue
        previous = char
        index += 1
    return found


def shell_evidence_text(command: str) -> str:
    """Shell text with heredoc *bodies* removed and headers kept.

    A heredoc body is stdin data, not commands: `cat <<EOF` followed by a line
    `rm foo.py` deletes nothing, and a line `foo.py` inside the body is not a
    path this command touched. The header line — including the `<<EOF` marker
    and any real output redirection on it — is kept, so `cat > deploy.sh <<EOF`
    still reads as a write of `deploy.sh`; the terminator is removed with the
    body. A declaration whose delimiter cannot be read, or one that is never
    terminated, discards the remaining text: an unplaceable form becomes a
    false negative, never false evidence. Every consumer of shell command text
    (operation classification, completion keyword evidence, learning
    staleness) reads it through here, so the body cannot leak into one and not
    another.
    """
    if not command or "<<" not in command:
        return command
    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.splitlines(keepends=True):
        if pending:
            delimiter, strip_tabs = pending[0]
            candidate = line.rstrip("\r\n")
            if strip_tabs:
                candidate = candidate.lstrip("\t")
            if delimiter and candidate == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend(_heredoc_declarations(line))
    return "".join(kept)


#: Command words that delete, move and write. Recognised only in command
#: position — never as an argument, so `grep rm foo.py` reads.
_DELETE_COMMANDS = frozenset({"rm", "rmdir", "del", "erase", "unlink", "trash"})
_MOVE_COMMANDS = frozenset({"mv", "move", "rename"})
_WRITE_COMMANDS = frozenset({"cp", "copy", "xcopy", "robocopy", "tee",
                             "truncate", "touch"})
#: Prefixes that run the command after them. A bounded set: the wrapper is
#: skipped and the verb is the next non-option word. `command`/`builtin` are
#: deliberately absent — `command -v rm` queries rather than deletes.
_WRAPPERS = frozenset({"env", "sudo", "nohup", "time", "exec"})
#: Wrapper options that take the following word as their value, by wrapper.
_WRAPPER_VALUE_OPTIONS = {
    "sudo": frozenset({"-u", "-g", "-p", "-C", "-D", "-r", "-t", "-U", "-T",
                       "-R", "--user", "--group", "--prompt", "--chdir",
                       "--unset", "--set-home"}),
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
}
#: git global options that take the following word as their value.
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree",
                                "--namespace", "--exec-path"})
#: A shell word that is an environment assignment (`KEY=value`).
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: The control operators that separate one command from the next.
_SEGMENT = re.compile(r"[;&|(){}\n]+")


@dataclass(frozen=True)
class ShellOperations:
    """What one raw shell command does to the filesystem, by operation."""

    writes: bool = False
    deletes: bool = False
    moves: bool = False


def _effective_command(tokens: list[str]) -> tuple[str, list[str]]:
    """The command word of a segment, after assignments and simple wrappers.

    `KEY=value rm foo.py`, `env -i rm foo.py` and `sudo -u user rm foo.py` all
    name `rm`. The verb is taken by basename and lowercased, so `/bin/rm` is
    `rm`. An unrecognised first word is the verb, whatever it is — the reader
    does not guess through `xargs`, `find -exec` or nested interpreters.
    """
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _ASSIGNMENT.match(token):
            index += 1
            continue
        base = token.rsplit("/", 1)[-1].lower()
        if base not in _WRAPPERS:
            return base, tokens[index + 1:]
        values = _WRAPPER_VALUE_OPTIONS.get(base, frozenset())
        index += 1
        while index < len(tokens):
            following = tokens[index]
            if _ASSIGNMENT.match(following):
                index += 1
                continue
            if following.startswith("-"):
                index += 2 if following in values else 1
                continue
            break
    return "", []


def _git_subcommand(tokens: list[str]) -> tuple[str, list[str]]:
    """The git subcommand, after git's own global options."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _GIT_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token.rsplit("/", 1)[-1].lower(), tokens[index + 1:]
    return "", []


def _is_in_place(token: str) -> bool:
    """Whether a `sed` argument is the in-place flag (`-i`, `-i.bak`,
    `--in-place`)."""
    return token.startswith(("-i", "--in-place"))


def _has_output_redirection(masked: str) -> bool:
    """Whether quote/comment-stripped shell text redirects output to a file.

    A `>` (or `>>`, or `>|`) with something after it that is not `&` is a
    write: `>file`, `> file`, `2>errors.log`, `>>log`, `1>out`. Descriptor
    duplication (`2>&1`, `2> &1`), process substitution (`>(cmd)`, `> >(cmd)`)
    and a dangling `>` are not, and an escaped `\\>` is a literal. Input
    `<`/`<<` never appears here, and quoting and comments were already removed
    by `_unquoted`.
    """
    index = 0
    length = len(masked)
    while index < length:
        if masked[index] != ">":
            index += 1
            continue
        backslashes = 0
        before = index - 1
        while before >= 0 and masked[before] == "\\":
            backslashes += 1
            before -= 1
        if backslashes % 2 == 1:          # `a\>b` is a literal `>`
            index += 1
            continue
        after = index + 1
        if after < length and masked[after] == ">":
            after += 1
        if after < length and masked[after] == "|":
            after += 1
        while after < length and masked[after] in " \t":
            after += 1                    # `> file` and `2> errors.log`
        if after >= length:               # a dangling `>` redirects nothing
            index = after
            continue
        if masked[after] == "&":          # `2>&1` and `2> &1` duplicate a descriptor
            index = after + 1
            continue
        if masked[after] == "(":          # `>(cmd)` is process substitution
            index = after + 1
            continue
        if masked[after] == ">" and after + 1 < length \
                and masked[after + 1] == "(":
            index = after + 2             # `> >(cmd)` is process substitution
            continue
        return True
    return False


def shell_operations(command: str) -> ShellOperations:
    """What a raw shell command does, read as a sequence of command words.

    The command is split on the control operators that separate one command
    from the next (`;`, `&&`, `||`, `|`, `&`, newlines, subshell brackets) and
    each segment's effective verb is classified. An operation word in argument
    position is not an operation: `grep rm foo.py` reads, `printf rename x`
    prints. Heredoc bodies are removed first (`shell_evidence_text`), so a line
    of stdin data is not read as a command. Output redirection is detected
    separately, from the same quote- and comment-stripped text. A form this
    bounded reader cannot place is left unknown — a false negative, never
    false evidence.
    """
    masked = _unquoted(shell_evidence_text(command or ""))
    writes = deletes = moves = False
    for segment in _SEGMENT.split(masked):
        verb, rest = _effective_command(segment.split())
        if not verb:
            continue
        if verb == "git":
            verb, rest = _git_subcommand(rest)
        if verb in _DELETE_COMMANDS:
            deletes = writes = True
        elif verb in _MOVE_COMMANDS:
            moves = writes = True
        elif verb in _WRITE_COMMANDS:
            writes = True
        elif verb == "sed" and any(_is_in_place(word) for word in rest):
            writes = True
    if _has_output_redirection(masked):
        writes = True
    return ShellOperations(writes=writes, deletes=deletes, moves=moves)


def shell_writes(command: str) -> bool:
    """Whether a raw shell command changes the filesystem."""
    return shell_operations(command).writes


def shell_deletes(command: str) -> bool:
    """Whether a raw shell command deletes a filesystem entry."""
    return shell_operations(command).deletes


def shell_moves(command: str) -> bool:
    """Whether a raw shell command moves or renames a filesystem entry."""
    return shell_operations(command).moves


def _shell_command(claim: str) -> str:
    """The raw shell command inside an evidence claim.

    A `run_shell` claim is `<tool> <command>`; some callers carry the display
    summary instead (`run_shell run: <command>`). Both are stripped
    deterministically, so `run_shell` and `run:` never take part in command
    classification.
    """
    text = (claim or "").strip()
    if text.startswith("run_shell"):
        text = text[len("run_shell"):].lstrip()
    if text.startswith("run:"):
        text = text[len("run:"):].lstrip()
    return text


def _python_code(code: str) -> str:
    """Python source with comments removed, for mutation detection.

    A commented-out write (`# Path("foo.py").write_text(...)`) is not a write.
    Quotes are tracked per line so a `#` inside a string is not a comment.
    """
    kept: list[str] = []
    for line in (code or "").splitlines():
        single = double = False
        cut = len(line)
        for index, char in enumerate(line):
            if char == "'" and not double:
                single = not single
            elif char == '"' and not single:
                double = not double
            elif char == "#" and not single and not double:
                cut = index
                break
        kept.append(line[:cut])
    return "\n".join(kept)


#: The pathlib classes that build a filesystem path. A path delete is a method
#: call on a value built from one of these; a method of the same name on any
#: other receiver — `SharedMemory(...).unlink()` — deletes no file.
_PATH_CLASSES = frozenset({
    "Path", "PurePath", "PosixPath", "WindowsPath",
    "PurePosixPath", "PureWindowsPath",
})
#: os functions that write, and the subset that deletes. A delete is also a
#: write; the destructive check needs the narrower set, because an ordinary
#: write must not satisfy a delete request.
_OS_WRITES = frozenset({"remove", "unlink", "rename", "replace", "rmdir",
                        "mkdir", "makedirs"})
_OS_DELETES = frozenset({"remove", "unlink", "rmdir"})
#: shutil functions that write, and the subset that deletes.
_SHUTIL_WRITES = frozenset({"move", "copy", "copy2", "copyfile", "rmtree",
                            "make_archive"})
_SHUTIL_DELETES = frozenset({"rmtree"})
#: pathlib methods that write, and the subset that deletes. The delete set is
#: deliberately narrower: `write_text` is a write and not a delete.
_PATHLIB_WRITES = frozenset({"write_text", "write_bytes", "unlink", "rename",
                             "replace", "touch", "mkdir", "rmdir"})
_PATHLIB_DELETES = frozenset({"unlink", "rmdir"})
#: A method on an open file handle that writes. Receiver-blind, as it always
#: was: `writelines` is a write whatever it is called on, and it is not a
#: delete, so it needs no receiver resolution.
_HANDLE_WRITES = frozenset({"writelines"})
#: An `open()` mode that can write.
_WRITABLE_MODE = re.compile(r"^(?:[wax][bt+]*|r[bt]*\+[bt]*)$")
#: The delete forms, as text, for source that does not parse. Deliberately
#: narrower than `_PYTHON_MUTATION`: only the calls that actually delete.
_PYTHON_DELETE_TEXT = re.compile(
    r"(?i)(\.unlink\s*\(|\.rmdir\s*\(|"
    r"\bos\.(remove|unlink|rmdir)\s*\(|"
    r"\bshutil\.rmtree\s*\()")


def _opens_for_writing(call: ast.Call) -> bool:
    mode: ast.expr | None = call.args[1] if len(call.args) > 1 else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return False
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
        and bool(_WRITABLE_MODE.match(mode.value))


#: A binding event that may be relied upon: a filesystem module, a
#: from-imported filesystem function, a pathlib class, or a path value.
_FS_EVENTS = frozenset({"module", "from", "path_class", "path"})

#: The name is bound in the scope, but not to a filesystem binding: the search
#: for what it names stops here instead of looking outward.
_SHADOWED = object()


def _parameter_names(args: ast.arguments) -> list[str]:
    """Every name a function or lambda binds as a parameter."""
    names = [arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _pattern_names(node: ast.AST) -> list[str]:
    """Names a `match` pattern binds, for the binding forms that name one."""
    if isinstance(node, ast.MatchAs) and node.name:
        return [node.name]
    if isinstance(node, ast.MatchStar) and node.name:
        return [node.name]
    if isinstance(node, ast.MatchMapping) and node.rest:
        return [node.rest]
    return []


class _Scope:
    """One lexical scope's names, and what each is bound to.

    Bindings are order-insensitive and conservative. A name bound more than
    once to different things — an import rebound by an assignment, a parameter
    or a `def` of the same name — is treated as unknown, so the filesystem
    operation the import named is never the one a later call is taken to be.
    """

    __slots__ = ("parent", "kind", "events", "_assignments")

    def __init__(self, parent: "_Scope | None", kind: str) -> None:
        self.parent = parent
        self.kind = kind
        self.events: dict[str, set[tuple]] = {}
        self._assignments: list[tuple[str, ast.expr | None]] = []

    def add(self, name: str, event: tuple) -> None:
        self.events.setdefault(name, set()).add(event)

    def assign(self, name: str, value: ast.expr | None) -> None:
        """Record an assignment target; classified once every binding is in."""
        self._assignments.append((name, value))

    def function_parent(self) -> "_Scope | None":
        """The scope a function or lambda defined here closes over.

        A class body is not an enclosing scope for the functions defined in
        it, so a method closes over the class's parent, not the class.
        """
        scope: "_Scope | None" = self
        while scope is not None and scope.kind == "class":
            scope = scope.parent
        return scope

    def resolve(self, name: str):
        """What `name` is bound to here or outward.

        The filesystem event when the nearest binding is one; `_SHADOWED` when
        the nearest binding is anything else, or is ambiguous; None when no
        scope on the chain binds it.
        """
        scope: "_Scope | None" = self
        while scope is not None:
            events = scope.events.get(name)
            if events is not None:
                if len(events) == 1:
                    event = next(iter(events))
                    if event[0] in _FS_EVENTS:
                        return event
                return _SHADOWED
            scope = scope.parent
        return None

    def classify(self, scanner: "_PythonScan") -> None:
        """Turn recorded assignment targets into binding events."""
        for name, value in self._assignments:
            if value is not None and scanner._is_path_call(value, self):
                self.add(name, ("path",))
            else:
                self.add(name, ("other",))


class _PythonScan:
    """What Python source, as it would execute, writes and deletes.

    One bounded, lexical-scope-aware resolution shared by `python_writes` and
    `python_deletes`, so the two agree that a recognised delete is a recognised
    write.

    Imports resolve to the module function they name (`from os import remove as
    rmfile` is `os.remove`), and a binding is used only where it is in scope: a
    parameter named `os`, a `def remove`, an assignment that rebinds an alias,
    or an import in a sibling function never makes a call filesystem evidence.
    A pathlib delete counts only when the receiver is established as a path —
    built directly (`Path("x").unlink()`) or through a simple `p = Path("x")`
    binding. A name bound to two different things is left unknown and fails
    conservatively.
    """

    def __init__(self, tree: ast.AST) -> None:
        self.writes = False
        self.deletes = False
        self._scopes: dict[int, _Scope] = {}
        self._all_scopes: list[_Scope] = []
        root = self._new_scope(None, "module")
        self._collect(tree, root)
        for scope in self._all_scopes:
            scope.classify(self)
        self._calls(tree, root)

    # -- scope construction ----------------------------------------------- #

    def _new_scope(self, parent: "_Scope | None", kind: str) -> _Scope:
        scope = _Scope(parent, kind)
        self._all_scopes.append(scope)
        return scope

    def _collect(self, node, scope: _Scope) -> None:
        """Record every name `scope` binds and build its child scopes."""
        if isinstance(node, list):
            for item in node:
                self._collect(item, scope)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.add(node.name, ("other",))
            self._collect(node.decorator_list, scope)
            self._collect_defaults(node.args, scope)
            child = self._new_scope(scope.function_parent(), "function")
            for name in _parameter_names(node.args):
                child.add(name, ("other",))
            self._collect(node.body, child)
            self._scopes[id(node)] = child
            return
        if isinstance(node, ast.Lambda):
            self._collect_defaults(node.args, scope)
            child = self._new_scope(scope.function_parent(), "lambda")
            for name in _parameter_names(node.args):
                child.add(name, ("other",))
            self._collect(node.body, child)
            self._scopes[id(node)] = child
            return
        if isinstance(node, ast.ClassDef):
            scope.add(node.name, ("other",))
            self._collect(node.decorator_list, scope)
            self._collect(node.bases, scope)
            self._collect([keyword.value for keyword in node.keywords], scope)
            child = self._new_scope(scope, "class")
            self._collect(node.body, child)
            self._scopes[id(node)] = child
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                scope.add(alias.asname or top, ("module", top))
            return
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if module == "pathlib" and alias.name in _PATH_CLASSES:
                    scope.add(local, ("path_class", module, alias.name))
                else:
                    scope.add(local, ("from", module, alias.name))
            return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                self._bind_target(target, node.value, scope)
            self._collect(node.value, scope)
            return
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self._bind_target(node.target, node.value, scope)
                self._collect(node.value, scope)
            return
        if isinstance(node, ast.AugAssign):
            self._bind_target(node.target, None, scope)
            self._collect(node.value, scope)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self._bind_target(node.target, None, scope)
            self._collect(node.iter, scope)
            self._collect(node.body, scope)
            self._collect(node.orelse, scope)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self._collect(item.context_expr, scope)
                if item.optional_vars is not None:
                    self._bind_target(item.optional_vars, None, scope)
            self._collect(node.body, scope)
            return
        if isinstance(node, ast.ExceptHandler):
            if node.name:
                scope.add(node.name, ("other",))
            self._collect(node.body, scope)
            return
        if isinstance(node, ast.NamedExpr):
            self._bind_target(node.target, node.value, scope)
            self._collect(node.value, scope)
            return
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            # A name declared global/nonlocal is not this scope's to resolve
            # from an import here; treat it as unknown, the safe side.
            for name in node.names:
                scope.add(name, ("other",))
            return
        if isinstance(node, ast.Delete):
            for target in node.targets:
                self._bind_target(target, None, scope)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                             ast.DictComp)):
            self._collect_comprehension(node, scope)
            return
        for name in _pattern_names(node):
            scope.add(name, ("other",))
        for child in ast.iter_child_nodes(node):
            self._collect(child, scope)

    def _collect_defaults(self, args: ast.arguments, scope: _Scope) -> None:
        self._collect(args.defaults, scope)
        self._collect([d for d in args.kw_defaults if d is not None], scope)

    def _collect_comprehension(self, node, scope: _Scope) -> None:
        child = self._new_scope(scope.function_parent(), "comprehension")
        for generator in node.generators:
            self._bind_target(generator.target, None, child)
            self._collect(generator.iter, child)
            for condition in generator.ifs:
                self._collect(condition, child)
        if isinstance(node, ast.DictComp):
            self._collect(node.key, child)
            self._collect(node.value, child)
        else:
            self._collect(node.elt, child)
        self._scopes[id(node)] = child

    def _bind_target(self, target: ast.expr, value: ast.expr | None,
                     scope: _Scope) -> None:
        if isinstance(target, ast.Name):
            scope.assign(target.id, value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind_target(element, None, scope)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value, None, scope)

    # -- call classification ---------------------------------------------- #

    def _calls(self, node, scope: _Scope) -> None:
        if isinstance(node, list):
            for item in node:
                self._calls(item, scope)
            return
        if isinstance(node, ast.Call):
            self._classify_call(node, scope)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._calls(node.decorator_list, scope)
            self._calls_defaults(node.args, scope)
            self._calls(node.body, self._scopes[id(node)])
            return
        if isinstance(node, ast.Lambda):
            self._calls_defaults(node.args, scope)
            self._calls(node.body, self._scopes[id(node)])
            return
        if isinstance(node, ast.ClassDef):
            self._calls(node.decorator_list, scope)
            self._calls(node.bases, scope)
            self._calls([keyword.value for keyword in node.keywords], scope)
            self._calls(node.body, self._scopes[id(node)])
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                             ast.DictComp)):
            self._calls_comprehension(node, scope)
            return
        for child in ast.iter_child_nodes(node):
            self._calls(child, scope)

    def _calls_defaults(self, args: ast.arguments, scope: _Scope) -> None:
        self._calls(args.defaults, scope)
        self._calls([d for d in args.kw_defaults if d is not None], scope)

    def _calls_comprehension(self, node, scope: _Scope) -> None:
        child = self._scopes[id(node)]
        generators = node.generators
        if generators:
            # The first iterable is evaluated in the enclosing scope.
            self._calls(generators[0].iter, scope)
        for generator in generators[1:]:
            self._calls(generator.iter, child)
        for generator in generators:
            for condition in generator.ifs:
                self._calls(condition, child)
        if isinstance(node, ast.DictComp):
            self._calls(node.key, child)
            self._calls(node.value, child)
        else:
            self._calls(node.elt, child)

    def _classify_call(self, node: ast.Call, scope: _Scope) -> None:
        target = node.func
        if isinstance(target, ast.Name):
            if target.id == "open" and scope.resolve("open") is None \
                    and _opens_for_writing(node):
                self.writes = True
                return
            imported = self._from_import_of(target.id, scope)
            if imported is not None:
                module, original = imported
                if module == "os" and original in _OS_WRITES:
                    self.writes = True
                    self.deletes = self.deletes or original in _OS_DELETES
                elif module == "shutil" and original in _SHUTIL_WRITES:
                    self.writes = True
                    self.deletes = self.deletes or original in _SHUTIL_DELETES
            return
        if isinstance(target, ast.Attribute):
            self._method_call(target, scope)

    def _from_import_of(self, name: str, scope: _Scope):
        """The (module, function) a from-imported name stands for, or None."""
        binding = scope.resolve(name)
        if binding is None or binding is _SHADOWED:
            return None
        return (binding[1], binding[2]) if binding[0] == "from" else None

    def _module_of(self, name: str, scope: _Scope) -> str:
        """The canonical module a name stands for, or "" if it is not one.

        `os`, `shutil` and `pathlib` are recognised by their own names when no
        scope binds them, as the detector always did; an alias resolves through
        the import that bound it, and a shadowing binding stops the search.
        """
        binding = scope.resolve(name)
        if binding is None:
            return name if name in ("os", "shutil", "pathlib") else ""
        if binding is _SHADOWED:
            return ""
        return binding[1] if binding[0] == "module" else ""

    def _path_class_of(self, name: str, scope: _Scope):
        """The (module, class) a pathlib class name stands for, or None."""
        binding = scope.resolve(name)
        if binding is None:
            return ("pathlib", name) if name in _PATH_CLASSES else None
        if binding is _SHADOWED:
            return None
        return (binding[1], binding[2]) if binding[0] == "path_class" else None

    def _is_path_call(self, node: ast.expr, scope: _Scope) -> bool:
        """Whether `node` builds a pathlib path: `Path("x")`, `P("x")`,
        `pathlib.Path("x")`, `pl.Path("x")`."""
        if not isinstance(node, ast.Call):
            return False
        target = node.func
        if isinstance(target, ast.Name):
            return self._path_class_of(target.id, scope) is not None
        if isinstance(target, ast.Attribute):
            return target.attr in _PATH_CLASSES \
                and isinstance(target.value, ast.Name) \
                and self._module_of(target.value.id, scope) == "pathlib"
        return False

    def _receiver_is_path(self, node: ast.expr, scope: _Scope) -> bool:
        if isinstance(node, ast.Name):
            return scope.resolve(node.id) == ("path",)
        return self._is_path_call(node, scope)

    def _method_call(self, target: ast.Attribute, scope: _Scope) -> None:
        attr = target.attr
        receiver = target.value
        if isinstance(receiver, ast.Name):
            module = self._module_of(receiver.id, scope)
            if module == "os" and attr in _OS_WRITES:
                self.writes = True
                self.deletes = self.deletes or attr in _OS_DELETES
                return
            if module == "shutil" and attr in _SHUTIL_WRITES:
                self.writes = True
                self.deletes = self.deletes or attr in _SHUTIL_DELETES
                return
            if module == "pathlib" and attr in _PATH_CLASSES:
                return                        # `pathlib.Path(...)`, a constructor
        if attr in _HANDLE_WRITES:
            self.writes = True                # `handle.writelines(...)`
            return
        if attr in _PATHLIB_WRITES:
            # A path method name is a write, as the detector always read it;
            # it is a delete only when the receiver is established as a path,
            # so `SharedMemory(...).unlink()` deletes no file. A recognised
            # delete is always a recognised write.
            self.writes = True
            if attr in _PATHLIB_DELETES and self._receiver_is_path(receiver, scope):
                self.deletes = True


def _python_operations(code: str) -> tuple[bool, bool]:
    """(writes, deletes) that Python source performs, as it would execute.

    Source that does not parse could not have run, and is read by the text
    patterns as a last resort.
    """
    try:
        tree = ast.parse(code or "")
    except (SyntaxError, ValueError):
        text = _python_code(code)
        return (bool(_PYTHON_MUTATION.search(text)),
                bool(_PYTHON_DELETE_TEXT.search(text)))
    scan = _PythonScan(tree)
    return scan.writes, scan.deletes


def python_writes(code: str) -> bool:
    """Whether Python source, as it would execute, changes the filesystem.

    The calls are read from the syntax tree, so a write mentioned inside a
    string or a comment — `print('Path("foo.py").write_text("new")')` — is
    not a write: only an executable call node counts. An aliased or
    from-imported os/shutil function resolves to what it names, in the lexical
    scope that binds it, so a shadowing parameter, `def` or assignment is not
    read as the import. `open()` writes when its mode is a literal that can
    write; a mode that is not a literal is not evidence of a write. Source that
    does not parse could not have run, and is read by the text pattern as a
    last resort.
    """
    return _python_operations(code)[0]


def python_deletes(code: str) -> bool:
    """Whether Python source, as it would execute, deletes a filesystem entry.

    Read from the syntax tree for the same reason `python_writes` is: a
    `print('os.remove("foo.py")')` mentions the call and performs nothing, so
    only an executable call node counts. `os.remove`, `shutil.rmtree` and the
    pathlib methods (`unlink`, `rmdir`) are deletes, through an alias or a
    from-import as well as a literal name, and only in the lexical scope that
    binds them; an ordinary write is not. A method of the same name on a
    receiver that is not an established path — a `SharedMemory`, or a name
    bound in another scope — is not a delete. Source that does not parse could
    not have run, and is read by the delete text pattern as a last resort.
    """
    return _python_operations(code)[1]


def command_mutates(command: str, tool: str = "run_shell") -> bool:
    """Whether a shell or Python command changes the filesystem."""
    if tool == "run_python":
        return python_writes(command)
    return shell_writes(command)


# --------------------------------------------------------------------------- #
# the validation oracle: which files are checks, and what weakens them
# --------------------------------------------------------------------------- #
#
# A green suite is only evidence of the requested behaviour if the suite still
# checks that behaviour. A model can make a failing check pass by fixing the
# implementation (valid), by correcting a demonstrably wrong expectation
# (valid), or by weakening the check until it stops failing (not valid). The
# preflight is the primary defense against the third; this is the bounded,
# deterministic reading of "this mutation changes the oracle" and "this change
# weakens it", used both to gate the mutation and to mark a validation run as
# not authoritative.

#: Directory names that mark the files under them as checks, not product code.
#: Deliberately narrow — a false positive here would make an ordinary source
#: edit look like a validator change. `spec/` is not included: this repository
#: keeps its own specification documents there, and a spec document is not a
#: validator.
_VALIDATION_DIRS = frozenset({"tests", "test", "__tests__"})
#: Directory names whose contents are recorded expectations.
_SNAPSHOT_DIRS = frozenset({"__snapshots__", "snapshots", "golden", "goldens"})

#: Filename shapes that are a check by convention, across the languages the
#: benchmark and the product actually use.
_VALIDATION_FILE = re.compile(
    r"(?i)^(?:"
    r"test_.*\.(?:py|js|jsx|ts|tsx|mjs|cjs|rb|go|java|kt|cs|rs|php)|"
    r".*_test\.(?:py|js|jsx|ts|tsx|mjs|cjs|rb|go|java|kt|cs|rs|php)|"
    r".*\.(?:test|spec)\.(?:js|jsx|ts|tsx|mjs|cjs)|"
    r".*\.snap|"
    r".*\.golden"
    r")$")

#: Test-runner configuration and fixtures that are a check by name. A config
#: file that merely happens to be `pyproject.toml` is only a validator when its
#: content touches test configuration, which `oracle_risk` decides from the
#: mutation text.
_VALIDATION_NAMES = frozenset({
    "conftest.py", "pytest.ini", "tox.ini", "nose.cfg", ".noserc",
    "jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs",
    "vitest.config.js", "vitest.config.ts", "vitest.config.mjs",
    "karma.conf.js",
})
#: Files that carry test configuration among other things.
_VALIDATION_CONFIG_NAMES = frozenset({"pyproject.toml", "setup.cfg"})
#: Content that makes a general config file a validation config.
_CONFIG_MARKERS = ("[tool.pytest", "[pytest]", "[tool.coverage", "[coverage:",
                   "testpaths", "addopts")


def validation_artifact(path: str) -> bool:
    """Whether `path` names a validation artifact — a check, not product code.

    A test directory, a `test_*`/`*_test`/`*.test.*`/`*.spec.*` file, a
    snapshot or golden expectation, a test fixture or a known test-runner
    config. General config (`pyproject.toml`) is only a validator when its
    content carries test configuration; that is decided by `oracle_risk` from
    the mutation text, so the path test alone does not classify it.
    """
    norm = str(path or "").replace("\\", "/").strip().lower()
    if not norm:
        return False
    parts = [part for part in norm.split("/") if part and part not in (".", "..")]
    if not parts:
        return False
    name = parts[-1]
    directories = parts[:-1]
    if any(part in _VALIDATION_DIRS for part in directories):
        return True
    if any(part in _SNAPSHOT_DIRS for part in directories):
        return True
    if name in _VALIDATION_NAMES:
        return True
    return bool(_VALIDATION_FILE.match(name))


def _paths_in(text: str) -> list[str]:
    """Path-looking tokens in a command or code string."""
    return [match for match in _PATH_ISH.findall(text or "") if match]


def mentions_validation_artifact(text: str) -> bool:
    """Whether a command or code string names a validation artifact."""
    for token in _paths_in(text):
        if validation_artifact(token):
            return True
    return False


#: Constructs that weaken a check: a skip, an expected failure, a collection
#: exclusion. High-confidence and bounded — each is a deliberate way to stop a
#: failing check from failing, and each is what the observed benchmark failure
#: used. They are evidence for the preflight, not a complete policy engine.
_WEAKENING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("skip", re.compile(r"(?i)\bpytest\s*\.\s*mark\s*\.\s*skip(?:if)?\b")),
    ("skip", re.compile(r"(?i)\bpytestmark\s*=\s*[^\n]*\bpytest\s*\.\s*mark\s*\.\s*skip")),
    ("skip", re.compile(r"(?i)\bpytest\s*\.\s*skip\s*\(")),
    ("skip", re.compile(r"(?i)\bunittest\s*\.\s*skip(?:If|Unless)?\b")),
    ("skip", re.compile(r"(?im)^\s*@\s*(?:unittest\s*\.\s*)?skip(?:If|Unless)?\b")),
    ("xfail", re.compile(r"(?i)\bpytest\s*\.\s*mark\s*\.\s*xfail\b")),
    ("xfail", re.compile(r"(?im)^\s*@\s*xfail\b")),
    ("deselect", re.compile(r"(?i)--deselect\b|--ignore(?:=|\s)|collect_ignore\b")),
)


def weakening_signals(text: str) -> list[str]:
    """The high-confidence weakening constructs in `text`, by name."""
    found: list[str] = []
    for name, pattern in _WEAKENING_PATTERNS:
        if pattern.search(text or "") and name not in found:
            found.append(name)
    return found


def _removal_signals(old: str, new: str) -> list[str]:
    """Weakening implied by an edit's before/after: a test or assertion removed."""
    found: list[str] = []
    if "def test_" in (old or "") and "def test_" not in (new or ""):
        found.append("deleted_test")
    if (old or "").count("assert") > (new or "").count("assert"):
        found.append("removed_assertion")
    return found


def oracle_risk(name: str, arguments: dict) -> tuple[bool, list[str]]:
    """Whether one mutating call touches a validator, and how it weakens it.

    Returns `(targets_a_validation_artifact, weakening_signals)`. A write or
    edit is judged by its path and its content (and, for an edit, by what it
    removes). A shell or Python command is judged by the validation artifacts
    its text names and the weakening constructs it contains. A call that names
    no validation artifact is not a validator change.
    """
    arguments = arguments or {}
    if name in ("write_file", "edit_file"):
        path = str(arguments.get("path") or "")
        content = str(arguments.get("content")
                      or arguments.get("new_string") or "")
        old = str(arguments.get("old_string") or "")
        target = validation_artifact(path)
        config = path.replace("\\", "/").rsplit("/", 1)[-1].lower() \
            in _VALIDATION_CONFIG_NAMES
        if config:
            # A general config file is a validator only when the change touches
            # test configuration; an unrelated dependency edit is not.
            target = target or any(marker in content.lower()
                                   for marker in _CONFIG_MARKERS)
        signals = weakening_signals(content)
        if old:
            signals += _removal_signals(old, content)
        return target, signals
    if name in ("run_shell", "run_python"):
        text = str(arguments.get("command") or arguments.get("code") or "")
        # Running the check is not changing it: only a command that actually
        # writes (or deletes) a validation artifact changes the oracle. A
        # command's text names many paths (an output file, an argument), so the
        # write must also carry a weakening signal or delete the artifact —
        # otherwise `pytest test_x.py > out.txt` would look like a change.
        if not command_mutates(text, name):
            return False, []
        if not mentions_validation_artifact(text):
            return False, []
        signals = weakening_signals(text)
        if name == "run_shell" and shell_deletes(text):
            signals.append("delete")
        if not signals:
            return False, []
        return True, signals
    return False, []


# --------------------------------------------------------------------------- #
# grounding a validator correction: a model's claim is not authority
# --------------------------------------------------------------------------- #
#
# The assessor may answer `grounded_validator_correction` and cite sources, but
# those are claims. Core decides whether they name an actual source, and whether
# a high-confidence weakening is authorised. A missing prerequisite is not
# evidence that the check is wrong; only the request or a real evidence ref can
# authorise changing a check.

#: A sentence, for the narrow request-authorization reading.
_REQUEST_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
#: A sentence that names a check.
_TEST_NOUN = re.compile(
    r"(?i)\b(?:test|tests|suite|check|checks|assertion|assertions|case|cases|"
    r"collection|collecting)\b")
#: A negation in the same sentence means it is not authorization.
_REQUEST_NEGATION = re.compile(r"(?i)(?:\b(?:not|never|without|avoid)\b|n't\b)")
#: The verb a high-confidence weakening signal corresponds to in a request.
_SIGNAL_AUTHORIZATION: dict[str, re.Pattern[str]] = {
    "skip": re.compile(r"(?i)\b(?:skip|skipping|skipif|xfail|disable|disabling|disabled)\b"),
    "xfail": re.compile(r"(?i)\b(?:skip|skipping|skipif|xfail|disable|disabling|disabled)\b"),
    "deselect": re.compile(r"(?i)\b(?:deselect|exclude|excluding|omit|omitting|stop|"
                           r"drop|dropping|collection|collecting)\b"),
    "delete": re.compile(r"(?i)\b(?:remove|removing|delete|deleting|drop|dropping)\b"),
    "deleted_test": re.compile(r"(?i)\b(?:remove|removing|delete|deleting|drop|dropping)\b"),
    "removed_assertion": re.compile(
        r"(?i)\b(?:remove|removing|delete|deleting|drop|dropping|loosen|loosening|"
        r"relax|relaxing)\b"),
}


def normalize_ref(ref: str) -> str:
    """A claimed source reduced to a comparable identity."""
    text = str(ref or "").strip().strip("`'\"").replace("\\", "/").lower()
    return " ".join(text.split())


def ref_matches(ref: str, allowed: Iterable[str]) -> bool:
    """Whether a claimed source names an actual available source.

    A claimed `validator_ref` counts only when it is the request or a real
    evidence ref supplied to the preflight — by full path or by basename. A
    convincing-sounding sentence names nothing and does not count.
    """
    wanted = normalize_ref(ref)
    if not wanted:
        return False
    if wanted == "request":
        return True
    wanted_base = wanted.rsplit("/", 1)[-1]
    for candidate in allowed or ():
        name = normalize_ref(candidate)
        if not name:
            continue
        if wanted == name:
            return True
        if wanted_base and wanted_base == name.rsplit("/", 1)[-1]:
            return True
        if name.endswith("/" + wanted) or wanted.endswith("/" + name):
            return True
    return False


def explicit_weakening_authorized(request: str, signals: Iterable[str]) -> bool:
    """Whether the request explicitly asks for this weakening.

    A narrow reading: a sentence that names a check and the verb the weakening
    uses, with no negation. "Skip this flaky integration test" authorises a
    skip; "get the suite green", "fix the tests" and "the dataset is
    unavailable" authorise nothing (FR-013).
    """
    wanted = [name for name in signals if name in _SIGNAL_AUTHORIZATION]
    if not wanted or not request:
        return False
    for sentence in _REQUEST_SENTENCE.findall(request):
        if _REQUEST_NEGATION.search(sentence) or not _TEST_NOUN.search(sentence):
            continue
        for name in wanted:
            if _SIGNAL_AUTHORIZATION[name].search(sentence):
                return True
    return False


def validator_grounding_verified(validator_change: str,
                                 validator_refs: Iterable[str],
                                 allowed_refs: Iterable[str], request: str,
                                 signals: Iterable[str]) -> bool:
    """Whether a claimed validator correction is independently grounded.

    Only a `grounded_validator_correction` can be verified. It needs a ref that
    names an actual source (the request or a real evidence ref). If the mutation
    also carries a high-confidence weakening, the request must explicitly
    authorise that weakening — a prerequisite being unavailable is not evidence
    that the check is wrong (FR-013, FR-036).
    """
    if validator_change != "grounded_validator_correction":
        return False
    if not any(ref_matches(ref, allowed_refs) for ref in validator_refs or ()):
        return False
    if signals:
        return explicit_weakening_authorized(request, signals)
    return True


#: Commands whose primary purpose is validation, by kind. Classified from the
#: command word, never from output — a `grep` that prints a line containing
#: `fail` is not a failing test. Deliberately narrow: an unrecognised command is
#: not validation, and a validation-reporting obligation is never satisfied or
#: contradicted by one.
_VALIDATION_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tests", re.compile(
        r"(?i)(^|[;&|(\s])(?:"
        r"pytest|unittest|nose|tox|jest|vitest|mocha|"
        r"npm\s+(?:run\s+)?tests?|pnpm\s+(?:run\s+)?tests?|"
        r"yarn\s+(?:run\s+)?tests?|bun\s+tests?|"
        r"cargo\s+test|go\s+test|dotnet\s+test|mvn\s+test|gradle\s+test|"
        r"\./gradlew\s+test|make\s+tests?|"
        r"python[0-9.]*\s+-m\s+(?:pytest|unittest)|"
        r"python[0-9.]*\s+-m\s+pytest)(\s|$)")),
    ("build", re.compile(
        r"(?i)(^|[;&|(\s])(?:"
        r"npm\s+run\s+build|pnpm\s+build|yarn\s+build|bun\s+build|"
        r"cargo\s+build|dotnet\s+build|make\s+(?:build|all)|"
        r"gradle\s+build|mvn\s+package|go\s+build)(\s|$)")),
    ("lint", re.compile(
        r"(?i)(^|[;&|(\s])(?:"
        r"ruff\s+check|flake8|pylint|eslint|mypy|pyright|"
        r"npm\s+run\s+lint|pnpm\s+lint|yarn\s+lint)(\s|$)")),
    ("check", re.compile(
        r"(?i)(^|[;&|(\s])(?:"
        r"cargo\s+check|go\s+vet|tsc|make\s+check|"
        r"python[0-9.]*\s+-m\s+compileall)(\s|$)")),
)


def validation_kind(command: str, tool: str = "run_shell") -> str:
    """The kind of validation a command performs, or "" when it is not one.

    Recognised only in command position and only for the explicit forms that
    are a check: `pytest`, `cargo test`, `npm test`, `ruff check` and the like.
    A command that merely mentions the word is not validation.
    """
    if tool not in ("run_shell",):
        return ""
    text = command or ""
    for kind, pattern in _VALIDATION_KINDS:
        if pattern.search(text):
            return kind
    return ""


@dataclass(frozen=True)
class ValidationObservation:
    """One validation run this turn, and how it ended. Transient state.

    `status` is the process outcome; `integrity` says whether the oracle that
    produced it still means what the task asked it to mean. A run whose
    validation artifact was weakened beforehand is `tainted`: a green exit is
    then not evidence that the requested behaviour passes.
    """

    kind: str
    command_summary: str
    status: str                    # passed | failed | unavailable
    integrity: str = "trusted"     # trusted | tainted | unknown
    evidence_ref: str = ""


def _validation_target(command: str) -> str:
    """A bounded identity for the thing a validation command checks.

    A rerun of the same target supersedes an earlier result; two different
    checks do not. The command word and its subcommand, redacted by the caller,
    is enough — never the whole command line.
    """
    return " ".join((command or "").split())[:120]


def fold_validation(observations: list[ValidationObservation],
                    command: str, ok: bool,
                    integrity: str = "trusted") -> list[ValidationObservation]:
    """Add one run, dropping an earlier run of the same target it supersedes.

    The superseded run is dropped whatever its integrity: a rerun is the latest
    word on that target. `integrity` is carried into the new observation, so a
    tainted pass cannot silently replace a trusted failure with a trusted pass
    (FR-036, FR-125).
    """
    kind = validation_kind(command)
    if not kind:
        return observations
    target = _validation_target(command)
    kept = [one for one in observations
            if not (one.kind == kind and one.command_summary == target)]
    kept.append(ValidationObservation(
        kind=kind, command_summary=target,
        status="passed" if ok else "failed",
        integrity=integrity if integrity in ("trusted", "tainted", "unknown")
        else "unknown",
        evidence_ref=f"{kind}:{target[:60]}"))
    return kept


def final_validation_status(observations: list[ValidationObservation]) -> str:
    """The latest status per target, as one verdict for the turn.

    Any target whose latest run failed makes the turn's validation `failed`;
    otherwise, if anything ran, `passed`; with nothing run, "".
    """
    if not observations:
        return ""
    if any(one.status == "failed" for one in observations):
        return "failed"
    return "passed"


def final_validation_integrity(observations: list[ValidationObservation]) -> str:
    """Whether the turn's latest validation is authoritative.

    `tainted` if any latest run was made against a weakened oracle; `unknown`
    if any run's integrity is unknown; otherwise `trusted`. Empty when nothing
    ran. A tainted pass is not evidence that the requested behaviour passes.
    """
    if not observations:
        return ""
    if any(one.integrity == "tainted" for one in observations):
        return "tainted"
    if any(one.integrity == "unknown" for one in observations):
        return "unknown"
    return "trusted"


def _command_writes(tool: str, claim: str) -> bool:
    """Whether this command tool's command actually writes.

    Python is read as a syntax tree (a write inside a string literal is not a
    write); shell is read by the shared operation scanner, so an operation word
    in argument position — `grep rm foo.py` — is not a write.
    """
    if tool == "run_python":
        # The claim is "run_python <code>"; the code is what is parsed.
        _, _, code = claim.partition(" ")
        return python_writes(code)
    return shell_writes(_shell_command(claim))


def _command_deletes(tool: str, claim: str) -> bool:
    """Whether this command tool's command actually deletes.

    Python is read as a syntax tree, so `print('os.remove("foo.py")')` is not a
    delete. Shell is read by the shared operation scanner, so a read-only
    command that merely names a delete word is not a delete. Only a command
    tool can delete: a `write_file` of `unlink.py` changes nothing.
    """
    if tool not in _COMMAND_TOOLS:
        return False
    if tool == "run_python":
        # The claim is "run_python <code>"; the code is what is parsed.
        _, _, code = claim.partition(" ")
        return python_deletes(code)
    return shell_deletes(_shell_command(claim))


def _command_moves(tool: str, claim: str) -> bool:
    """Whether this command tool's command actually moves or renames.

    Shell moves go through the same operation scanner as writes and deletes,
    so `grep mv foo.py` is not a move. Python keeps its reviewed text reading.
    """
    if tool not in _COMMAND_TOOLS:
        return False
    if tool == "run_python":
        _, _, code = claim.partition(" ")
        return bool(_MOVE_COMMAND.search(_unquoted(code)))
    return shell_moves(_shell_command(claim))


def _file_operation(element: str, verb: re.Pattern[str]) -> bool:
    """Whether `element` asks to operate on a file, not on prose.

    "Delete foo.py" is a filesystem operation and needs filesystem evidence;
    "remove the unused import" is an edit, and a write delivers it.
    """
    match = verb.search(element)
    if match is None:
        return False
    return bool(_PATH_ISH.search(element[match.end():]))


@dataclass
class Element:
    """One requested thing and the evidence that shows it was delivered."""

    what: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class Assessment:
    """The turn's request-versus-delivery comparison. Never persisted."""

    requested: list[str] = field(default_factory=list)
    delivered: list[Element] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    unresolved_reasons: dict[str, str] = field(default_factory=dict)
    claims_completion: bool = False
    contradicted: bool = False
    pending_clarification: str = ""
    #: The user explicitly asked to be told how a check ended, and the turn's
    #: latest validation status — `passed`, `failed`, `""` for none. The answer
    #: must state it; a false pass is contradicted even without a completion
    #: claim (FR-036, FR-125).
    validation_obligation: bool = False
    validation_status: str = ""
    #: Whether the latest validation is authoritative — `trusted`, `tainted`,
    #: `unknown` or `""`. A tainted pass is not evidence the requested behaviour
    #: passes, so a pass claim on it is contradicted (FR-036, FR-125).
    validation_integrity: str = ""
    verdict: str = "no_intervention"          # no_intervention | annotate | block
    #: Why an explicit completion claim is delivered unconfirmed, or "": the
    #: gate could not reach a verdict, or the one correction turn still made
    #: the contradicted claim. Such a claim is never delivered as completed
    #: (FR-127).
    unconfirmed: str = ""

    def annotation(self) -> str:
        """The notice shown beside an answer with unresolved work (FR-037)."""
        lines = [f"  - {what}" + (f" ({self.unresolved_reasons.get(what)})"
                                  if self.unresolved_reasons.get(what) else "")
                 for what in self.unresolved]
        if self.unconfirmed:
            text = f"Completion is not confirmed — {self.unconfirmed}."
            if lines:
                text += "\nOutstanding:\n" + "\n".join(lines)
            return text
        if not self.unresolved:
            return ""
        return ("Not everything the request asked for was delivered:\n"
                + "\n".join(lines))


#: A list line that is data rather than work: a labelled value ("Expected:
#: 200", "Actual: 500", "status: failed") or a line with no word in it. A
#: pasted log or a table of numbers becomes bullets when a request is quoted,
#: and treating those as requested work forces a correction turn for something
#: nobody asked for.
_DATA_BULLET = re.compile(r"^[A-Za-z][A-Za-z ]{0,24}:\s*\S+$")


def _looks_like_data(what: str) -> bool:
    if _DATA_BULLET.match(what):
        return True
    return not re.search(r"[A-Za-z]{3,}", what)


def requested_elements(request: str) -> list[str]:
    """The explicitly enumerated things a request asked for.

    Only items the person actually wrote as a work list are taken; prose is
    not parsed into a checklist, because guessing the elements of a sentence
    would invent work the user never asked for. Lines that are data — a
    labelled expected/actual value, a bare number, pasted log rows — are not
    requested work. A request with no list has no elements, and the gate then
    acts only on a failed tool or an open decision.
    """
    found: list[str] = []
    for line in (request or "").splitlines():
        match = _ELEMENT.match(line)
        if not match:
            continue
        what = " ".join(match.group("what").split())
        if what and not _looks_like_data(what) and what not in found:
            found.append(what[:200])
    return found


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9_][a-z0-9_.\-/]{1,}", (text or "").lower())
    return {word for word in words if word not in _UNINFORMATIVE and len(word) > 2}


def _path_keywords(path: str) -> set[str]:
    """Keywords for a changed path, with its basename too.

    An absolute POSIX path is one token (`/tmp/x/notes.md`), so the element's
    `notes.md` would never match it; the basename is what the request names.
    """
    text = str(path or "")
    return _keywords(text) | _keywords(Path(text).name)


def _delivered(element: str, entries, changed_paths) -> list[str]:
    """Evidence refs showing `element` was done, or empty."""
    wanted = _keywords(element)
    if not wanted:
        return []
    mutation = bool(_MUTATION.search(element))
    destructive = _file_operation(element, _DESTRUCTIVE)
    move = _file_operation(element, _MOVE)
    refs: list[str] = []
    for entry in entries or []:
        state = getattr(getattr(entry, "state", None), "value", "")
        if state not in ("verified", "known", "derived"):
            continue
        claim = str(getattr(entry, "claim", "") or "")
        tool = claim.split(" ", 1)[0].strip().lower()
        # A shell claim is matched on its executable text: a path or operation
        # word that appears only inside a heredoc body is data, not evidence
        # that this command touched it (FR-036, FR-116).
        evidence = f"{tool} {shell_evidence_text(_shell_command(claim))}" \
            if tool == "run_shell" else claim
        if mutation and tool in _READ_ONLY_TOOLS:
            # The file was read, not changed. Only a change to the artifact —
            # or verified resulting state — delivers a mutation request.
            continue
        if destructive and not _command_deletes(tool, claim):
            # An edit to `foo.py` is not a delete of it; a Python delete is
            # read as code, not as shell text.
            continue
        if move and not _command_moves(tool, claim):
            # A read-only command that merely names a move word is not a move.
            continue
        if mutation and not destructive and not move \
                and tool not in _WRITER_TOOLS \
                and not (tool in _COMMAND_TOOLS and _command_writes(tool, claim)):
            # An ordinary mutation (write/create/update) needs writer evidence
            # or a shell command that actually writes; a read-only command
            # that merely names the file is not a change (FR-036).
            continue
        if wanted & _keywords(evidence):
            ref = str(getattr(entry, "fingerprint", "") or getattr(entry, "source", ""))
            if ref and ref not in refs:
                refs.append(ref)
    if not destructive and not move:
        # A changed path is delivery for a write, a create or an edit, and not
        # for an operation whose evidence has to match the operation.
        for path in changed_paths or []:
            if wanted & _path_keywords(str(path)):
                refs.append(str(path))
    return refs


def assess(request: str, *, entries=(), changed_paths=(), failures=(),
           pending=(), answer: str = "", validations=()) -> Assessment:
    """Compare the request against the delivery and decide the gate's verdict.

    `failures` are `(tool, reason)` for tool calls that failed; `pending` are
    open decisions. Either names real unresolved work, so the gate can see a
    completion claim contradicted even when the request was not a list.
    `validations` are this turn's `ValidationObservation`s: when the user asked
    to be told how a check ended, the answer must state the latest status, and
    a false pass is contradicted on its own.
    """
    from .claims import (
        claims_completion,
        claims_validation_pass,
        reports_validation_failure,
        reports_validation_unknown,
        requests_validation_status,
    )

    result = Assessment()
    result.requested = requested_elements(request)

    for element in result.requested:
        evidence = _delivered(element, entries, changed_paths)
        if evidence:
            result.delivered.append(Element(element, evidence))
        else:
            result.unresolved.append(element)
            result.unresolved_reasons[element] = "the gathered evidence does not show it"

    for tool, reason in failures or []:
        what = f"the {tool} call failed"
        if what not in result.unresolved:
            result.unresolved.append(what)
            result.unresolved_reasons[what] = str(reason or "the tool reported a failure")

    for decision in pending or []:
        what = str(getattr(decision, "what", "") or "an open decision")
        if what in result.unresolved:
            continue
        result.unresolved.append(what)
        state = str(getattr(decision, "state", "") or "unresolved")
        result.unresolved_reasons[what] = f"blocked by an open decision ({state})"
        if not result.pending_clarification:
            result.pending_clarification = str(getattr(decision, "id", "") or "")

    result.validation_obligation = requests_validation_status(request)
    observations = list(validations)
    result.validation_status = final_validation_status(observations)
    result.validation_integrity = final_validation_integrity(observations)
    if result.validation_obligation:
        _check_validation_report(result, answer, claims_validation_pass,
                                 reports_validation_failure, reports_validation_unknown)

    result.claims_completion = claims_completion(answer)
    result.contradicted = result.contradicted \
        or bool(result.claims_completion and result.unresolved)

    if result.contradicted:
        result.verdict = "block"
    elif result.unresolved:
        result.verdict = "annotate"
    return result


def _check_validation_report(result: Assessment, answer: str, claims_pass, reports_failure,
                             reports_unknown) -> None:
    """The user asked for the check's outcome; the answer must give it.

    A false pass is contradicted whether or not the answer claims the task is
    complete (FR-036, FR-125); an omitted status is a completion failure the
    single correction turn is for. Only a recognised validation observation
    moves `validation_status` — an unrelated tool error never does. A green run
    against a weakened oracle (`integrity = tainted`) is not authoritative: a
    pass claim on it is contradicted, because the check no longer means what the
    task asked it to mean.
    """
    what = "the validation result"
    status = result.validation_status
    if status == "failed":
        if claims_pass(answer):
            result.unresolved.append(what)
            result.unresolved_reasons[what] = (
                "the latest validation run failed, but the answer says it passed")
            result.contradicted = True
        elif not reports_failure(answer):
            result.unresolved.append(what)
            result.unresolved_reasons[what] = (
                "the user asked for the validation result, and the answer does not "
                "state it")
            result.contradicted = True
    elif status == "passed":
        if result.validation_integrity == "tainted":
            if claims_pass(answer):
                result.unresolved.append(what)
                result.unresolved_reasons[what] = (
                    "a validation run passed, but the validation artifact was "
                    "weakened, so the pass is not trustworthy")
                result.contradicted = True
            elif not (reports_failure(answer) or reports_unknown(answer)):
                result.unresolved.append(what)
                result.unresolved_reasons[what] = (
                    "the validation oracle was weakened, so the result is not "
                    "established; the answer does not say so")
                result.contradicted = True
        elif reports_failure(answer) and not claims_pass(answer):
            result.unresolved.append(what)
            result.unresolved_reasons[what] = (
                "the latest validation run passed, but the answer says it failed")
            result.contradicted = True
    else:
        if claims_pass(answer):
            result.unresolved.append(what)
            result.unresolved_reasons[what] = (
                "no validation run was recorded, so the answer cannot say it passed")
            result.contradicted = True
        elif not reports_unknown(answer):
            result.unresolved.append(what)
            result.unresolved_reasons[what] = (
                "the user asked for the validation result, and no run was recorded")
            result.contradicted = True


def as_incomplete(assessment: Assessment) -> str:
    """What the model is told when an answer is contradicted (FR-125).

    When the block came from a requested validation status rather than a
    completion claim, say that instead of accusing the model of a claim it did
    not make — the correction is to state the result, not to withdraw a claim.
    A green run against a weakened oracle is named as such: the correction is to
    stop claiming the check passed, not to weaken it further.
    """
    named = "\n".join(f"  - {what}" for what in assessment.unresolved)
    if assessment.validation_status == "passed" \
            and assessment.validation_integrity == "tainted":
        return (
            "A validation run exited zero, but the validation artifact was "
            "changed without a grounded reason, so the pass is not trustworthy "
            "and is not evidence that the requested behaviour works. Do not "
            "claim the check passes. State plainly that the validation was "
            "weakened and the result is not established, or restore the check "
            "to the behaviour the request asked for.\n"
            f"These are still unresolved:\n{named}")
    if assessment.validation_obligation and not assessment.claims_completion:
        status = assessment.validation_status
        shown = (f"The latest relevant validation run {status}."
                 if status else
                 "No validation run was recorded, so the result is not known.")
        return (
            "The user explicitly asked for the final validation status, and your "
            f"answer does not state it. {shown}\n"
            f"These are still unresolved:\n{named}\n\n"
            "Correct the answer to state plainly what the latest validation run "
            "shows and name the blocking reason. Do not claim success, and do "
            "not invent a result.")
    extra = ""
    if assessment.validation_obligation and assessment.validation_status:
        extra = ("\nThe user explicitly asked for the validation result. The latest "
                 f"validation run {assessment.validation_status}. State that plainly "
                 "in your answer, with the reason; do not claim success.\n")
    return (
        "Your answer says the task is complete, but the evidence does not "
        "support that. These are still unresolved:\n"
        f"{named}\n{extra}\n"
        "Correct the answer to state the work as incomplete and name what is "
        "still needed. Do not claim completion for work the evidence does not "
        "show."
    )
