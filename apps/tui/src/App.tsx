/**
 * The screen.
 *
 * Enough of an interface to prove the architecture and no more: a header, the
 * conversation, a composer, the mode switcher, a footer, a command palette
 * and a question card. Not an IDE in a terminal — that is later phases, and
 * building it now would mean building it against a protocol nobody had used.
 *
 * Every colour comes from `@comodor/design-tokens` by name. Nothing here
 * knows what `#ff9d5c` is, which is what lets a browser render the same
 * component set from the same names.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import type { KeyEvent, ScrollBoxRenderable } from "@opentui/core";

import { CoreClient } from "@comodor/client";
import { terminal as theme } from "@comodor/design-tokens";
import { MODES, type Mode } from "@comodor/modes";
import type { EventName, Session } from "@comodor/protocol";
import {
  beginIntent,
  followMarker,
  followMoved,
  followSent,
  followStart,
  followTail,
  grew,
  initial,
  intentConfirmed,
  intentDue,
  intentSending,
  reduce,
  refuseIntent,
  stepIntent,
  timeline,
  unsent,
  wantMode,
  type Follow,
  type Line,
  type ModeIntent,
  type Snapshot,
  type State,
  type ToolRun,
  type ToolState,
} from "@comodor/session";
import {
  allowsWriting,
  answer as answerOf,
  answerable,
  begin,
  cancel as cancelOf,
  current as currentQuestion,
  isSelected,
  move,
  optionAt,
  startWriting,
  step,
  stopWriting,
  toggle,
  type as typeInto,
  type FormState,
} from "@comodor/questions";

import { build, type Screen } from "./commands.ts";
import {
  move as movePalette,
  open as openPalette,
  search as searchPalette,
  selected as selectedCommand,
  window as paletteWindow,
  type PaletteState,
} from "./palette.ts";

export interface AppProps {
  readonly client: CoreClient;
  readonly onQuit: () => void;
  /**
   * A session the core already has.
   *
   * Given one, the client rebuilds itself from `session.snapshot` instead of
   * creating a second session. That is what a remount is: the projection is
   * gone, the session is not, and a client that answered by creating another
   * one would leave the first still running with nobody attached.
   */
  readonly sessionId?: string | undefined;
}

/** Below this the sidebar-free single column is the only thing that fits. */
const NARROW = 80;

/** How many rows a page key moves. Less than a screen, so context carries over. */
const PAGE = 8;

