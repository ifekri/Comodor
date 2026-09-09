/**
 * The workbench surfaces: what delegated work exists, and what the agent
 * thinks remains to be done.
 *
 * Presentation only. Which delegates exist, which states they may be in,
 * whether one may be stopped, and what the task list says are all decisions
 * the shared projection (`@comodor/session`) has already made from the core's
 * own words — this file draws them and routes clicks and cursor moves back to
 * the App, which talks to the core. Nothing here keeps a second copy of any
 * state, and nothing here invents one: a delegate is `stopping` because the
 * core announced it, never because a key was pressed.
 *
 * Two rules the drawing follows:
 *
 * **No state is carried by colour alone.** Every delegate and task state has
 * its own mark *and* its word, so the panel reads the same in a monochrome
 * terminal and to somebody who cannot tell the hues apart.
 *
 * **Everything is bounded.** A long autonomous job leaves dozens of terminal
 * delegates and a fifty-item plan behind; the panel caps what it draws and
 * says how much it is not showing, rather than growing until it pushes the
 * conversation off the screen.
 */

import { useEffect, useState } from "react";

import { terminal as theme } from "@comodor/design-tokens";
import {
  runningDelegates,
  stoppable,
  tasksDone,
  type Delegate,
  type DelegateState,
  type State,
  type Task,
  type TaskState,
} from "@comodor/session";

/**
 * At this width there is room for a persistent panel beside the conversation.
 *
 * Measured against the same evidence the Rich interface uses: it draws its
 * sidebar from 100 columns and hides it below, because under that the two
 * columns stop being worth what they cost the conversation.
 */
export const WIDE = 100;

/** How many delegate rows the panel draws before it starts counting instead. */
const AGENT_ROWS = 4;

/** How many task rows the panel draws before it starts counting instead. */
const TASK_ROWS = 6;

/**
 * Which delegates the bounded panel draws, as indexes into `delegates`.
 *
 * A fixed head slice shows the *oldest* rows — and terminal records never
 * leave, so after a long job every newly launched delegate would hide behind
 * "+N more" while the keyboard cursor still ranges over the full array:
 * Enter could stop work nobody can see. The window therefore keeps what is
 * current visible: live rows first, then the row the cursor is on, then the
 * most recent activity. The drawn order stays the core's own — the window is
 * a selection of rows, never a reordering of the truth.
 */
export function visibleWindow(delegates: readonly Delegate[],
                              selected: number,
                              rows: number): number[] {
  if (delegates.length <= rows) {
    return delegates.map((_, at) => at);
  }
  const picked = new Set<number>();
  delegates.forEach((delegate, at) => {
    if (picked.size < rows
        && (delegate.state === "running" || delegate.state === "stopping")) {
      picked.add(at);
    }
  });
  if (picked.size < rows && selected >= 0 && selected < delegates.length) {
    picked.add(selected);
  }
  for (let at = delegates.length - 1; at >= 0 && picked.size < rows; at--) {
    picked.add(at);
  }
  return [...picked].sort((left, right) => left - right);
}

/** The panel's width, by the terminal's: wider screens afford a wider panel. */
export function panelWidth(width: number): number {
  return width >= 140 ? 30 : 24;
}

const DELEGATE_MARKS: Record<DelegateState, string> = {
  running: "●",
  stopping: "◐",
  done: "✓",
  failed: "×",
  stopped: "■",
  lost: "?",
};

const DELEGATE_COLOURS: Record<DelegateState, string> = {
  running: theme["text.primary"],
  stopping: theme["semantic.warning"],
  done: theme["semantic.success"],
  failed: theme["semantic.danger"],
  stopped: theme["text.secondary"],
  lost: theme["semantic.warning"],
};

/** The same four marks the Rich sidebar uses, so the two interfaces agree. */
const TASK_MARKS: Record<TaskState, string> = {
  pending: "○",
  active: "◐",
  done: "●",
  blocked: "✗",
};

/**
 * A clock that only runs while something is in flight.
 *
 * A running delegate's elapsed time is the core's `started_at` against now,
 * which needs a tick to redraw — but a session with no live delegates must
 * not repaint once a second for nothing, so the interval exists only while
 * one is running or stopping.
 */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

