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

import os
import re
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

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
    r"(?i)\b(create|write|add|change|replace|rename|move|delete|remove|update|"
    r"fix|implement|refactor|migrate|generate)\b")

#: Verbs whose evidence has to match the operation, not just the path: an edit
#: to `foo.py` is not a delete of it, and a write is not a rename.
_DESTRUCTIVE = re.compile(r"(?i)\b(delete|remove)\b")
_MOVE = re.compile(r"(?i)\b(rename|move)\b")
_DESTRUCTIVE_COMMAND = re.compile(r"(?i)\b(rm|rmdir|del|erase|unlink|trash)\b")
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

#: A shell command that writes: a read-only `cat README.md` is not an update.
_SHELL_MUTATION = re.compile(
    r"(?i)(\brm\b|\brmdir\b|\bdel\b|\berase\b|\bunlink\b|\bmv\b|\bmove\b|"
    r"\brename\b|\btee\b|\btruncate\b|\btouch\b|\bsed\s+-i|>>?\s)")

#: A Python statement that writes. `run_python` is not a shell, so the shell
#: operators do not describe it.
_PYTHON_MUTATION = re.compile(
    r"(?i)(\.write_text\s*\(|\.write_bytes\s*\(|\.writelines\s*\(|"
    r"\.unlink\s*\(|\.rename\s*\(|\.replace\s*\(|\.touch\s*\(|\.mkdir\s*\(|"
    r"\bopen\s*\([^)]*['\"][wax]['\"]|"
    r"\bos\.(remove|unlink|rename|replace|rmdir|mkdir|makedirs)\s*\(|"
    r"\bshutil\.(move|copy|copy2|copyfile|rmtree|make_archive)\s*\()")

#: A path-looking target: a token with a file extension or a path separator.
_PATH_ISH = re.compile(r"(?:[\w.-]*[/\\][\w./\\-]*)|\b[\w-]+\.[A-Za-z0-9]{1,8}\b")


def _unquoted(command: str) -> str:
    """The command with quoted spans removed, for operator detection.

    `grep '> ' foo.py` searches for a string; the `>` is not redirection. Only
    a `>` outside quotes is a shell operator.
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"", " ", command or "")


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


def command_mutates(command: str, tool: str = "run_shell") -> bool:
    """Whether a shell or Python command changes the filesystem."""
    if tool == "run_python":
        return bool(_PYTHON_MUTATION.search(_python_code(command)))
    return bool(_SHELL_MUTATION.search(_unquoted(command)))


def _command_writes(tool: str, claim: str) -> bool:
    """Whether this command tool's command actually writes.

    Python gets comment-stripped source (its literals are meaningful, e.g.
    `open("foo.py", "w")`); shell gets quote-stripped text (a quoted `>` is
    not redirection).
    """
    if tool == "run_python":
        return bool(_PYTHON_MUTATION.search(_python_code(claim)))
    return bool(_SHELL_MUTATION.search(_unquoted(claim)))


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
    verdict: str = "no_intervention"          # no_intervention | annotate | block

    def annotation(self) -> str:
        """The notice shown beside an answer with unresolved work (FR-037)."""
        if not self.unresolved:
            return ""
        lines = [f"  - {what}" + (f" ({self.unresolved_reasons.get(what)})"
                                  if self.unresolved_reasons.get(what) else "")
                 for what in self.unresolved]
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
        command = _unquoted(claim)
        if mutation and tool in _READ_ONLY_TOOLS:
            # The file was read, not changed. Only a change to the artifact —
            # or verified resulting state — delivers a mutation request.
            continue
        if destructive and (tool not in _COMMAND_TOOLS
                            or not _DESTRUCTIVE_COMMAND.search(command)):
            # An edit to `foo.py` is not a delete of it.
            continue
        if move and (tool not in _COMMAND_TOOLS
                     or not _MOVE_COMMAND.search(command)):
            continue
        if mutation and not destructive and not move \
                and tool not in _WRITER_TOOLS \
                and not (tool in _COMMAND_TOOLS and _command_writes(tool, claim)):
            # An ordinary mutation (write/create/update) needs writer evidence
            # or a shell command that actually writes; a read-only command
            # that merely names the file is not a change (FR-036).
            continue
        if wanted & _keywords(claim):
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
           pending=(), answer: str = "") -> Assessment:
    """Compare the request against the delivery and decide the gate's verdict.

    `failures` are `(tool, reason)` for tool calls that failed; `pending` are
    open decisions. Either names real unresolved work, so the gate can see a
    completion claim contradicted even when the request was not a list.
    """
    from .claims import claims_completion

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

    result.claims_completion = claims_completion(answer)
    result.contradicted = bool(result.claims_completion and result.unresolved)

    if result.contradicted:
        result.verdict = "block"
    elif result.unresolved:
        result.verdict = "annotate"
    return result


def as_incomplete(assessment: Assessment) -> str:
    """What the model is told when a completion claim is contradicted (FR-125)."""
    named = "\n".join(f"  - {what}" for what in assessment.unresolved)
    return (
        "Your answer says the task is complete, but the evidence does not "
        "support that. These are still unresolved:\n"
        f"{named}\n\n"
        "Correct the answer to state the work as incomplete and name what is "
        "still needed. Do not claim completion for work the evidence does not "
        "show."
    )
