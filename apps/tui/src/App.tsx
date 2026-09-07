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
  answer as answerOf,
  answerable,
  begin,
  cancel as cancelOf,
  current as currentQuestion,
  isSelected,
  move,
  step,
  toggle,
  type FormState,
} from "@comodor/questions";

import { build, type Screen } from "./commands.ts";
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
  const [palette, setPalette] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [question, setQuestion] = useState<FormState | undefined>();
  const { width } = useTerminalDimensions();

  const registry = useMemo(() => build(), []);
  const latest = useRef(state);
  latest.current = state;

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
    openPalette: () => { setPaletteQuery(""); setPalette(true); },
    closePalette: () => setPalette(false),
    paletteOpen: () => palette,
    quit: onQuit,
    note: () => {},
  }), [client, onQuit, palette]);

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

    if (question) {
      if (named === "escape") {
        void client.call("question.answer", cancelOf(question) as never);
        setQuestion(undefined);
      } else if (named === "up") setQuestion(move(question, -1));
      else if (named === "down") setQuestion(move(question, 1));
      // A form has several questions; left and right walk between them.
      else if (named === "left") setQuestion(step(question, -1));
      else if (named === "right") setQuestion(step(question, 1));
      else if (named === "space") setQuestion(toggle(question));
      else if (named === "return" && answerable(question)) {
        void client.call("question.answer", answerOf(question) as never);
        setQuestion(undefined);
      }
      return;
    }

    if (palette) {
      if (named === "escape") { setPalette(false); return; }
      if (named === "return") {
        const first = registry.search(paletteQuery, screen)[0];
        setPalette(false);
        if (first) void registry.run(first.id, screen);
        return;
      }
      return;
    }

    // Ctrl+C is context-sensitive: it stops work, and only quits when there
    // is none. Killing the client mid-turn would leave a core running.
    if (named === "ctrl+c") {
      if (latest.current.session?.busy) void registry.run("session.cancel", screen);
      else onQuit();
      return;
    }

    const command = registry.forKey(named);
    if (command) {
      void registry.run(command.id, screen);
      return;
    }
    if (named === "return") void send();
  }, [client, onQuit, palette, paletteQuery, question, registry, screen, send]));

  // -- the screen --------------------------------------------------------- //

  const mode = (state.session?.mode ?? "act") as Mode;
  const narrow = width < NARROW;

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%",
                  backgroundColor: theme["surface.base"] }}>
      <Header state={state} narrow={narrow} />
      <Conversation state={state} />
      {question
        ? <QuestionCard question={question} />
        : <Composer value={draft} onChange={setDraft} onSubmit={send}
                    busy={Boolean(state.session?.busy)} />}
      <ModeBar mode={mode} narrow={narrow} />
      <Footer registry={registry} narrow={narrow} state={state} />
      {palette
        ? <Palette query={paletteQuery} onQuery={setPaletteQuery}
                   registry={registry} screen={screen} />
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
    <box style={{ paddingLeft: 1, paddingRight: 1,
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
    <scrollbox style={{ flexGrow: 1, padding: 1 }}>
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
    <box style={{ borderStyle: "single", paddingLeft: 1, paddingRight: 1,
                  borderColor: busy ? theme["border.default"]
                                    : theme["border.focused"] }}>
      <input value={value} focused={!busy}
             placeholder={busy ? "working…" : "ask for anything"}
             onInput={onChange} onSubmit={onSubmit} />
    </box>
  );
}

function ModeBar({ mode, narrow }: { mode: Mode; narrow: boolean }):
    React.ReactNode {
  // A segmented control, and never colour alone: the mode is spelled out, so
  // it reads the same to somebody who cannot tell the colours apart.
  return (
    <box style={{ flexDirection: "row", paddingLeft: 1 }}>
      {(["act", "plan", "ask"] as const).map((each) => (
        <text key={each}
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
    <box style={{ paddingLeft: 1, backgroundColor: theme["surface.raised"] }}>
      <text style={{ fg: theme["text.muted"] }}>
        {(narrow ? shown.slice(0, 2) : shown).join("   ")}
      </text>
    </box>
  );
}

function QuestionCard({ question }: { question: FormState }):
    React.ReactNode {
  const asked = currentQuestion(question);
  const total = question.form.questions.length;
  if (!asked) return null;

  return (
    <box style={{ borderStyle: "single", flexDirection: "column", padding: 1,
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
          <text key={option.id} style={style}>
            {`${mark} ${option.label}`}
          </text>
        );
      })}
      <text style={{ fg: theme["text.muted"] }}>
        {total > 1
          ? "↑↓ Move   ←→ Question   space Choose   enter Send   esc Cancel"
          : "↑↓ Move   space Choose   enter Send   esc Cancel"}
      </text>
    </box>
  );
}

function Palette({ query, onQuery, registry, screen }: {
  query: string; onQuery: (text: string) => void;
  registry: ReturnType<typeof build>; screen: Screen;
}): React.ReactNode {
  const found = registry.search(query, screen).slice(0, 8);
  return (
    <box style={{ borderStyle: "single", flexDirection: "column", padding: 1,
                  borderColor: theme["border.focused"],
                  backgroundColor: theme["surface.overlay"] }}>
      <input value={query} focused placeholder="type a command" onInput={onQuery} />
      {found.map((command, index) => (
        <text key={command.id}
              style={{ fg: index === 0 ? theme["text.primary"]
                                       : theme["text.secondary"] }}>
          {command.title}
        </text>
      ))}
      {found.length === 0
        ? <text style={{ fg: theme["text.muted"] }}>Nothing matches.</text>
        : null}
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