/** Seconds as a person reads them: `3.2s`, `42.0s`, `5m02s`. */
export function elapsedText(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds * 10) / 10);
  if (whole < 60) return `${whole.toFixed(1)}s`;
  const minutes = Math.floor(whole / 60);
  const rest = Math.round(whole % 60);
  return `${minutes}m${String(rest).padStart(2, "0")}s`;
}

/**
 * Where a delegate's clock stands.
 *
 * A terminal record's `elapsed` is the final count and stays authoritative;
 * a live one is measured from the core's `started_at` against the local clock
 * — the same machine for a spawned core, and a client that guessed from the
 * last event instead would freeze at zero.
 */
function elapsedOf(delegate: Delegate, now: number): string {
  if (delegate.state === "running" || delegate.state === "stopping") {
    if (delegate.startedAt > 0) {
      return elapsedText((now - delegate.startedAt * 1000) / 1000);
    }
  }
  return elapsedText(delegate.elapsed);
}

/** Keep one drawn line inside the columns it has, clipping rather than wrapping. */
function fit(text: string, columns: number): string {
  if (columns <= 1) return "";
  if (text.length <= columns) return text;
  return `${text.slice(0, columns - 1)}…`;
}

/** One drawn line with a right-aligned tail, the way the tool rows read. */
function spread(left: string, right: string, columns: number): string {
  if (!right) return fit(left, columns);
  const room = columns - right.length - 1;
  if (room <= 0) return fit(right, columns);
  return `${fit(left, room)}${" ".repeat(Math.max(1, columns - fit(left, room).length - right.length))}${right}`;
}

export function WorkbenchPanel({ state, width, focused, selected, hasTasks,
                                 hasDelegates, onSelect, onStop }: {
  state: State;
  /** Columns the panel owns, border included. */
  width: number;
  focused: boolean;
  /** Which delegate row the cursor is on, when focused. */
  selected: number;
  hasTasks: boolean;
  hasDelegates: boolean;
  onSelect: (at: number) => void;
  onStop: (id: string) => void;
}): React.ReactNode {
  const live = runningDelegates(state);
  const now = useNow(live.length > 0);
  const inner = Math.max(8, width - 4);
  const chosen = state.delegates[selected];

  return (
    <box style={{ borderStyle: "single", flexDirection: "column",
                  width, flexShrink: 0, paddingLeft: 1, paddingRight: 1,
                  borderColor: focused ? theme["border.focused"]
                                       : theme["border.default"],
                  backgroundColor: theme["surface.raised"] }}>
      {hasDelegates
        ? <AgentsSection delegates={state.delegates} inner={inner} now={now}
                         focused={focused} selected={selected}
                         onSelect={onSelect} />
        : null}
      {hasTasks && state.tasks.length > 0
        ? <TasksSection tasks={state.tasks} inner={inner} />
        : null}
      {focused
        ? (chosen && stoppable(chosen)
          // The stop is spelled out as the thing Enter does, and is also
          // clickable here — on the control, never on the row: selecting a
          // delegate must not be able to stop it.
          ? <text onMouseDown={() => onStop(chosen.id)}
                  style={{ fg: theme["semantic.warning"], flexShrink: 0 }}>
              {fit(`enter Stop ${chosen.id}`, inner)}
            </text>
          : <text style={{ fg: theme["text.muted"], flexShrink: 0 }}>
              {fit("↑↓ select   esc back", inner)}
            </text>)
        : null}
    </box>
  );
}

function AgentsSection({ delegates, inner, now, focused, selected,
                         onSelect }: {
  delegates: readonly Delegate[];
  inner: number;
  now: number;
  focused: boolean;
  selected: number;
  onSelect: (at: number) => void;
}): React.ReactNode {
  const live = delegates.filter((delegate) =>
    delegate.state === "running" || delegate.state === "stopping").length;
  // The cursor claims a row only while it is live: an unfocused panel shows
  // the newest work rather than wherever a stale selection once rested.
  const window = visibleWindow(delegates, focused ? selected : -1, AGENT_ROWS);
  return (
    <box style={{ flexDirection: "column", flexShrink: 0 }}>
      <text style={{ fg: theme["text.secondary"] }}>
        {spread("Agents", live > 0 ? `${live} live` : "", inner)}
      </text>
      {delegates.length === 0
        ? <text style={{ fg: theme["text.muted"] }}>
            {fit("No background work.", inner)}
          </text>
        : null}
      {window.map((at) => {
        const delegate = delegates[at];
        // The window only ever carries real indexes; the guard is for the
        // type system, not for a case that can happen.
        if (!delegate) return null;
        return (
          <AgentRow key={delegate.id} delegate={delegate} inner={inner}
                    now={now} here={focused && at === selected}
                    onSelect={() => onSelect(at)} />
        );
      })}
      {delegates.length > window.length
        ? <text style={{ fg: theme["text.muted"] }}>
            {fit(`+${delegates.length - window.length} more`, inner)}
          </text>
        : null}
    </box>
  );
}

