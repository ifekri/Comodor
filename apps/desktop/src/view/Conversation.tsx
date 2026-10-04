/**
 * The conversation: messages and tool activity in the order they arrived,
 * each exactly as the Core sent it. Text is shown as text, never markup.
 */

import { type Entry, type Line, type State, timeline, type ToolRun } from "@comodor/session";

const LINE_STATES: Readonly<Record<string, string>> = {
  pending: "sending…",
  failed_to_send: "not sent",
  streaming: "",
  completed: "",
  cancelled: "cancelled",
  failed: "failed",
};

function LineView({ line }: { line: Line }) {
  const note = LINE_STATES[line.state] ?? line.state;
  return (
    <article className={`line speaker-${line.speaker} line-${line.state}`} data-testid="line"
             data-state={line.state} data-turn={line.turnId}>
      <span className="speaker">{line.speaker === "you" ? "You" : "Comodor"}</span>
      <div className="text">{line.text}</div>
      {note !== "" && <span className="line-note">{note}</span>}
      {line.error !== undefined && <span className="line-error">{line.error}</span>}
    </article>
  );
}

function ToolView({ tool }: { tool: ToolRun }) {
  return (
    <article className={`tool tool-${tool.state}`} data-testid="tool" data-call={tool.id}
             data-state={tool.state}>
      <header>
        <span className="tool-name">{tool.name}</span>
        {tool.summary !== "" && <span className="tool-summary">{tool.summary}</span>}
        <span className="tool-state">{tool.state}</span>
      </header>
      {tool.output !== "" && (
        <pre className="tool-output">{tool.outputTruncated ? "…" : ""}{tool.output}</pre>
      )}
      {tool.error !== undefined && <span className="tool-error">{tool.error}</span>}
    </article>
  );
}

function EntryView({ entry }: { entry: Entry }) {
  return entry.kind === "line" ? <LineView line={entry.line} /> : <ToolView tool={entry.tool} />;
}

export function Conversation({ state }: { state: State }) {
  const entries = timeline(state);
  return (
    <section className="conversation" data-testid="conversation" aria-live="polite">
      {entries.map((entry) => (
        <EntryView key={`${entry.kind}:${entry.kind === "line" ? entry.line.id : entry.tool.id}`}
                   entry={entry} />
      ))}
      {state.notice !== undefined && (
        <p className={`notice notice-${state.notice.level}`} data-testid="notice">{state.notice.text}</p>
      )}
    </section>
  );
}
