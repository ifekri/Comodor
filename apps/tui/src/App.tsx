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
import type { KeyEvent } from "@opentui/core";

import { CoreClient } from "@comodor/client";
import { terminal as theme } from "@comodor/design-tokens";
import { MODES, type Mode } from "@comodor/modes";
import type { EventName, Session } from "@comodor/protocol";
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
import { initial, reduce, type State } from "./session.ts";

export interface AppProps {
  readonly client: CoreClient;
  readonly onQuit: () => void;
}

/** Below this the sidebar-free single column is the only thing that fits. */
const NARROW = 80;

export function App({ client, onQuit }: AppProps): React.ReactNode {
  const [state, dispatch] = useReducer(reduce, initial);
  const [draft, setDraft] = useState("");
  const [palette, setPalette] = useState<PaletteState<Screen> | undefined>();
  const [question, setQuestion] = useState<FormState | undefined>();
  const { width } = useTerminalDimensions();

  const registry = useMemo(() => build(), []);
  const latest = useRef(state);
  latest.current = state;

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

  useEffect(() => {
    let alive = true;
    const stop = client.on((name: EventName, params) => {
      if (!alive) return;
      dispatch({ type: "event", name, params });
      if (name === "question.requested") {
        setQuestion(begin(params as never));
      } else if (name === "question.resolved") {
        setQuestion(undefined);
      }
    });

    void (async () => {
      try {
        const made = await client.call("session.create");
        if (alive) {
          dispatch({ type: "connected",
                     session: made["session"] as Session });
        }
      } catch (problem) {
        if (alive) {
          dispatch({ type: "lost", reason: (problem as Error).message });
        }
      }
    })();

    return () => { alive = false; stop(); };
  }, [client]);

  // -- what a command is given ------------------------------------------- //

  const screen: Screen = useMemo(() => ({
    call: (method, params) => client.call(method as never, params ?? {}),
    sessionId: () => latest.current.session?.id,
    mode: () => (latest.current.session?.mode ?? "act") as Mode,
    busy: () => Boolean(latest.current.session?.busy),
    openPalette: () => setPalette(openPalette(registry, screenRef.current)),
    closePalette: () => setPalette(undefined),
    paletteOpen: () => Boolean(palette),
    quit: onQuit,
    note: () => {},
  }), [client, onQuit, palette, registry]);

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
      dispatch({ type: "event", name: "notification.created",
                 params: { level: "warning",
                           text: (problem as Error).message } });
    });
  }, [registry]);

  const send = useCallback(async () => {
    const text = draft.trim();
    const id = latest.current.session?.id;
    if (!text || !id) return;
    setDraft("");
    dispatch({ type: "said", text });
    try {
      await client.call("session.send", { session_id: id, text });
    } catch (problem) {
      dispatch({ type: "event", name: "notification.created",
                 params: { level: "error", text: (problem as Error).message } });
    }
  }, [client, draft]);

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

    const command = registry.forKey(named);
    if (command) {
      runCommand(command.id);
      return;
    }
    if (named === "return") void send();
  }, [client, onQuit, registry, runCommand, send]));

  // -- the screen --------------------------------------------------------- //

  const mode = (state.session?.mode ?? "act") as Mode;
  const narrow = width < NARROW;

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%",
                  backgroundColor: theme["surface.base"] }}>
      <Header state={state} narrow={narrow} />
      <Conversation state={state} />
      {question
        ? <QuestionCard question={question} onChange={setQuestion} />
        : <Composer value={draft} onChange={setDraft} onSubmit={send}
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

function Conversation({ state }: { state: State }): React.ReactNode {
  if (state.connection.kind !== "ready") {
    return (
      <box style={{ flexGrow: 1, padding: 1 }}>
        <text style={{ fg: state.connection.kind === "lost"
          ? theme["semantic.danger"] : theme["text.secondary"] }}>
          {state.connection.kind === "lost"
            ? `The core is not answering — ${state.connection.reason}`
            : "Starting the core…"}
        </text>
      </box>
    );
  }

  return (
    <scrollbox style={{ flexGrow: 1, flexShrink: 1, padding: 1 }}>
      {state.lines.map((line) => (
        <box key={line.id} style={{ flexDirection: "column", marginBottom: 1 }}>
          <text style={{ fg: line.speaker === "you"
            ? theme["text.secondary"] : theme["border.focused"] }}>
            {line.speaker === "you" ? "You" : "Comodor"}
          </text>
          <text style={{ fg: theme["text.primary"] }}>{line.text}</text>
        </box>
      ))}
      {state.tools.map((tool) => (
        <text key={tool.id} style={{ fg: tool.state === "failed"
          ? theme["semantic.danger"]
          : tool.state === "done" ? theme["semantic.success"]
          : theme["text.muted"] }}>
          {`${marker(tool.state)} ${tool.name} ${tool.summary}`.trimEnd()}
        </text>
      ))}
      {state.notice
        ? <text style={{ fg: level(state.notice.level) }}>
            {state.notice.text}
          </text>
        : null}
    </scrollbox>
  );
}

function Composer({ value, onChange, onSubmit, busy }: {
  value: string; onChange: (text: string) => void;
  onSubmit: () => void; busy: boolean;
}): React.ReactNode {
  return (
    <box style={{ borderStyle: "single", height: 3, flexShrink: 0,
                  paddingLeft: 1, paddingRight: 1,
                  borderColor: busy ? theme["border.default"]
                                    : theme["border.focused"] }}>
      <input value={value} focused={!busy}
             placeholder={busy ? "working…" : "ask for anything"}
             onInput={onChange} onSubmit={onSubmit} />
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

function marker(state: "running" | "done" | "failed"): string {
  return state === "done" ? "✓" : state === "failed" ? "×" : "●";
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
