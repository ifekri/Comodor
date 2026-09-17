"""The learning engine — what makes Comodor better the more it is used.

The cycle, once per task:

1. **Recall.** Before answering, rank stored lessons against the request and
   inject the best few as a *Playbook* block, under a hard token cap.
2. **Act.** The agent works normally.
3. **Credit.** Whatever was recalled shares the outcome: a clean finish is a win
   for those lessons, a failure is a loss. Confidence moves accordingly.
4. **Reflect.** In the background, the model reads the episode and proposes new
   lessons. Near-duplicates merge into the existing lesson instead of piling up.
5. **Consolidate.** Old, unused, low-confidence lessons decay away.

Two design choices are load-bearing. Reflection runs on a background thread so a
finished task never waits on it. And everything recalled is *shown* to the user
— a memory system you cannot inspect is one you cannot trust, and a wrong lesson
that silently shapes every answer is worse than no memory at all.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from ..config import Config
from ..events import EventBus, Kind
from ..paths import project_key
from . import reflect as reflection_module
from . import rules as rules_module
from .signals import Outcome, SignalDetector
from .store import BrainStore, Episode, Lesson, Rule, Skill, score

PLAYBOOK_HEADER = """\
Learned playbook — things earlier sessions established. Treat these as strong \
priors, not orders: if what you observe now contradicts one, trust your \
observation and say so."""


# --------------------------------------------------------------------------- #
# the admission gate: what backs a proposal (FR-056, FR-066)
# --------------------------------------------------------------------------- #

#: Tools whose output is an observation of the repository or the machine.
#: Text that arrived through one of them may back a fact about what that
#: source contained — and nothing else (contracts/learning-record.md §L5).
OBSERVING_TOOLS = frozenset({"read_file", "list_dir", "glob", "grep", "run_shell",
                             "run_python", "web_fetch", "web_search", "browse"})

#: Tools that change a file. An observation of a file that one of these has
#: since written to is out of date, whatever its words still say.
_WRITER_TOOLS = frozenset({"write_file", "edit_file"})

#: A shell command that changes a file, for the same staleness check.
_SHELL_MUTATION = re.compile(
    r"(?i)(\brm\b|\brmdir\b|\bdel\b|\berase\b|\bunlink\b|\bmv\b|\bmove\b|"
    r"\brename\b|\btee\b|\btruncate\b|\btouch\b|sed\s+-i|>>?\s)")

#: A Python statement that changes a file. `run_python` is not a shell, so the
#: shell operators do not describe it: `Path("foo.py").write_text(...)` is a
#: write even though it matches none of them.
_PYTHON_MUTATION = re.compile(
    r"(?i)(\.write_text\s*\(|\.write_bytes\s*\(|\.writelines\s*\(|"
    r"\.unlink\s*\(|\.rename\s*\(|\.replace\s*\(|\.touch\s*\(|\.mkdir\s*\(|"
    r"\bopen\s*\([^)]*['\"][wax]['\"]|"
    r"\bos\.(remove|unlink|rename|replace|rmdir|mkdir|makedirs)\s*\(|"
    r"\bshutil\.(move|copy|copy2|copyfile|rmtree|make_archive)\s*\()")

#: How much of a proposal's wording a single message must contain to count
#: as having said it. Word overlap, not meaning: the check is deterministic
#: and says only that the words came from there.
COVERAGE = 0.6

_STOP = frozenset("""
a an and are as at be been but by for from has have if in into is it its of on or
that the their then there these this to was were will with when which who would
you your we our they them i me my not no do does did so than can could should
""".split())


def _content_words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9_][a-z0-9_.\-/]{1,}", (text or "").lower())
            if word not in _STOP and len(word) > 1}


def covers(words: set[str], text: str) -> bool:
    """Whether `text` contains enough of `words` to have said them."""
    if not words:
        return False
    present = words & _content_words(text)
    needed = max(1, int(len(words) * COVERAGE + 0.999))
    return len(present) >= needed


def instruction_shaped(text: str) -> bool:
    """Text that gives an order rather than describing something.

    The curated shelf already refuses these (`facts.py`); retrieved content
    that reads this way is the injection case, and is refused before it can
    become a fact about "what the file says" (FR-066).
    """
    from .facts import FactError, _check_injection

    try:
        _check_injection(text)
    except FactError:
        return True
    return bool(re.match(r"\s*(always|never|do not|don't|you must|you should|from now on|"
                         r"ignore|disregard|remember)\b", text or "", re.IGNORECASE))


def corroborate(text: str, messages: Iterable[Any]) -> tuple[str, str, str]:
    """What in a transcript backs a proposed lesson or fact.

    Returns `(provenance, source_ref, fingerprint)`, or three empty strings
    when nothing does. The person's own words back it as `user_statement`;
    an observing tool's output backs it as `tool_confirmed` — a fact about
    what that source contained, fingerprinted so a change to the source can
    invalidate it — unless the text is instruction-shaped, in which case it
    is refused outright (FR-066). Assistant text backs nothing: a proposal
    corroborated only by the model's own prose is still a model assertion.

    Two things that look like corroboration but are not. A USER-role message
    the loop wrote to itself — a compaction brief, a completion correction, a
    plan restatement — is not the person's words (`meta["synthetic"]` /
    `meta["compacted"]`), and neither is an observation of a file something
    has written to since: its words may still match while the file does not
    (FR-066, FR-114).
    """
    words = _content_words(text)
    if not words:
        return "", "", ""
    messages = list(messages)
    for message in messages:
        if _role(message) == "user" and not _internal(message) \
                and covers(words, _content(message)):
            return "user_statement", "user message", ""
    if instruction_shaped(text):
        return "", "", ""
    for index, message in enumerate(messages):
        if _role(message) != "tool" or getattr(message, "is_error", False):
            continue
        name = str(getattr(message, "name", "") or "")
        if name not in OBSERVING_TOOLS or not covers(words, _content(message)):
            continue
        meta = getattr(message, "meta", None) or {}
        path = str(meta.get("path") or "") if isinstance(meta, dict) else ""
        if not path:
            # A source with no re-observable identity — a web page, a pathless
            # command — cannot be fingerprinted or invalidated later, so it
            # must not become durable knowledge (FR-066, FR-114).
            continue
        if _written_later(messages, index, path):
            continue
        ref = f"{name}:{path}"
        fingerprint = rules_module.file_fingerprint(Path(path))
        return "tool_confirmed", ref[:200], fingerprint
    return "", "", ""


def _internal(message: Any) -> bool:
    """Whether a USER-role message is the loop's own text, not the person's."""
    meta = getattr(message, "meta", None)
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("synthetic") or meta.get("compacted"))


def _unquoted(command: str) -> str:
    """A command with quoted spans removed, so a quoted `>` is not redirection."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", " ", command or "")