export function App({ client, onQuit, sessionId }: AppProps): React.ReactNode {
  const [state, dispatch] = useReducer(reduce, initial);
  const [draft, setDraft] = useState("");
  const [palette, setPalette] = useState<PaletteState<Screen> | undefined>();
  const [question, setQuestion] = useState<FormState | undefined>();
  const [intent, setIntent] = useState<ModeIntent>(() => beginIntent("act"));
  const [follow, setFollow] = useState<Follow>(followStart);
  const { width } = useTerminalDimensions();

  const registry = useMemo(() => build(), []);
  const latest = useRef(state);
  latest.current = state;
  const scroller = useRef<ScrollBoxRenderable | null>(null);

  // Keys can arrive faster than React re-renders — a key repeat, a paste,
  // or simply two presses in one tick — and a handler that closed over
  // `question` would then apply the second press to the state before the
  // first. Every update below is functional, and these refs are what the
  // *branching* reads, so both halves see what is actually current.
  const questionRef = useRef(question);
  questionRef.current = question;
  const paletteRef = useRef(palette);
  paletteRef.current = palette;

  // -- the connection --------------------------------------------------- //

  /**
   * Ask the core what the session actually looks like, and adopt the answer.
   *
   * The repair for a gap, and the way a rebuilt client catches up. Safe to
   * call at any moment, including mid-turn: the snapshot names the sequence
   * number it includes up to, and the projection drops anything at or below
   * it. Whichever of the snapshot and the next delta arrives first, the
   * result is the same.
   */
  const resync = useCallback(async (id: string) => {
    dispatch({ type: "resynchronising" });
    try {
      const answer = await client.call("session.snapshot", { session_id: id });
      dispatch({ type: "snapshot", snapshot: answer["snapshot"] as Snapshot });
    } catch (problem) {
      dispatch({ type: "lost", reason: (problem as Error).message });
    }
  }, [client]);

  useEffect(() => {
    let alive = true;
    const stop = client.on((name: EventName, params, seq) => {
      if (!alive) return;
      dispatch({ type: "event", name, params, seq });
      if (name === "question.requested") {
        setQuestion(begin(params as never));
      } else if (name === "question.resolved") {
        setQuestion(undefined);
      } else if (name === "mode.changed") {
        // The core is the authority, and this is it speaking — whoever asked.
        setIntent((was) => intentConfirmed(was, params["mode"] as Mode));
      }
    });

    void (async () => {
      try {
        if (sessionId) {
          await resync(sessionId);
        } else {
          const made = await client.call("session.create");
          if (!alive) return;
          const session = made["session"] as Session;
          dispatch({ type: "connected", session });
          setIntent(beginIntent(session.mode as Mode));
        }
      } catch (problem) {
        if (alive) {
          dispatch({ type: "lost", reason: (problem as Error).message });
        }
      }
    })();

    return () => { alive = false; stop(); };
  }, [client, resync, sessionId]);

  // A hole in the sequence means an event never arrived, and no amount of
  // later events repairs that. Asking the core is the only honest answer.
  useEffect(() => {
    const id = state.session?.id;
    if (state.gap && id) void resync(id);
  }, [state.gap, state.session?.id, resync]);

  // -- mode intent -------------------------------------------------------- //

  /**
   * One mutation in flight per session, and the *current* intent is what goes
   * out next — not the intermediate modes it passed through on the way.
   *
   * Running as an effect rather than inside the key handler is what makes
   * three presses in one tick collapse into at most two requests: React has
   * already folded them into one intent by the time this reads it.
   */
  useEffect(() => {
    const id = state.session?.id;
    const next = intentDue(intent);
    if (!id || next === undefined) return;
    setIntent((was) => intentSending(was, next));
    void client.call("session.set_mode", { session_id: id, mode: next })
      .catch((problem: unknown) => {
        // A refusal is final: intent falls back to what the core has, so this
        // does not turn into a loop against a settled no.
        setIntent((was) => refuseIntent(was, (problem as Error).message));
        dispatch({ type: "event", name: "notification.created", seq: 0,
                   params: { level: "warning",
                             text: (problem as Error).message } });
      });
  }, [client, intent, state.session?.id]);

  // -- following the newest line ------------------------------------------ //

  /** Whether the viewport is showing the end of the conversation. */
  const atTail = useCallback((): boolean => {
    const box = scroller.current;
    if (!box) return true;
    // Exact, deliberately: a wheel notch is one row, and a tolerance that
    // counted that as "at the tail" would let new output yank the viewport
    // right back after the first notch of an upward scroll.
    return box.scrollTop >= box.scrollHeight - box.viewport.height;
  }, []);

  const toTail = useCallback(() => {
    scroller.current?.scrollTo(Number.MAX_SAFE_INTEGER);
    setFollow(followTail());
  }, []);

  const scrollBy = useCallback((rows: number) => {
    const box = scroller.current;
    if (!box) return;
    box.scrollBy(rows);
    setFollow((was) => followMoved(was, atTail()));
  }, [atTail]);

  // Content arrived. Following: nothing to do, the box is sticky and the tail
  // moved with it. Paused: the viewport stays put and the marker goes up.
  useEffect(() => {
    setFollow((was) => grew(was));
  }, [state.arrivals, state.lines, state.tools]);

  /**
   * Put one prompt to the core, and be honest about how it went.
   *
   * The composer clears on the way in, because a person who pressed Enter has
   * finished with that text — but the text is not thrown away, it moves into
   * the conversation as a *pending* line. If the core refuses, that line says
   * so and keeps every character. F1 cleared the composer and showed a
   * notification, which meant a refused send ate the paragraph.
   */
  const deliver = useCallback(async (localId: string, text: string) => {
    const id = latest.current.session?.id;
    if (!id) return;
    setFollow(followSent());
    try {
      const answer = await client.call("session.send",
                                       { session_id: id, text });
      dispatch({ type: "accepted", localId,
                 turnId: String(answer["turn_id"] ?? "") });
    } catch (problem) {
      dispatch({ type: "rejected", localId,
                 reason: (problem as Error).message });
    }
  }, [client]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || !latest.current.session?.id) return;
    const localId = `you-${latest.current.arrivals + 1}`;
    setDraft("");
    dispatch({ type: "sending", localId, text });
    await deliver(localId, text);
  }, [deliver, draft]);

  /**
   * Send again what the core never accepted.
   *
   * Only that. A turn the core *did* accept and which then failed is not
   * resent: whatever tools it ran already ran, and resubmitting it would run
   * them twice for a failure the person has not seen the shape of yet.
   */
  const retry = useCallback(async () => {
    const waiting = unsent(latest.current);
    const line = waiting[waiting.length - 1];
    if (!line) return;
    dispatch({ type: "retrying", localId: line.id });
    await deliver(line.id, line.text);
  }, [deliver]);

  // -- what a command is given ------------------------------------------- //

  const screen: Screen = useMemo(() => ({
    call: (method, params) => client.call(method as never, params ?? {}),
    sessionId: () => latest.current.session?.id,
    mode: () => (latest.current.session?.mode ?? "act") as Mode,
    busy: () => Boolean(latest.current.session?.busy),
    stepMode: (back: boolean) => setIntent((was) => stepIntent(was, back)),
    wantMode: (mode: Mode) => setIntent((was) => wantMode(was, mode)),
    openPalette: () => setPalette(openPalette(registry, screenRef.current)),
    closePalette: () => setPalette(undefined),
    paletteOpen: () => Boolean(palette),
    toTail,
    hasUnsent: () => unsent(latest.current).length > 0,
    retry: () => { void retry(); },
    quit: onQuit,
    note: () => {},
  }), [client, onQuit, palette, registry, toTail, retry]);

  // The commands are given the screen, and opening the palette needs the
  // screen to filter by. A ref breaks that circle without a second object.
  const screenRef = useRef<Screen>(undefined as unknown as Screen);
  screenRef.current = screen;

  // Every command is run through here.
  //
  // `registry.run` returns a promise, and a command that asks the core for
  // something the core refuses rejects it. Started with `void` and left
  // uncaught, that is an unhandled rejection — which is a crash in Node and
  // Bun, from a refusal the interface is perfectly able to show. The refusal
  // becomes a notification instead.
  const runCommand = useCallback((id: string) => {
    void registry.run(id, screenRef.current).catch((problem: unknown) => {
      // Seq 0: raised here rather than received, so it is outside the
       // core's sequence and must not move the revision.
       dispatch({ type: "event", name: "notification.created", seq: 0,
                  params: { level: "warning",
                            text: (problem as Error).message } });
    });
  }, [registry]);

  // -- keys --------------------------------------------------------------- //

  useKeyboard(useCallback((key: KeyEvent) => {
    const named = describeKey(key);
    const asked = questionRef.current;
    const open = paletteRef.current;

    if (asked) {
      if (named === "escape") {
        // While writing, Escape leaves the field rather than the form: losing
        // a typed answer to a key meant for the box is not a trade anybody
        // would choose.
        if (asked.writing) { setQuestion((was) => was && stopWriting(was)); return; }
        void client.call("question.answer", cancelOf(asked) as never);
        setQuestion(undefined);
        return;
      }
      if (named === "return" && answerable(asked)) {
        void client.call("question.answer", answerOf(asked) as never);
        setQuestion(undefined);
        return;
      }
      // While writing, the keys below belong to the text rather than to the
      // option list, and the branch after this one has them.
      if (asked.writing) {
        if (named === "backspace") {
          setQuestion((was) => was && typeInto(was, written(was).slice(0, -1)));
        } else if (named === "space") {
          setQuestion((was) => was && typeInto(was, `${written(was)} `));
        } else if (isPrintable(key)) {
          setQuestion((was) => was && typeInto(was, written(was) + key.name));
        }
        return;
      }
      if (named === "up") setQuestion((was) => was && move(was, -1));
      else if (named === "down") setQuestion((was) => was && move(was, 1));
      // A form has several questions; left and right walk between them.
      else if (named === "left") setQuestion((was) => was && step(was, -1));
      else if (named === "right") setQuestion((was) => was && step(was, 1));
      else if (named === "space") {
        // Choosing the write-your-own row is how a person reaches the field,
        // which is the same gesture as choosing any other option.
        setQuestion((was) => was && (optionAt(was)?.free
          ? startWriting(toggle(was)) : toggle(was)));
      }
      return;
    }


    if (open) {
      if (named === "escape") { setPalette(undefined); return; }
      if (named === "up") { setPalette((was) => was && movePalette(was, -1)); return; }
      if (named === "down") { setPalette((was) => was && movePalette(was, 1)); return; }
      if (named === "return") {
        // What is highlighted, not what happens to be first.
        const chosen = selectedCommand(open);
        setPalette(undefined);
        if (chosen) runCommand(chosen.id);
        return;
      }
      return;
    }

    // Ctrl+C is context-sensitive: it stops work, and only quits when there
    // is none. Killing the client mid-turn would leave a core running.
    if (named === "ctrl+c") {
      if (latest.current.session?.busy) runCommand("session.cancel");
      else onQuit();
      return;
    }

    // Reading the history. Handled here rather than left to the scroll box,
    // which only sees keys when it holds focus — and focus belongs to the
    // composer, because typing is what the window is mostly for.
    if (named === "pageup") { scrollBy(-PAGE); return; }
    if (named === "pagedown") { scrollBy(PAGE); return; }

    const command = registry.forKey(named);
    if (command) {
      runCommand(command.id);
      return;
    }
    if (named === "return") void send();
  }, [client, onQuit, registry, runCommand, scrollBy, send]));

  // -- the screen --------------------------------------------------------- //

  const mode = (state.session?.mode ?? "act") as Mode;
  const narrow = width < NARROW;

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%",
                  backgroundColor: theme["surface.base"] }}>
      <Header state={state} narrow={narrow} />
      <Conversation state={state} scroller={scroller} follow={follow}
                    onScrolled={() => setFollow(
                      (was) => followMoved(was, atTail()))} />
      {followMarker(follow) ? <NewOutput onPick={toTail} /> : null}
      {question
        ? <QuestionCard question={question} onChange={setQuestion} />
        : <Composer value={draft} onChange={setDraft}
                    busy={Boolean(state.session?.busy)} />}
      <ModeBar mode={mode} narrow={narrow}
               onPick={(picked) => runCommand(`mode.${picked}`)} />
      <Footer registry={registry} narrow={narrow} state={state} />
      {palette
        ? <Palette state={palette}
                   onQuery={(text) =>
                     setPalette(searchPalette(registry, screen, text))}
                   onPick={(id) => {
                     setPalette(undefined);
                     runCommand(id);
                   }} />
        : null}
    </box>
  );
}