/**
 * One delegate, two rows: what it is doing, and what it is.
 *
 * The state is a word next to a mark, the clock is on the right, and the
 * second row is the label — or, when the delegate failed or was lost, the
 * reason, because that is the half somebody actually came here to read.
 * Clicking selects; nothing about clicking stops.
 */
function AgentRow({ delegate, inner, now, here, onSelect }: {
  delegate: Delegate;
  inner: number;
  now: number;
  here: boolean;
  onSelect: () => void;
}): React.ReactNode {
  const colour = DELEGATE_COLOURS[delegate.state];
  const head = spread(
    `${here ? "›" : " "} ${DELEGATE_MARKS[delegate.state]} ${delegate.id} ${delegate.state}`,
    elapsedOf(delegate, now), inner);
  const broken = delegate.state === "failed" || delegate.state === "lost";
  const second = broken && delegate.error
    ? delegate.error
    : terminalNote(delegate);
  const style = here
    ? { fg: theme["text.primary"], bg: theme["surface.selected"] }
    : { fg: colour };
  return (
    <box style={{ flexDirection: "column", flexShrink: 0 }}>
      {/* The heading row is the click target, and clicking it *selects* —
          stopping is the explicit control below, never a row click. */}
      <text style={{ ...style, flexShrink: 0 }}
            onMouseDown={onSelect}>{head}</text>
      {second
        ? <text style={{ fg: broken ? theme["semantic.danger"]
                                    : theme["text.muted"], flexShrink: 0 }}>
            {fit(`  ${second}`, inner)}
          </text>
        : null}
    </box>
  );
}

/** The metrics row for a settled delegate: what it cost, truthfully. */
function terminalNote(delegate: Delegate): string {
  const parts = [delegate.label];
  if (delegate.state === "done" || delegate.state === "failed"
      || delegate.state === "stopped") {
    const metrics: string[] = [];
    if (delegate.steps > 0) metrics.push(`${delegate.steps} steps`);
    if (delegate.tokens > 0) metrics.push(`${shortCount(delegate.tokens)} tok`);
    if (metrics.length > 0) parts.push(metrics.join(" · "));
  }
  return parts.filter(Boolean).join(" · ");
}

function shortCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

function TasksSection({ tasks, inner }: {
  tasks: readonly Task[];
  inner: number;
}): React.ReactNode {
  // Active first, stable, exactly like the Rich sidebar: the item being
  // worked on is the one never dropped when the list does not fit. The rest
  // keep the model's own order — a reorder upstream is a reorder here.
  const ordered = [...tasks].sort(
    (left, right) => Number(right.state === "active")
      - Number(left.state === "active"));
  return (
    <box style={{ flexDirection: "column", flexShrink: 0 }}>
      <text style={{ fg: theme["text.secondary"] }}>
        {spread("Tasks", `${tasksDone(tasks)}/${tasks.length}`, inner)}
      </text>
      {ordered.slice(0, TASK_ROWS).map((task, at) => (
        <TaskRow key={`${at}:${task.text}`} task={task} inner={inner} />
      ))}
      {ordered.length > TASK_ROWS
        ? <text style={{ fg: theme["text.muted"] }}>
            {fit(`+${ordered.length - TASK_ROWS} more`, inner)}
          </text>
        : null}
    </box>
  );
}

function TaskRow({ task, inner }: { task: Task; inner: number }): React.ReactNode {
  const colour = task.state === "blocked" ? theme["semantic.danger"]
    : task.state === "active" ? theme["text.primary"]
    : theme["text.muted"];
  return (
    <text style={{ fg: colour, flexShrink: 0 }}>
      {fit(` ${TASK_MARKS[task.state]} ${task.text}`, inner)}
    </text>
  );
}