def _names_file(command: str, path: str) -> bool:
    """Whether a shell command names the file, absolute or by basename.

    A read records the absolute path; a later command commonly names the same
    file relatively (`sed -i … foo.py`), so the basename counts too.
    """
    if not command:
        return False
    return path in command or Path(path).name in command


def _written_later(messages: list[Any], index: int, path: str) -> bool:
    """Whether a write to `path` follows the observation at `index`.

    An observation the model has since edited over is no longer what the file
    says; storing the fact against the current file's fingerprint would keep
    a contradicted fact active (FR-114). A shell command that changes the file
    counts too: `run_shell("rm foo.py")` leaves the observation just as stale
    as an editor would.
    """
    for later in messages[index + 1:]:
        role = _role(later)
        if role == "assistant":
            for call in getattr(later, "tool_calls", None) or []:
                name = str(getattr(call, "name", "") or "")
                args = getattr(call, "arguments", None) or {}
                if name in _WRITER_TOOLS and str(args.get("path") or "") == path:
                    return True
                if name in ("run_shell", "run_python"):
                    command = str(args.get("command") or args.get("code") or "")
                    if not _names_file(command, path):
                        continue
                    if name == "run_python":
                        if _PYTHON_MUTATION.search(command):
                            return True
                    elif _SHELL_MUTATION.search(_unquoted(command)):
                        return True
        elif role == "tool" and str(getattr(later, "name", "") or "") in _WRITER_TOOLS:
            meta = getattr(later, "meta", None) or {}
            if isinstance(meta, dict) and str(meta.get("path") or "") == path:
                return True
    return False


def _role(message: Any) -> str:
    role = getattr(message, "role", "")
    return str(getattr(role, "value", role) or "")


def _content(message: Any) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content or "")


# --------------------------------------------------------------------------- #
# fingerprint staleness (FR-060, FR-114, T111)
# --------------------------------------------------------------------------- #
#
# Granularity, decided from the shapes in `rules.py` and `store.py`:
#
# * A counted convention (`counted_convention` rule) is a *tally over a
#   sample* — "31 of 34 string literals are single-quoted" — not a fact about
#   one file. Its fingerprint covers the sampled files as a whole
#   (`rules.manifest_fingerprint`), and a mismatch is the cue to **re-count**,
#   not the verdict: the rule is marked stale only when re-counting flips
#   what it says. Editing one sampled file changes the fingerprint and
#   changes nothing else. This is rule-level granularity: what is
#   fingerprinted is the evidence the rule was counted from, and what
#   invalidates the rule is the count no longer supporting it.
# * A structural convention (`layout.*`) is fingerprinted over the directory
#   structure, names only: moving what it describes invalidates it; editing
#   a file inside does not.
# * A `tool_confirmed` fact is about what one source contained. Its
#   fingerprint is whole-file: any change to that file marks it stale,
#   because nothing records which part of the file backed it.
# * A `user_correction` carries the corrected file's fingerprint for the
#   record only. It is a statement of preference, not of the file, and it
#   is displaced by a later contradicting correction — never by an edit.