// --------------------------------------------------------------------------- //
// pieces
// --------------------------------------------------------------------------- //

function Header({ state, narrow }: { state: State; narrow: boolean }):
    React.ReactNode {
  const where = state.session?.workspace ?? "";
  const shown = narrow ? where.split(/[/\\]/).pop() ?? "" : where;
  return (
    <box style={{ flexDirection: "row", height: 1, flexShrink: 0,
                  paddingLeft: 1, paddingRight: 1,
                  backgroundColor: theme["surface.raised"] }}>
      <text style={{ fg: theme["text.primary"] }}>Comodor</text>
      <text style={{ fg: theme["text.muted"] }}>{shown ? `  ${shown}` : ""}</text>
    </box>
  );
}

function Conversation({ state, scroller, follow, onScrolled }: {
  state: State;
  scroller: React.RefObject<ScrollBoxRenderable | null>;
  follow: Follow;
  onScrolled: () => void;
}): React.ReactNode {
  if (state.connection.kind !== "ready") {
    return (
      <box style={{ flexGrow: 1, padding: 1 }}>
        <text style={{ fg: state.connection.kind === "lost"
          ? theme["semantic.danger"] : theme["text.secondary"] }}>
          {/*
            Three states, three sentences. "Starting the core…" while actually
            catching up with a session the core already has would be a lie
            about which of the two ends lost its place.
          */}
          {state.connection.kind === "lost"
            ? `The core is not answering — ${state.connection.reason}`
            : state.connection.kind === "resynchronising"
              ? "Catching up with the session…"
              : "Starting the core…"}
        </text>
      </box>
    );
  }

  return (
    // `stickyScroll` is what keeps the tail in view, and turning it off is
    // what keeps it out of view once somebody has scrolled up. The box does
    // the scrolling; this decides whether it should be.
    <scrollbox
      ref={scroller}
      stickyScroll={follow.following}
      stickyStart="bottom"
      // Wheel events arrive here, not through a per-renderable scroll prop:
      // the scroll box scrolls itself in the same event, after this listener
      // returns — so where the wheel landed is read on the next turn.
      onMouse={(event) => {
        if (event.type !== "scroll") return;
        queueMicrotask(() => onScrolled());
      }}
      style={{ flexGrow: 1, flexShrink: 1, padding: 1 }}
    >
      {timeline(state).map((entry) => entry.kind === "line"
        ? <Said key={`line:${entry.line.id}`} line={entry.line} />
        : <Ran key={`tool:${entry.tool.id}`} tool={entry.tool} />)}
      {state.notice
        ? <text style={{ fg: level(state.notice.level) }}>
            {state.notice.text}
          </text>
        : null}
    </scrollbox>
  );
}

