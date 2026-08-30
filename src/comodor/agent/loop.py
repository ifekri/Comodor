"""The reason/act loop.

One turn is: assemble context, stream a response, run whatever tools it asked
for, feed the results back, repeat. It ends when the model stops asking for
tools, or when a guard trips — step count, wall clock, or spend.

Three details are worth knowing:

*Loop off means one step.* The ``Loop`` switch in the status bar decides whether
the agent may iterate after the first round of tools or must hand control back.

*Read-only tools run in parallel.* When a round contains only ``SAFE`` calls and
they need no approval, they execute concurrently — several file reads should not
cost several round trips of latency. Results are still reported in call order so
the transcript stays deterministic.

*Cancellation is cooperative and checked everywhere.* Between steps, between
stream chunks, and inside the shell tool, so Esc stops the agent within a
fraction of a second rather than at the end of the current model response.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..events import Cancellation, Cancelled, EventBus, Kind
from ..providers.base import (
    EventType,
    Message,
    ProviderError,
    ToolCall,
    ToolSpec,
    Usage,
)
from ..providers.gateway import Gateway
from ..safety import PermissionEngine, Risk
from ..tools import ToolContext, ToolRegistry, ToolResult
from .context import Conversation
from .prompts import COMPACT_PROMPT, build_system_prompt

MAX_PARALLEL_TOOLS = 6
#: Blank line between the skill block and the playbook block.
SECTION_GAP = "\n\n"


@dataclass
class TurnResult:
    """What one user turn produced."""

    text: str = ""
    steps: int = 0
    tool_calls: int = 0
    usage: Usage = field(default_factory=Usage)
    stopped: str = "done"        # done | max_steps | budget | cancelled | error
    error: str = ""
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.stopped in ("done", "max_steps")


class AgentLoop:
    """Drives one conversation against one gateway and one tool set."""

    def __init__(self, config: Config, gateway: Gateway, tools: ToolRegistry,
                 bus: EventBus, permissions: PermissionEngine,
                 conversation: Conversation | None = None,
                 memory: Any = None, skills: Any = None) -> None:
        self.config = config
        self.gateway = gateway
        self.tools = tools
        self.bus = bus
        self.permissions = permissions
        self.conversation = conversation or Conversation()
        self.memory = memory                     # LearningEngine, or None
        self.skills = skills                     # SkillRegistry, or None
        self.cancel = Cancellation()
        self._skills_used: list[Any] = []
        self.tool_context: ToolContext | None = None
        self._recalled: list[Any] = []
        #: Every tool this turn reached for, in order. Read at the end of the
        #: turn to tell "it says the tests pass and ran them" from "it says the
        #: tests pass".
        self._used: list[str] = []
        #: Worked out once. The model does not change mid-turn, and reading a
        #: cached catalogue from disk on every step would be a file read per
        #: message for an answer that cannot have moved.
        self._profile: Any = None

    # -- public API ------------------------------------------------------- #

    def run(self, user_text: str, images: list[str] | None = None) -> TurnResult:
        """Handle one user message from start to finish."""
        started = time.monotonic()
        self.cancel.reset()
        self._used = []
        result = TurnResult()

        # Recall runs before the message is stored, not after, so that what it
        # finds travels *with* the turn instead of in the system prompt. That
        # ordering is the whole of the caching win: the head of the request then
        # never changes, and every request after the first is served from the
        # provider's cache at a tenth of the price. See providers/caching.py.
        playbook = self._recall(user_text)
        self.conversation.add(
            Message.user(user_text, images=images or [], briefing=playbook))
        self.bus.emit(Kind.TURN_START, text=user_text)

        deadline = started + self.config.agent.max_seconds

        try:
            # Filled in as it goes rather than returned at the end. A turn that
            # fails halfway has still read files and made edits, and a result
            # built only on the way out reports none of it: `steps: 0,
            # tool_calls: 0` for a turn that changed the project. Every caller
            # then believes nothing happened — the headless JSON, the turn
            # summary, and the lesson the brain records about how much this
            # took.
            self._iterate(deadline, result)
        except Cancelled:
            result.stopped = "cancelled"
            self.bus.emit(Kind.CANCELLED)
        except ProviderError as exc:
            result.stopped = "error"
            result.error = str(exc)
            self.bus.emit(Kind.ERROR, text=str(exc))
        except Exception as exc:                  # a bug here must not kill the UI
            result.stopped = "error"
            result.error = f"{type(exc).__name__}: {exc}"
            self.bus.emit(Kind.ERROR, text=result.error)

        result.elapsed = time.monotonic() - started
        result.usage = self.conversation.usage
        self._say_if_unverified(result)
        self.bus.emit(Kind.TURN_END, stopped=result.stopped, steps=result.steps,
                      elapsed=result.elapsed, error=result.error)

        self._learn(user_text, result)
        return result

    def interrupt(self) -> None:
        self.cancel.cancel()

    # -- the loop --------------------------------------------------------- #

    def _iterate(self, deadline: float, result: TurnResult) -> TurnResult:
        agent = self.config.agent

        while True:
            self.cancel.raise_if_cancelled()
            result.steps += 1

            specs = self.tools.specs(agent.mode)
            system_prompt = build_system_prompt(self.config)
            self._maybe_compact(system_prompt, specs)

            completion = self._stream_once(system_prompt, specs)
            assistant = completion["message"]
            self.conversation.add(assistant)

            calls: list[ToolCall] = assistant.tool_calls
            if not calls:
                result.text = assistant.content
                result.stopped = "done"
                return result

            result.tool_calls += len(calls)
            self._execute(calls)
            self.bus.emit(Kind.STEP, step=result.steps, tool_calls=len(calls))

            if not agent.loop:
                # Loop off: run the tools the model asked for, then stop and
                # let the user decide whether to continue.
                result.stopped = "done"
                result.text = assistant.content
                return result

            # Zero means no limit, for each of these. A step count is not a
            # measure of risk, so it is off by default; the two that follow
            # are, and stay on.
            if agent.max_steps and result.steps >= agent.max_steps:
                result.stopped = "max_steps"
                self._note(f"Stopped after {agent.max_steps} steps — the step "
                           f"limit for one task. Say 'continue' to keep going, "
                           f"or set agent.max_steps to 0 for no limit.")
                return result

            if agent.max_seconds and time.monotonic() > deadline:
                result.stopped = "budget"
                self._note(f"Stopped after {agent.max_seconds:.0f}s — the time "
                           f"limit for one task. Say 'continue' to keep going, "
                           f"or raise agent.max_seconds.")
                return result

            spent = self.conversation.usage.cost_usd
            if agent.max_cost_usd and spent >= agent.max_cost_usd:
                result.stopped = "budget"
                self._note(f"Stopped at ${spent:.2f} — the spend limit for one "
                           f"task. Say 'continue' to keep going, or raise "
                           f"agent.max_cost_usd.")
                return result

    # -- model call ------------------------------------------------------- #

    def _stream_once(self, system_prompt: str, specs: list[ToolSpec]) -> dict[str, Any]:
        """One streamed assistant response, surfaced to the UI as it arrives."""
        payload = self.conversation.render(system_prompt)
        agent = self.config.agent

        self.bus.emit(Kind.ASSISTANT_START)
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = Usage()

        stream = self.gateway.stream(
            payload,
            tools=specs or None,
            model=self.config.model,
            temperature=agent.temperature,
            max_tokens=agent.max_output_tokens,
            cache=agent.prompt_cache,
            cache_ttl=agent.prompt_cache_ttl,
        )

        for event in stream:
            self.cancel.raise_if_cancelled()
            if event.type is EventType.TEXT:
                text_parts.append(event.text)
                self.bus.emit(Kind.ASSISTANT_DELTA, text=event.text)
            elif event.type is EventType.REASONING:
                reasoning_parts.append(event.text)
                self.bus.emit(Kind.REASONING_DELTA, text=event.text)
            elif event.type is EventType.TOOL_CALL and event.tool_call:
                tool_calls.append(event.tool_call)
            elif event.type is EventType.USAGE and event.usage:
                usage = usage.merge(event.usage)

        text = "".join(text_parts)
        self.bus.emit(Kind.ASSISTANT_END, text=text,
                      tool_calls=[call.name for call in tool_calls])

        self.conversation.record_usage(usage)
        if usage.prompt_tokens:
            # What the model *read*, not what it was billed for. With caching on
            # those differ by an order of magnitude, and it is the former the
            # context gauge is measuring.
            self.conversation.counter.observe_usage(payload, specs, usage.prompt_tokens)
        self._emit_usage(system_prompt, specs)

        message = Message.assistant(text, tool_calls)
        if reasoning_parts:
            message.meta["reasoning"] = "".join(reasoning_parts)
        route = self.gateway.last_route
        if route:
            message.meta["provider"] = route.provider
            message.meta["model"] = route.model
            if route.failed_over_from:
                self._note(f"{', '.join(route.failed_over_from)} failed — "
                           f"served by {route.provider}.")
        return {"message": message, "usage": usage}

    # -- tools ------------------------------------------------------------ #

    def _execute(self, calls: list[ToolCall]) -> None:
        context = self._tool_context()
        parallel = self._can_parallelise(calls)

        if parallel and len(calls) > 1:
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TOOLS, len(calls))) as pool:
                futures = [pool.submit(self._run_one, call, context) for call in calls]
                results = [future.result() for future in futures]
        else:
            results = [self._run_one(call, context) for call in calls]

        for call, result in zip(calls, results, strict=True):
            message = Message.tool(
                call_id=call.id, name=call.name,
                content=result.content, is_error=not result.ok,
            )
            # A tool that produced a picture — a screenshot of a page — sends
            # it as one. Where the dialect allows an image beside a tool result
            # it goes there; where it does not, the adapter moves it.
            picture = result.meta.get("image")
            if isinstance(picture, str) and picture:
                message.images = [picture]
            self.conversation.add(message)

    def _run_one(self, call: ToolCall, context: ToolContext) -> ToolResult:
        self._used.append(call.name)
        self.bus.emit(Kind.TOOL_START, id=call.id, name=call.name,
                      arguments=call.arguments,
                      summary=self._describe(call))
        if self.cancel.cancelled:
            result = ToolResult.failure("cancelled before the tool ran")
        else:
            result = self.tools.invoke(call.name, context, call.arguments)
        self.bus.emit(Kind.TOOL_END, id=call.id, name=call.name, ok=result.ok,
                      content=result.content, display=result.rendered,
                      elapsed=result.elapsed, meta=result.meta)
        return result

    def _describe(self, call: ToolCall) -> str:
        tool = self.tools.get(call.name)
        return tool.summary(call.arguments) if tool else call.name

    def _can_parallelise(self, calls: list[ToolCall]) -> bool:
        """Only when nothing in the batch could stop to ask a question."""
        if not self.config.safety.auto_approve_safe:
            return False
        for call in calls:
            tool = self.tools.get(call.name)
            if tool is None or tool.risk is not Risk.SAFE:
                return False
        return True

    def _tool_context(self) -> ToolContext:
        if self.tool_context is None:
            from ..safety import CheckpointStore, Redactor

            secrets = [entry.api_key for entry in self.config.providers.values()
                       if entry.api_key]
            self.tool_context = ToolContext(
                config=self.config,
                permissions=self.permissions,
                checkpoints=CheckpointStore(self.config.paths.checkpoints),
                bus=self.bus,
                redact=Redactor(secrets),
                cancel=self.cancel,
                cwd=Path(self.config.paths.project),
                emit_output=lambda text: self.bus.emit(Kind.TOOL_OUTPUT, text=text),
            )
        return self.tool_context

    # -- context management ----------------------------------------------- #

    def _maybe_compact(self, system_prompt: str, specs: list[ToolSpec]) -> None:
        agent = self.config.agent

        # Before measuring anything. Screenshots are the largest thing in a
        # desktop run's history and the fastest to go stale, and dropping them
        # is exact and free - where compaction is a model call. Doing it first
        # also means the measurement below is of what will actually be sent.
        gone = self.conversation.forget_old_pictures(
            getattr(agent, "keep_screenshots", 2))
        if gone:
            self._emit_usage(system_prompt, specs)
        limit = self._window()
        if not self.conversation.needs_compaction(limit, agent.compact_at,
                                                  system_prompt, specs):
            return

        removed = self.conversation.compact(self._summarise)
        if removed:
            self._note(f"Compacted {removed} earlier messages to free context.")
            self._emit_usage(system_prompt, specs)

    def _summarise(self, messages: list[Message]) -> str:
        """Ask the model to write the brief that replaces old history."""
        from ..providers.base import collapse

        transcript = "\n\n".join(
            f"[{message.role.value}] {message.content[:2000]}"
            for message in messages if message.content
        )
        completion = collapse(self.gateway.stream(
            [Message.system(COMPACT_PROMPT), Message.user(transcript)],
            model=self.config.model, temperature=0.2, max_tokens=1500,
        ))
        return completion.text

    def _window(self) -> int:
        """How much this model can actually read, cached for the turn.

        Not `agent.context_limit`, which defaults to a million and describes no
        model in particular. Point Comodor at a 32k model with that number in
        force and compaction never fires — the conversation grows past what the
        model can take, and the first sign is the provider refusing it.
        """
        if self._profile is None:
            from ..providers import profile

            try:
                self._profile = profile.of(self.config)
            except Exception:
                # Never the reason a turn does not run. The old constant is a
                # bad answer; no answer at all is a worse one.
                return self.config.agent.context_limit or 128_000
        return self._profile.context

    def _emit_usage(self, system_prompt: str, specs: list[ToolSpec]) -> None:
        limit = self._window()
        used = self.conversation.used_tokens(system_prompt, specs)
        usage = self.conversation.usage
        self.bus.emit(
            Kind.USAGE,
            context_used=used,
            context_limit=limit,
            fill=min(1.0, used / limit) if limit else 0.0,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
        )

    def _say_if_unverified(self, result: TurnResult) -> None:
        """Say so when the answer claims a suite passes and nothing ran it.

        The system prompt already forbids this. That is not the same as it not
        happening, and the user is the one person who cannot tell the two apart
        — the answer reads identically either way.
        """
        try:
            from .claims import unverified

            notice = unverified(result.text, self._used)
        except Exception:
            return
        if notice:
            self._note(notice)

    def _note(self, text: str) -> None:
        self.bus.emit(Kind.NOTICE, text=text)

    # -- learning --------------------------------------------------------- #

    def _recall(self, user_text: str) -> str:
        """Assemble what the model should know before it answers.

        Two independent sources: skills the user authored, and what the agent
        has learned by itself. They are gathered separately so switching one off
        — or having it fail — leaves the other working.
        """
        blocks = [self._skills_for(user_text), self._memory_for(user_text)]
        return SECTION_GAP.join(block for block in blocks if block)

    def _memory_for(self, user_text: str) -> str:
        """The learned playbook.

        Corrections are folded in *before* recall, so a fix the user made a
        minute ago governs the answer they are about to get, rather than the
        one after that.
        """
        self._recalled = []
        if self.memory is None or not self.config.learning.enabled:
            return ""

        try:
            self.memory.before_turn(user_text)
        except Exception:
            pass

        try:
            # The UI usually computed this while the user was still typing.
            lessons = self.memory.take_prefetched(user_text)
            if lessons is None:
                lessons = self.memory.recall(user_text)
            rules = self.memory.active_rules()
        except Exception:
            return ""

        self._recalled = lessons
        if lessons:
            self.bus.emit(Kind.MEMORY, action="recalled",
                          items=[lesson.as_dict() for lesson in lessons],
                          rules=len(rules))
        if not lessons and not rules:
            return ""
        return self.memory.render_playbook(lessons, rules=rules)

    def _skills_for(self, user_text: str) -> str:
        """Pick the authored skills that fit this request, and announce them.

        Skills are shown rather than applied silently for the same reason
        learned rules are: an instruction shaping the answer should be one the
        user can see and switch off.
        """
        self._skills_used = []
        settings = getattr(self.config, "skills", None)
        if self.skills is None or settings is None or not settings.enabled:
            return ""
        try:
            matched = self.skills.match(user_text, limit=settings.top_k)
        except Exception:
            return ""
        if not matched:
            return ""

        kept, dropped = self.skills.fit(matched, settings.max_tokens)
        for skill in dropped:
            # Naming the setting, because the fix is one number and the user
            # has no other way to discover that their skill never arrived.
            self._note(f"{skill.name} matched but is too large for the "
                       f"{settings.max_tokens:,}-token skill budget — raise "
                       f"skills.max_tokens to use it.")

        # Announced from what actually travelled. Announcing the match instead
        # tells the user a skill is shaping the answer when it was discarded.
        self._skills_used = kept
        if kept:
            self.bus.emit(Kind.MEMORY, action="skills",
                          items=[skill.as_dict() for skill in kept])
        return self.skills.render(kept, max_tokens=settings.max_tokens)

    def _learn(self, user_text: str, result: TurnResult) -> None:
        """Credit the lessons that were in play, then reflect on the episode."""
        if self.memory is None or not self.config.learning.enabled:
            return
        approvals, _ = self.permissions.take_stats()
        try:
            self.memory.record_outcome(
                goal=user_text,
                messages=self.conversation.messages,
                recalled=self._recalled,
                success=result.ok and result.stopped == "done",
                stopped=result.stopped,
                steps=result.steps,
                elapsed=result.elapsed,
                approvals=approvals,
                tokens=self.conversation.usage.total,
            )
        except Exception:
            # Learning is a background nicety; it must never break a turn.
            pass


def make_summariser(gateway: Gateway, model: str) -> Callable[[list[Message]], str]:
    """Standalone summariser, used by session export and tests."""
    from ..providers.base import collapse

    def summarise(messages: list[Message]) -> str:
        transcript = "\n\n".join(f"[{m.role.value}] {m.content[:2000]}"
                                 for m in messages if m.content)
        return collapse(gateway.stream(
            [Message.system(COMPACT_PROMPT), Message.user(transcript)],
            model=model, temperature=0.2, max_tokens=1500,
        )).text

    return summarise