def stale_by_fingerprint(store: BrainStore, root: Path, scopes: list[str],
                         paths: Iterable[str] | None = None,
                         tables: tuple[str, ...] = ("rules", "facts",
                                                    "lessons")) -> list[dict[str, Any]]:
    """Mark what a changed source no longer supports. Returns what was marked.

    `paths` narrows the check to items whose source includes one of them —
    the per-observation path — and `None` checks everything in `scopes`.
    Nothing is deleted; a marked item stays inspectable (FR-061).
    """
    root = Path(root)
    touched = {_under(root, path) for path in (paths or []) if path}
    marked: list[dict[str, Any]] = []

    if "rules" in tables:
        for rule in store.all_rules(scopes, active_only=True):
            if rule.provenance != "counted_convention" or not rule.fingerprint:
                continue
            if rule.source_ref.startswith("sample:"):
                # The sample is the evidence identity: a new, removed, renamed
                # or changed eligible file can move a repository-wide
                # convention, so the current bounded sample is rebuilt rather
                # than assuming the recorded file set is still representative
                # (T111).
                historical = rules_module.files_of(rule.source_ref, root)
                sample = rules_module.sampled_files(root)
                if touched:
                    # Relevant when the requested path is in the current
                    # sample or was in the recorded one: a newly added path is
                    # not in the old source_ref, so membership alone cannot be
                    # the test.
                    domain = {_under(root, str(f)) for f in sample} \
                        | {_under(root, str(f)) for f in historical}
                    if not (domain & touched):
                        continue
                current = rules_module.manifest_fingerprint(sample, root)
                if current == rule.fingerprint:
                    continue
                holds = rules_module.recount(sample, rule.key, root, rule.statement)
            elif rule.source_ref.startswith("layout:"):
                current = rules_module.structure_fingerprint(root)
                if current == rule.fingerprint:
                    continue
                holds = rule.key in {observation.key
                                     for observation in rules_module.layout_signals(root)}
            else:
                continue
            if holds:
                source_ref = (rules_module.manifest_ref(root, sample)
                              if rule.source_ref.startswith("sample:") else "")
                store.refresh_fingerprint("rules", rule.id, current,
                                          source_ref=source_ref)
                continue
            store.mark_stale("rules", rule.id)
            marked.append({"table": "rules", "id": rule.id, "text": rule.statement,
                           "why": "its source changed and a re-count no longer supports it"})

    if "facts" in tables:
        for fact in store.all_facts(scopes, settled_only=True):
            if fact.provenance != "tool_confirmed" or not fact.fingerprint:
                continue
            path = _path_of(fact.source_ref)
            if not path:
                continue
            if touched and _under(root, path) not in touched:
                continue
            current = rules_module.file_fingerprint(root / path)
            if current == fact.fingerprint:
                continue
            store.mark_stale("facts", fact.id)
            marked.append({"table": "facts", "id": fact.id, "text": fact.text,
                           "why": f"{path} changed since it was read"})

    if "lessons" in tables:
        # A reflection can admit a lesson corroborated by a tool observation,
        # with the same source_ref and fingerprint a fact gets. Checked the
        # same way: a lesson that still describes a file which has changed is
        # injected into the playbook as if it were true (FR-060, FR-114).
        for lesson in store.all_lessons(scopes):
            if lesson.status != "active" or lesson.provenance != "tool_confirmed" \
                    or not lesson.fingerprint:
                continue
            path = _path_of(lesson.source_ref)
            if not path:
                continue
            if touched and _under(root, path) not in touched:
                continue
            current = rules_module.file_fingerprint(root / path)
            if current == lesson.fingerprint:
                continue
            store.mark_stale("lessons", lesson.id)
            marked.append({"table": "lessons", "id": lesson.id, "text": lesson.text,
                           "why": f"{path} changed since it was read"})
    return marked


def _path_of(source_ref: str) -> str:
    tool, _, path = source_ref.partition(":")
    return path if tool in OBSERVING_TOOLS else ""


def _under(root: Path, path: str) -> str:
    try:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = root / resolved
        return resolved.resolve().as_posix().lower()
    except (OSError, ValueError):
        return str(path).replace("\\", "/").lower()


def _same_question(left: str, right: str) -> bool:
    return " ".join(left.lower().split()) == " ".join(right.lower().split())