/** One message, and what became of it. */
function Said({ line }: { line: Line }): React.ReactNode {
  const who = line.speaker === "you" ? "You" : "Comodor";
  return (
    <box style={{ flexDirection: "column", marginBottom: 1 }}>
      <box style={{ flexDirection: "row", flexShrink: 0 }}>
        <text style={{ fg: line.speaker === "you"
          ? theme["text.secondary"] : theme["border.focused"] }}>{who}</text>
        {/*
          The state is spelled out, never carried by colour alone, and only
          when it is not the ordinary one: labelling every finished answer
          "completed" would be noise on every line of the transcript.
        */}
        {said(line)
          ? <text style={{ fg: saidColour(line) }}>{`  ${said(line)}`}</text>
          : null}
      </box>
      <text style={{ fg: theme["text.primary"] }}>{line.text}</text>
    </box>
  );
}

function said(line: Line): string {
  if (line.state === "pending") return "sending…";
  if (line.state === "failed_to_send") {
    return `not sent — ctrl+r to try again${line.error ? `: ${line.error}` : ""}`;
  }
  if (line.state === "cancelled") return "stopped";
  if (line.state === "failed") return line.error ? `failed: ${line.error}` : "failed";
  return "";
}

function saidColour(line: Line): string {
  if (line.state === "failed" || line.state === "failed_to_send") {
    return theme["semantic.danger"];
  }
  if (line.state === "cancelled") return theme["semantic.warning"];
  return theme["text.muted"];
}

/**
 * One tool invocation, with what it printed.
 *
 * Compact on purpose: a heading row and the output indented under it. An
 * expandable inspector is a later phase, and building one now would mean
 * building it before anything had streamed real output through it.
 */
function Ran({ tool }: { tool: ToolRun }): React.ReactNode {
  const colour = tool.state === "failed" ? theme["semantic.danger"]
    : tool.state === "completed" ? theme["semantic.success"]
    : theme["text.muted"];
  const lines = tool.output ? tool.output.replace(/\n+$/, "").split("\n") : [];
  return (
    <box style={{ flexDirection: "column", flexShrink: 0 }}>
      <text style={{ fg: colour }}>
        {`${marker(tool.state)} ${tool.name} ${tool.summary}`.trimEnd()}
      </text>
      {tool.outputTruncated
        ? <text style={{ fg: theme["text.muted"] }}>
            {"    … earlier output is not kept"}
          </text>
        : null}
      {lines.map((line, at) => (
        // Keyed by position within this call's own output, which only ever
        // grows at the end — so a key never moves to different text.
        <text key={`${tool.id}:${at}`} style={{ fg: theme["text.muted"] }}>
          {`    ${line}`}
        </text>
      ))}
      {tool.error
        ? <text style={{ fg: theme["semantic.danger"] }}>
            {`    ${tool.error}`}
          </text>
        : null}
    </box>
  );
}