class LearningEngine:
    """Owns the brain: recall, credit assignment, reflection, consolidation."""

    def __init__(self, config: Config, bus: EventBus, gateway: Any = None,
                 store: BrainStore | None = None, checkpoints: Any = None,
                 redact: Any = None) -> None:
        self.config = config
        self.bus = bus
        self.gateway = gateway
        self.store = store or BrainStore(config.paths.brain_db)
        self.session_id = f"s{int(time.time())}"
        self.project_scope = f"project:{project_key(config.paths.project)}"
        self._reflect_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        #: Guards `_threads`: callers append while a waiter prunes, and a
        #: prune written as a fresh list would drop an append made in between.
        self._threads_lock = threading.Lock()

        # Curated memory: a small, separate shelf. The facts service is
        # cheap to build (one store handle, no threads) and is created even
        # when learning is off, so `comodor journey` can still list what was
        # learned before it was switched off.
        from .facts import FactService

        self.facts = FactService(
            self.store, scopes=["global", self.project_scope],
            write_scope=self.write_scope,
        )
        #: The briefing block, built once. Facts learned after this point
        #: join the next session, not this one — the prefix-cache rule.
        self.facts_briefing = ""

        # Reflex: the fast lane. Deterministic, model-free, always on.
        self.detector = SignalDetector(
            store=self.store, checkpoints=checkpoints, scope=self.project_scope,
            session_id=self.session_id, redact=redact, facts=self.facts,
        )
        self._prefetched: tuple[str, list[Lesson]] | None = None
        self._prefetch_lock = threading.Lock()
        #: The learned vocabulary. Read on first recall, not on start-up.
        self._associations = None
        self._reviewer: Any = None
        #: Whether this session has yet checked the counted rules against
        #: the repository as it is now (T111). Once, lazily, at first recall.
        self._rules_checked = False
        self.freeze_facts()

    # -- curated facts ----------------------------------------------------- #

    def freeze_facts(self) -> None:
        """Take the session's facts snapshot.

        Called once at construction. Everything the briefing says for the
        rest of this session was true when it was taken, which is exactly
        what keeps the head of every request byte-identical. Before it is
        taken, facts and tool-confirmed lessons whose source file changed are
        marked stale, so neither the snapshot nor recall carries what the
        repository no longer says (FR-060).
        """
        try:
            self.check_staleness(tables=("facts", "lessons"))
        except Exception:
            pass
        try:
            self.facts_briefing = self.facts.snapshot()
        except Exception:
            self.facts_briefing = ""

    def refresh_facts(self) -> str:
        """Rebuild the snapshot deliberately — a new conversation, a memory change."""
        self.facts_briefing = self.facts.snapshot()
        return self.facts_briefing

    @property
    def review_spent(self) -> float:
        """What background review has cost this session, in USD."""
        reviewer = self._reviewer
        usage = getattr(reviewer, "usage", None) if reviewer else None
        return float(getattr(usage, "cost_usd", 0.0) or 0.0)

    # -- scoping ---------------------------------------------------------- #

    @property
    def scopes(self) -> list[str]:
        """Which buckets of memory apply to the current project."""
        return ["global", self.project_scope]

    @property
    def write_scope(self) -> str:
        return (self.project_scope if self.config.learning.share_scope == "project"
                else "global")

    # -- 0. reflex: what the user changed since last time ------------------ #

    def before_turn(self, user_text: str, episode_id: int = 0) -> Outcome:
        """Fold in everything the user has done since the previous turn.

        Deliberately runs *before* recall rather than after the task, so a
        correction made a moment ago is already in force for the request being
        typed now. That immediacy is the whole point: fix it once, and the next
        answer is different.
        """
        if not self.config.learning.enabled or not self.config.learning.corrections:
            return Outcome()

        outcome = self.detector.scan_corrections(episode_id)
        message_outcome = self.detector.record_user_message(user_text, episode_id)
        outcome.new_rules.extend(message_outcome.new_rules)
        outcome.new_facts.extend(message_outcome.new_facts)
        outcome.refused.extend(message_outcome.refused)
        outcome.superseded.extend(message_outcome.superseded)

        if outcome.new_rules and self.config.learning.announce:
            self.bus.emit(Kind.MEMORY, action="rule",
                          items=[rule.as_dict() for rule in outcome.new_rules],
                          corrections=len(outcome.corrections))
        if outcome.new_facts:
            # A term defined in this message is on the shelf for the next
            # session; this session's briefing was frozen when it started.
            self.bus.emit(Kind.MEMORY, action="taught",
                          items=[fact.as_dict() for fact in outcome.new_facts])
        if outcome.superseded:
            self.bus.emit(Kind.MEMORY, action="superseded",
                          items=[{"older": _brief(older), "newer": _brief(newer)}
                                 for older, newer in outcome.superseded])
        if outcome.refused:
            self.bus.emit(Kind.MEMORY, action="refused", items=list(outcome.refused))
        return outcome

    def on_undo(self, paths: list[str]) -> None:
        self.detector.record_undo(paths)

    def on_denied(self, tool: str, subject: str) -> Outcome:
        """A refused permission, recorded as a preference."""
        if not self.config.learning.enabled or not self.config.learning.corrections:
            return Outcome()
        outcome = self.detector.record_denial(tool, subject)
        if outcome.new_rules and self.config.learning.announce:
            self.bus.emit(Kind.MEMORY, action="rule",
                          items=[rule.as_dict() for rule in outcome.new_rules])
        return outcome

    def bootstrap_project(self) -> int:
        """Read the project's existing conventions once, in the background."""
        if not self.config.learning.enabled or not self.config.learning.rules:
            return 0

        def work() -> None:
            try:
                self.detector.scan_project(self.config.paths.project)
            except Exception:
                pass

        thread = threading.Thread(target=work, daemon=True, name="comodor-scan")
        thread.start()
        with self._threads_lock:
            self._threads.append(thread)
        return 1

    # -- 1. recall -------------------------------------------------------- #

    def active_rules(self) -> list[Rule]:
        """The house rules confident enough to shape this turn.

        The first time a session asks, the counted rules are checked against
        the repository as it is now: one whose sample changed is re-counted,
        and one the re-count no longer supports is marked stale and left
        out — the contradiction is announced, never resolved quietly (T111).
        """
        if not self.config.learning.enabled or not self.config.learning.rules:
            return []
        if not self._rules_checked:
            self._rules_checked = True
            self.check_staleness(tables=("rules",))
        return self.store.confident_rules(self.scopes)

    def check_staleness(self, paths: Iterable[str] | None = None,
                        tables: tuple[str, ...] = ("rules", "facts",
                                                   "lessons")) -> list[dict[str, Any]]:
        """Mark what the repository no longer supports; say what was marked.

        `paths` narrows it to items derived from those files — called by
        the loop when a turn reads or writes one, so an answer resting on
        a learned item is corrected while the turn is still open (FR-114).
        A stale fact leaves the briefing at once: correctness outranks the
        cache here, and this is the one refresh that a turn may trigger.
        """
        if not self.config.learning.enabled:
            return []
        try:
            marked = stale_by_fingerprint(self.store, self.config.paths.project,
                                          self.scopes, paths, tables=tables)
        except Exception:                  # noqa: BLE001 - never fatal
            return []
        if not marked:
            return []
        if any(item["table"] == "facts" for item in marked) and self.facts_briefing:
            try:
                self.facts_briefing = self.facts.snapshot()
            except Exception:
                pass
        self.bus.emit(Kind.MEMORY, action="stale", items=marked)
        return marked

    def prefetch(self, query: str) -> None:
        """Warm recall for a draft the user is still typing.

        Called from the UI's idle path. By the time Enter is pressed the answer
        is usually already computed, so recall costs nothing on the turn itself.
        """
        if not query.strip() or not self.config.learning.enabled:
            return
        try:
            lessons = self.recall(query)
        except Exception:
            return
        with self._prefetch_lock:
            self._prefetched = (query, lessons)

    def take_prefetched(self, query: str) -> list[Lesson] | None:
        """The prefetched result, if it was for this exact query."""
        with self._prefetch_lock:
            cached = self._prefetched
            self._prefetched = None
        if cached and cached[0].strip() == query.strip():
            return cached[1]
        return None

    @property
    def associations(self):
        """The learned vocabulary, read once and kept.

        Lazily, because a brain that is never asked to recall anything — a
        `--version`, a `doctor` — should not pay to parse it.
        """
        if self._associations is None:
            from .associations import Associations

            try:
                self._associations = self.store.load_associations()
            except Exception:              # noqa: BLE001 - never fatal
                self._associations = Associations()
        return self._associations

    def recall(self, query: str) -> list[Lesson]:
        """The lessons worth spending context on for this request.

        The query is searched as written *and* as the vocabulary implies. A
        request for "tests for the parser" and a lesson reading "use pytest
        fixtures" share no word at all, and without the second search the right
        lesson is invisible — see `associations.py` for how the link between
        them is learned by counting rather than guessed by a model.
        """
        if not self.config.learning.enabled or not query.strip():
            return []

        learning = self.config.learning
        selected: list[Lesson] = []
        seen: set[int] = set()

        # Pinned lessons are unconditional — the user asked for them every time.
        for lesson in self.store.pinned_lessons(self.scopes):
            selected.append(lesson)
            seen.add(lesson.id)

        # Both, and the results merged: an exact match must never be displaced
        # by an inferred one, so the original query's hits are ranked first and
        # the expansion only adds candidates the plain search never saw.
        ranked = self.store.search_lessons(query, self.scopes, limit=learning.top_k * 3)
        if learning.associative:
            ranked = self._with_associates(query, ranked, learning.top_k * 3)
        scored = sorted(
            ((lesson, score(relevance, lesson, learning.half_life_days, query))
             for lesson, relevance in ranked if lesson.id not in seen),
            key=lambda pair: pair[1], reverse=True,
        )
        for lesson, value in scored:
            if len(selected) >= learning.top_k:
                break
            if value <= 0.01:              # too weak or too distrusted to bother
                continue
            selected.append(lesson)
            seen.add(lesson.id)

        return selected

    def _with_associates(self, query: str, ranked: list, limit: int) -> list:
        """Add what the learned vocabulary suggests, ranked below what matched.

        The expansion's relevance is scaled down before it competes, so a
        lesson found only by association can be recalled when nothing else was
        and cannot outrank a lesson the user's own words found.
        """
        enriched = self.associations.enrich(query)
        if enriched == query:
            return ranked

        try:
            extra = self.store.search_lessons(enriched, self.scopes, limit=limit)
        except Exception:                  # noqa: BLE001 - recall is best-effort
            return ranked

        from .associations import EXPANSION_WEIGHT

        seen = {lesson.id for lesson, _ in ranked}
        merged = list(ranked)
        for lesson, relevance in extra:
            if lesson.id in seen:
                continue
            merged.append((lesson, relevance * EXPANSION_WEIGHT))
            seen.add(lesson.id)
        return merged

    def render_playbook(self, lessons: list[Lesson], skills: list[Skill] | None = None,
                        max_tokens: int | None = None,
                        rules: list[Rule] | None = None) -> str:
        """Format recalled memory for the system prompt, within a token budget.

        House rules come first and carry their own budget. They are counted facts
        about how this user works rather than prose a model wrote, so they are
        both cheaper and more reliable than a lesson, and they should survive a
        tight budget that truncates the rest.
        """
        blocks: list[str] = []
        if rules:
            rules_block = rules_module.render_rules(rules, max_tokens=300)
            if rules_block:
                blocks.append(rules_block)

        if not lessons and not skills:
            return "\n\n".join(blocks)

        budget = max_tokens or self.config.learning.max_playbook_tokens
        lines = [PLAYBOOK_HEADER, ""]
        used = len(PLAYBOOK_HEADER) // 4

        for lesson in lessons:
            confidence = lesson.effective_confidence(self.config.learning.half_life_days)
            entry = f"- ({lesson.kind}, {confidence:.0%}) When {lesson.trigger}: {lesson.guidance}"
            cost = len(entry) // 4 + 1
            if used + cost > budget:
                break
            lines.append(entry)
            used += cost

        for skill in skills or []:
            entry = (f"- (skill: {skill.name}, {skill.success_rate:.0%} success) "
                     f"{skill.description} Steps: {'; '.join(skill.steps[:6])}")
            cost = len(entry) // 4 + 1
            if used + cost > budget:
                break
            lines.append(entry)
            used += cost

        if len(lines) > 2:
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    # -- external memory (optional, additive) ------------------------------- #

    def external_briefing(self, query: str) -> str:
        """What the external provider would add, or "" — never an error.

        Called before the briefing is assembled. Everything here is
        fail-open on purpose: a service that cannot be reached subtracts
        nothing from a turn that worked fine before it existed. The lines
        are marked as coming from outside so a reader of the prompt knows
        which memories were earned here and which were fetched.
        """
        if not getattr(self.config.learning, "provider", None):
            return ""
        settings = getattr(self.config.learning.provider, "read_augment", False)
        if not settings:
            return ""
        try:
            from .providers.base import provider_from_config

            provider = provider_from_config(self.config)
        except Exception:
            return ""
        if provider is None:
            return ""
        try:
            lines = [line for line in provider.augment_recall(query) if line.strip()]
        except Exception:
            return ""
        if not lines:
            return ""
        return ("From your external memory service (unverified here):\n"
                + "\n".join(f"- {line}" for line in lines))

    # -- 3. credit -------------------------------------------------------- #

    def record_outcome(self, goal: str, messages: list[Any], recalled: list[Lesson],
                       success: bool, stopped: str, steps: int, elapsed: float,
                       approvals: int = 0, tokens: int = 0,
                       corrections: int = 0, cancel_reason: str = "",
                       cost_usd: float = 0.0,
                       measurement: dict[str, Any] | None = None) -> None:
        """Close the loop on one task: credit, store, then reflect in the background.

        `measurement` is the turn's paired record (`agent/tokens.py`) — counts
        only — kept with the episode so `comodor insights` can aggregate it.
        """
        if not self.config.learning.enabled:
            # Off is off: nothing durable is written from a finished task —
            # not an episode, not a signal, not a lesson, not a fact.
            return
        tools_used = sorted({message.name for message in messages
                             if getattr(message.role, "value", "") == "tool" and message.name})
        errors = [message for message in messages
                  if getattr(message.role, "value", "") == "tool" and message.is_error]

        episode = self.store.add_episode(Episode(
            session_id=self.session_id,
            goal=goal[:1000],
            scope=self.project_scope,
            success=success,
            stopped=stopped,
            steps=steps,
            elapsed=elapsed,
            tools_used=tools_used,
            error_kind=(errors[-1].name if errors else ""),
            approvals_asked=approvals,
            tokens=tokens,
            corrections=corrections,
            retries=len(errors),
            rules_active=len(self.active_rules()),
            cost_usd=cost_usd,
            measurement=dict(measurement or {}),
        ))

        # One task is one bag of words that belonged together. This is where
        # the vocabulary comes from, and it costs a few hundred microseconds
        # against work that has just taken seconds.
        if self.config.learning.associative:
            self._learn_vocabulary(goal, tools_used, messages)

        if self.config.learning.corrections:
            self.detector.record_retries(messages, episode.id)

        if recalled:
            # Credit assignment is coarse on purpose: precisely attributing a
            # multi-step outcome to individual lessons is not solvable here, and
            # over many episodes the coarse signal still separates the useful
            # lessons from the useless ones.
            self.store.credit([lesson.id for lesson in recalled], won=success)

        self._learn_async(goal, list(messages), stopped, episode.id,
                          cancel_reason=cancel_reason)

    # -- 4. reflect ------------------------------------------------------- #

    def _learn_async(self, goal: str, messages: list[Any], outcome: str,
                     episode_id: int, cancel_reason: str = "") -> None:
        """The model-backed passes over a finished task, on one worker.

        Reflection distils lessons; the review curates facts. Each is one
        model call against the same gateway, and they used to start on two
        threads at once — which made their order a scheduling accident. In
        production that was two requests in flight for one turn; against a
        scripted provider it handed the reflection's reply to the review one
        run in forty, and a lesson was never learned. One worker runs them in
        a fixed order, reflection first, so the order is a fact of the code
        rather than of the scheduler, and one request is in flight at a time.
        """
        enabled = bool(self.config.learning.enabled)
        reflect = bool(enabled and self.config.learning.reflect and self.gateway is not None)
        review = bool(enabled and self.config.learning.review
                      and self.gateway is not None)
        if not reflect and not review:
            return
        # The review's "latest wins" ticket is drawn here, on the turn's own
        # thread, so two turns' reviews rank in the order the turns ended even
        # when the earlier one runs behind a slower reflection.
        generation = self._ensure_reviewer().reserve() if review else None
        thread = threading.Thread(
            target=self._learn_in_background,
            args=(goal, messages, outcome, episode_id, cancel_reason,
                  reflect, generation),
            daemon=True, name="comodor-learn",
        )
        thread.start()
        with self._threads_lock:
            self._threads.append(thread)

    def _learn_in_background(self, goal: str, messages: list[Any], outcome: str,
                             episode_id: int, cancel_reason: str,
                             reflect: bool, generation: int | None) -> None:
        if reflect:
            try:
                self._reflect(goal, messages, outcome, episode_id)
            except Exception:              # noqa: BLE001 - the review still runs
                pass
        if generation is not None:
            # The reviewer keeps its own thread; this worker waits for it, so
            # a join on the worker is a join on everything the task started.
            thread = self._review_async(messages, outcome, episode_id,
                                        cancel_reason=cancel_reason,
                                        generation=generation)
            if thread is not None:
                thread.join()

    def _ensure_reviewer(self):
        if self._reviewer is None:
            from .review import Reviewer

            self._reviewer = Reviewer(
                self.facts, self.gateway,
                model=self.config.learning.review_model,
                write_scope=self.write_scope,
                staging=self.config.learning.review_write_approval,
            )
            self._reviewer.on_accepted = self._announce_facts
        return self._reviewer

    def _review_async(self, messages: list[Any], outcome: str,
                      episode_id: int, cancel_reason: str = "",
                      generation: int | None = None) -> threading.Thread | None:
        """The curated-memory review, after the turn has fully ended.

        Announced through the bus when something stuck, for the same reason
        every other learned thing is announced: silent adaptation is the
        version of this feature nobody trusts. Returns the thread it started
        for the worker that started it to wait on; it is not added to
        `_threads`, because the worker already there outlives it.
        """
        if not self.config.learning.enabled or not self.config.learning.review:
            return None
        if self.gateway is None:
            return None
        return self._ensure_reviewer().review_async(
            messages, outcome, episode_id, cancel_reason=cancel_reason,
            generation=generation)

    def _announce_facts(self, facts: list[Any], staged: bool) -> None:
        """Say what the review wrote, once it has actually written it."""
        if not facts:
            return
        verb = "proposed" if staged else "remembered"
        self.bus.emit(
            Kind.MEMORY, action="facts",
            items=[fact.as_dict() if hasattr(fact, "as_dict") else {"text": str(fact)}
                   for fact in facts],
            staged=staged, verb=verb)

    def _reflect(self, goal: str, messages: list[Any], outcome: str,
                 episode_id: int) -> None:
        model = self.config.learning.reflect_model or self.config.active_model()
        result = reflection_module.reflect(
            gateway=self.gateway, model=model, goal=goal, messages=messages,
            outcome=outcome, scope=self.write_scope, source=f"episode:{episode_id}",
        )
        if result.empty:
            return

        with self._reflect_lock:
            learned, merged, refused = self._absorb(result.lessons, messages)
            if result.skill is not None:
                self.store.add_skill(result.skill)

        if learned or merged or refused or result.skill:
            self.bus.emit(
                Kind.MEMORY, action="learned",
                items=[lesson.as_dict() for lesson in learned],
                merged=merged, refused=len(refused),
                skill=result.skill.name if result.skill else "",
            )

    # -- the admission gate ---------------------------------------------- #

    def admit(self, lesson: Lesson, *, provenance: str, source_ref: str = "",
              fingerprint: str = "") -> Lesson:
        """The one door to a durable lesson (FR-056, contracts §L1).

        Every lesson the engine stores comes through here with the
        provenance its caller can vouch for; the store refuses anything
        else at its own door too, so a caller that goes around this method
        gains nothing by it.
        """
        lesson.provenance = provenance
        lesson.source_ref = source_ref or lesson.source_ref
        lesson.fingerprint = fingerprint or lesson.fingerprint
        return self.store.add_lesson(lesson)

    def _absorb(self, lessons: list[Lesson],
                messages: list[Any]) -> tuple[list[Lesson], int, list[Lesson]]:
        """Store the reflected lessons the transcript corroborates.

        A reflected lesson is the model's own assertion. It is stored — or
        merged into a lesson already held — only once something in the
        episode backs it: the person said it, or an observing tool showed
        it (FR-056). The rest are refused and counted, never written.
        """
        stored: list[Lesson] = []
        refused: list[Lesson] = []
        merged = 0
        for lesson in lessons:
            provenance, source_ref, fingerprint = corroborate(lesson.text, messages)
            if not provenance:
                refused.append(lesson)
                continue
            existing = self.store.find_similar(lesson.text, threshold=0.55,
                                               scopes=self.scopes)
            if existing is not None:
                # Seeing the same thing twice is evidence, not a duplicate.
                existing.confidence = min(0.98, existing.confidence + 0.08)
                existing.wins += 1
                self.store.update_lesson(existing)
                merged += 1
                continue
            stored.append(self.admit(lesson, provenance=provenance,
                                     source_ref=source_ref, fingerprint=fingerprint))
        return stored, merged, refused

    # -- settled decisions (FR-109, SC-017) -------------------------------- #

    def settle_decision(self, question: str, answer: str,
                        source_ref: str = "answered form") -> Lesson | None:
        """A decision the person made through a form, kept for the project.

        Only an answer settles anything: a form that was cancelled, declined,
        expired or unattended never reaches here (T106). A later answer to
        the same question supersedes the earlier one, which stays on record
        (FR-059). Returns the stored decision, or None when learning is off
        or there was nothing to keep.
        """
        if not self.config.learning.enabled:
            return None
        question = " ".join(str(question or "").split())
        answer = " ".join(str(answer or "").split())
        if not question or not answer:
            return None
        previous = [decision for decision in self.settled_decisions()
                    if _same_question(decision.trigger, question)]
        if any(decision.guidance == answer for decision in previous):
            return next(d for d in previous if d.guidance == answer)
        stored = self.admit(
            Lesson(kind="decision", scope=self.project_scope, trigger=question[:300],
                   guidance=answer[:600], confidence=0.9, source="user"),
            provenance="settled_decision", source_ref=source_ref)
        for older in previous:
            self.store.supersede("lessons", older.id, stored.id)
        self.bus.emit(Kind.MEMORY, action="decision", items=[stored.as_dict()],
                      superseded=[older.id for older in previous])
        return stored

    def settled_decisions(self) -> list[Lesson]:
        """The decisions this project has settled, newest first — active only."""
        if not self.config.learning.enabled:
            return []
        return [lesson for lesson in self.store.all_lessons([self.project_scope])
                if lesson.provenance == "settled_decision" and lesson.status == "active"]

    def wait_for_reflection(self, timeout: float = 30.0) -> None:
        """Block until every background learning pass has settled.

        Used by tests and at exit. When this returns before the deadline,
        nothing the engine started is still running and everything it
        learned is in the store: the wait re-reads the thread list after
        every join rather than snapshotting it once, because a pass can start
        another (the worker starts the review) after the snapshot was taken.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._threads_lock:
                self._threads[:] = [thread for thread in self._threads
                                    if thread.is_alive()]
                alive = list(self._threads)
            if not alive:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            alive[0].join(timeout=remaining)

    # -- 5. consolidate --------------------------------------------------- #

    def _learn_vocabulary(self, goal: str, tools: list[str], messages: list) -> None:
        """Relate the words of one finished task.

        The goal, what the tools touched, and what the user said — not the
        model's own prose, which is long, fluent and mostly filler, and would
        swamp the counts with words nobody chose.
        """
        try:
            said = [message.content for message in messages
                    if getattr(message.role, "value", "") == "user"
                    and message.content][:6]
            targets = [message.name for message in messages
                       if getattr(message.role, "value", "") == "tool"
                       and message.name][:20]
            self.associations.observe(goal, " ".join(tools), " ".join(targets), *said)
        except Exception:                  # noqa: BLE001 - never fatal
            pass

    def consolidate(self) -> int:
        learning = self.config.learning
        if self._associations is not None:
            try:
                self._associations.prune()
                self.store.save_associations(self._associations)
            except Exception:              # noqa: BLE001 - never fatal
                pass
        self._curate_if_due()
        return self.store.consolidate(learning.min_confidence, learning.half_life_days)

    def _curate_if_due(self) -> None:
        """The curator's idle trigger, riding the shutdown path.

        This runs when the interface closes — the one moment the agent is
        provably not mid-task — and only when the interval has passed. A
        pass costs no tokens and takes milliseconds, so it rides here rather
        than earning its own daemon.
        """
        try:
            if not self.config.curator.enabled:
                return
            from . import curator

            if not curator.due(self.store, self.config.curator.interval_days):
                return
            curator.run(self.store, self.config, skills_root=self.config.paths.skills)
        except Exception:                  # noqa: BLE001 - never fatal
            pass

    # -- user-facing controls --------------------------------------------- #

    def teach(self, text: str, kind: str = "preference", pinned: bool = True) -> Lesson:
        """Record something the user stated directly.

        Pinned by default and given high confidence: an explicit instruction is
        much better evidence than anything the agent infers on its own.
        """
        trigger, _, guidance = text.partition(":")
        if not guidance:
            trigger, guidance = "generally", text
        lesson = Lesson(
            kind=kind, scope=self.write_scope,
            trigger=trigger.strip()[:300] or "generally",
            guidance=guidance.strip()[:600],
            confidence=0.9, pinned=pinned, source="user",
        )
        stored = self.admit(lesson, provenance="user_statement", source_ref="taught directly")
        self.bus.emit(Kind.MEMORY, action="taught", items=[stored.as_dict()])
        return stored

    def forget(self, lesson_id: int) -> bool:
        removed = self.store.delete_lesson(lesson_id)
        if removed:
            self.bus.emit(Kind.MEMORY, action="forgot", id=lesson_id)
        return removed

    def pin(self, lesson_id: int, pinned: bool = True) -> bool:
        for lesson in self.store.all_lessons():
            if lesson.id == lesson_id:
                lesson.pinned = pinned
                self.store.update_lesson(lesson)
                return True
        return False

    def feedback(self, lessons: list[Lesson], good: bool, note: str = "") -> None:
        """Explicit good or bad on the last answer."""
        if lessons:
            self.store.credit([lesson.id for lesson in lessons], won=good)
        for lesson in lessons:
            self.store.add_feedback("lesson", lesson.id, 1.0 if good else -1.0, note)
        self.bus.emit(Kind.MEMORY, action="feedback", good=good,
                      count=len(lessons), note=note)

    def search(self, query: str, limit: int = 20) -> list[Lesson]:
        if not query.strip():
            return self.store.all_lessons(self.scopes)[:limit]
        return [lesson for lesson, _ in
                self.store.search_lessons(query, self.scopes, limit=limit)]

    # -- curated facts: user-facing controls ------------------------------- #

    def fact_entries(self, include_staged: bool = False) -> list:
        try:
            return self.facts.entries(include_staged=include_staged)
        except Exception:
            return []

    def add_fact(self, text: str, kind: str = "memory") -> Any:
        """The user wrote a fact by hand. Settled at once, pinned to nothing."""
        stored = self.facts.add(text, kind=kind)
        self.refresh_facts()
        self._mirror_write(stored)
        self.bus.emit(Kind.MEMORY, action="taught", items=[stored.as_dict()])
        return stored

    def _mirror_write(self, stored: Any) -> None:
        """Offer one settled fact to the external provider, if there is one.

        After the local write and its snapshot refresh, on purpose: the
        local truth is already saved, so the mirror failing changes a log
        line and nothing else. This is the whole contract — the brain here
        is primary, the cloud is a copy.
        """
        try:
            from .providers.base import provider_from_config

            provider = provider_from_config(self.config)
        except Exception:
            return
        if provider is None:
            return
        try:
            landed = provider.mirror_write(
                str(getattr(stored, "text", "") or ""),
                str(getattr(stored, "kind", "memory") or "memory"))
        except Exception:
            return
        if not landed:
            self.bus.emit(Kind.NOTICE, text="the external memory service did "
                          "not confirm the write; the fact is saved locally")

    def remove_fact(self, fact_id: int) -> bool:
        for fact in self.facts.entries(include_staged=True):
            if fact.id == fact_id:
                self.facts.store.delete_fact(fact_id)
                self.refresh_facts()
                self.bus.emit(Kind.MEMORY, action="forgot_fact", id=fact_id)
                return True
        return False

    def decide_fact(self, fact_id: int, approve: bool) -> bool:
        """Approve or reject a staged fact proposed by the review."""
        from .facts import STATUS_SETTLED

        if approve:
            done = self.facts.set_staged(fact_id, STATUS_SETTLED)
        else:
            done = self.facts.store.delete_fact(fact_id)
        if done:
            self.refresh_facts()
        return done

    def pin_fact(self, fact_id: int, pinned: bool = True) -> bool:
        done = self.facts.pin(fact_id, pinned)
        if done:
            self.refresh_facts()
        return done

    # -- house rules ------------------------------------------------------ #

    def all_rules(self) -> list[Rule]:
        return self.store.all_rules(self.scopes)

    def teach_rule(self, statement: str) -> Rule:
        """A rule the user stated outright, which outranks anything inferred."""
        key = "user." + "-".join(statement.lower().split()[:4])[:60]
        rule = self.store.observe_rule(
            key=key, scope=self.write_scope, category="preference",
            statement=statement.strip()[:300], detail="you told me directly",
            source="user", weight=3,
            provenance="user_statement", source_ref="stated directly")
        self.bus.emit(Kind.MEMORY, action="rule", items=[rule.as_dict()])
        return rule

    def forget_rule(self, rule_id: int) -> bool:
        removed = self.store.delete_rule(rule_id)
        if removed:
            self.bus.emit(Kind.MEMORY, action="forgot_rule", id=rule_id)
        return removed

    def set_rule(self, rule_id: int, *, pinned: bool | None = None,
                 active: bool | None = None) -> bool:
        return self.store.set_rule_flags(rule_id, pinned=pinned, active=active)

    def export_rules(self, target: Path | None = None) -> Path:
        """Write the learned conventions where a team can read and commit them."""
        destination = Path(target) if target else (
            self.config.paths.project_dir / "house-rules.md")
        rules = [rule for rule in self.all_rules() if rule.confident]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            rules_module.export_markdown(rules, project=str(self.config.paths.project)),
            encoding="utf-8")
        return destination

    def stats(self) -> dict[str, Any]:
        """What the store holds, and what applies *here*.

        `rules_active` is overridden on the way out. The store counts every
        confident rule it has, across every project it has ever learned in,
        which is the right answer for `doctor` and the wrong one for anything
        telling somebody what is shaping the conversation in front of them.

        The two disagreed by eight: rules learned in another folder, counted
        in the status strip, and absent from the panel that lists them —
        because the panel is scoped and the count was not. A number nobody can
        click through to is a number to distrust, and rightly.
        """
        data = self.store.stats()
        data["scope"] = self.project_scope
        data["rules_everywhere"] = data.get("rules_active", 0)
        data["rules_active"] = len(self.active_rules())
        data["rules_here"] = len(self.store.all_rules(self.scopes))
        data["facts_here"] = len(self.facts.entries())
        data["review_cost_usd"] = self.review_spent
        return data

    def close(self) -> None:
        self.wait_for_reflection(timeout=5.0)
        self.store.close()


def _brief(item: Any) -> dict[str, Any]:
    return {"id": getattr(item, "id", 0),
            "text": getattr(item, "statement", "") or getattr(item, "text", "")}