/**
 * There is more below, and the viewport is not going to jump there by itself.
 *
 * The key is named here rather than in the footer, because this is the one
 * moment it is worth knowing — and a footer that listed every binding all the
 * time would be a footer nobody reads.
 */
function NewOutput({ onPick }: { onPick: () => void }): React.ReactNode {
  return (
    <box style={{ height: 1, flexShrink: 0, paddingLeft: 1,
                  backgroundColor: theme["surface.raised"] }}>
      <text onMouseDown={onPick} style={{ fg: theme["semantic.info"] }}>
        {"↓ new output   end Jump to it"}
      </text>
    </box>
  );
}

/**
 * The prompt box. Enter is deliberately not bound here: the key handler
 * above is the one path that sends, and an input that also submitted would
 * make one press two requests — each with its own pending line, each refused
 * or accepted on its own. One press, one send, from one place.
 */
function Composer({ value, onChange, busy }: {
  value: string; onChange: (text: string) => void; busy: boolean;
}): React.ReactNode {
  return (
    <box style={{ borderStyle: "single", height: 3, flexShrink: 0,
                  paddingLeft: 1, paddingRight: 1,
                  borderColor: busy ? theme["border.default"]
                                    : theme["border.focused"] }}>
      <input value={value} focused={!busy}
             placeholder={busy ? "working…" : "ask for anything"}
             onInput={onChange} />
    </box>
  );
}

function ModeBar({ mode, narrow, onPick }: {
  mode: Mode; narrow: boolean; onPick: (mode: Mode) => void;
}): React.ReactNode {
  // A segmented control, and never colour alone: the mode is spelled out, so
  // it reads the same to somebody who cannot tell the colours apart.
  //
  // Each segment is clickable and calls the same command the keyboard and the
  // palette call — `mode.act` / `mode.plan` / `mode.ask`, which send
  // `session.set_mode` and wait for `mode.changed`. Nothing here moves the
  // label itself; four ways in, one action, one authority.
  return (
    <box style={{ flexDirection: "row", height: 1, flexShrink: 0,
                  paddingLeft: 1 }}>
      {(["act", "plan", "ask"] as const).map((each) => (
        <text key={each}
              onMouseDown={() => onPick(each)}
              style={{ fg: each === mode ? theme[MODES[each].token]
                                         : theme["text.muted"] }}>
          {each === mode ? ` [${MODES[each].label}] ` : `  ${MODES[each].label}  `}
        </text>
      ))}
      {narrow ? null
        : <text style={{ fg: theme["text.muted"] }}>{`  ${MODES[mode].summary}`}</text>}
    </box>
  );
}

function Footer({ registry, narrow, state }: {
  registry: ReturnType<typeof build>; narrow: boolean; state: State;
}): React.ReactNode {
  // Printed from the bindings, so a hint cannot outlive the key it names.
  const hints = registry.hints()
    .map((binding) => `${binding.key} ${binding.hint}`);
  const busy = state.session?.busy ? "ctrl+c Stop" : "";
  const shown = [...(busy ? [busy] : []), ...hints];
  return (
    <box style={{ height: 1, flexShrink: 0, paddingLeft: 1,
                  backgroundColor: theme["surface.raised"] }}>
      <text style={{ fg: theme["text.muted"] }}>
        {(narrow ? shown.slice(0, 2) : shown).join("   ")}
      </text>
    </box>
  );
}

function QuestionCard({ question, onChange }: {
  question: FormState;
  onChange: (next: FormState) => void;
}): React.ReactNode {
  const asked = currentQuestion(question);
  const total = question.form.questions.length;
  if (!asked) return null;

  const typed = question.written[question.at] ?? "";
  if (process.env["COMODOR_TRACE_KEYS"]) {
    console.error(`CARD typed=[${typed}] writing=${question.writing}`);
  }

  return (
    <box style={{ borderStyle: "single", flexDirection: "column",
                  flexShrink: 0, padding: 1,
                  borderColor: theme["border.active"],
                  backgroundColor: theme["surface.overlay"] }}>
      {total > 1
        ? <text style={{ fg: theme["text.muted"] }}>
            {`${question.at + 1} of ${total}`}
          </text>
        : null}
      <text style={{ fg: theme["text.primary"] }}>{asked.prompt}</text>
      {asked.options.map((option, index) => {
        const here = index === question.cursor;
        const chosen = isSelected(question, option.id);
        const mark = asked.multiple
          ? (chosen ? "[x]" : "[ ]")
          : (chosen ? "(*)" : "( )");
        // Only the row under the cursor takes a background: passing
        // `undefined` and passing nothing are different things under
        // `exactOptionalPropertyTypes`, and the renderer wants the latter.
        const style = here
          ? { fg: theme["text.primary"], bg: theme["surface.selected"] }
          : { fg: theme["text.secondary"] };
        return (
          <text key={option.id} style={{ ...style, flexShrink: 0 }}
                onMouseDown={() => {
                  const picked = { ...question, cursor: index };
                  onChange(option.free
                    ? startWriting(toggle(picked)) : toggle(picked));
                }}>
            {`${mark} ${option.label}`}
          </text>
        );
      })}
      {/*
        The write-your-own row is an option like any other until it is chosen,
        and then it needs somewhere to type. Rendered only when the form
        offers one, so a question without it has no dead field under it.
      */}
      {allowsWriting(question)
        ? <box style={{ borderStyle: "single", height: 3, flexShrink: 0,
                        flexDirection: "row", paddingLeft: 1,
                        borderColor: question.writing
                          ? theme["border.focused"] : theme["border.default"] }}>
            {/*
              The cursor is its own element, and that is not cosmetic.

              A `<text>` sizes itself to the content it first holds. Rendering
              the field as `${typed}▌` meant its first content, the moment
              writing began, was a single character — so it measured one
              column wide and clipped every character typed afterwards. The
              state was right, the component re-rendered with the right
              string, and the screen showed a cursor and nothing else.

              Neither `width`, nor `flexGrow`, nor remounting it fixed that.
              Keeping the typed text and the cursor apart does, because the
              field's content is never one character.

              Found by running the renderer. No reducer test could see it.
            */}
            <text style={{ flexShrink: 0,
                           fg: typed ? theme["text.primary"]
                                     : theme["text.muted"] }}>
              {typed || "or write your own"}
            </text>
            {question.writing
              ? <text style={{ flexShrink: 0,
                               fg: theme["border.focused"] }}>{"▌"}</text>
              : null}
          </box>
        : null}
      <text style={{ fg: theme["text.muted"] }}>
        {hint(total > 1, allowsWriting(question), question.writing)}
      </text>
    </box>
  );
}

/** What the card says the keys do, matching what they actually do. */
function hint(many: boolean, custom: boolean, writing: boolean): string {
  if (writing) return "type your answer   enter Send   esc Back to the options";
  const parts = ["↑↓ Move"];
  if (many) parts.push("←→ Question");
  parts.push("space Choose");
  if (custom) parts.push("space on the last row to write");
  parts.push("enter Send", "esc Cancel");
  return parts.join("   ");
}

function Palette({ state, onQuery, onPick }: {
  state: PaletteState<Screen>;
  onQuery: (text: string) => void;
  onPick: (id: string) => void;
}): React.ReactNode {
  const rows = 8;
  const { from, to } = paletteWindow(state, rows);
  const shown = state.results.slice(from, to);

  return (
    <box style={{ borderStyle: "single", flexDirection: "column",
                  flexShrink: 0, padding: 1,
                  borderColor: theme["border.focused"],
                  backgroundColor: theme["surface.overlay"] }}>
      <input value={state.query} focused placeholder="type a command"
             onInput={onQuery} />
      {shown.map((command, offset) => {
        const here = from + offset === state.index;
        // The selection is drawn, not implied: a palette that highlights
        // nothing is one where Enter is a guess. The marker carries it as
        // well as the colour, so it reads without colour too.
        const style = here
          ? { fg: theme["text.primary"], bg: theme["surface.selected"] }
          : { fg: theme["text.secondary"] };
        return (
          <text key={command.id} style={{ ...style, flexShrink: 0 }}
                onMouseDown={() => onPick(command.id)}>
            {`${here ? "›" : " "} ${command.title}`}
          </text>
        );
      })}
      {state.results.length === 0
        ? <text style={{ fg: theme["text.muted"] }}>Nothing matches.</text>
        : null}
      <text style={{ fg: theme["text.muted"] }}>
        {`↑↓ Move   enter Run   esc Close`
         + (state.results.length > rows
            ? `   ${state.index + 1}/${state.results.length}` : "")}
      </text>
    </box>
  );
}

// --------------------------------------------------------------------------- //

function marker(state: ToolState): string {
  return state === "completed" ? "✓" : state === "failed" ? "×" : "●";
}

function level(name: string): string {
  if (name === "error") return theme["semantic.danger"];
  if (name === "warning") return theme["semantic.warning"];
  return theme["semantic.info"];
}

/** What has been typed into the current question's free row. */
function written(state: FormState): string {
  return state.written[state.at] ?? "";
}

/**
 * Whether a key event is a character somebody meant to type.
 *
 * One-character names only, and no modifiers: `ctrl+a` is a command, `a` is
 * an `a`. Named keys — `up`, `f2`, `escape` — are longer than one character
 * and are excluded by the same check.
 */
function isPrintable(key: KeyEvent): boolean {
  return !key.ctrl && !key.meta
    && typeof key.name === "string" && [...key.name].length === 1;
}

/** A key event as the command registry names it. */
function describeKey(key: KeyEvent): string {
  const parts: string[] = [];
  if (key.ctrl) parts.push("ctrl");
  if (key.shift && key.name !== "tab") parts.push("shift");
  if (key.meta) parts.push("meta");
  // Shift+Tab arrives as its own name on most terminals and as tab+shift on
  // others; both have to reach the same command or the reverse cycle works
  // on one machine and not another.
  const name = key.name === "tab" && key.shift ? "shift+tab" : key.name;
  parts.push(name);
  return parts.join("+");
}
