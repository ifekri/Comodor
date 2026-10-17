/**
 * The Core panel (US5; FR-008, FR-010): the Core's values exactly as they
 * were reported for the current Core, "not reported yet" for the rest, and
 * the actions that apply now — the same commands as their status-bar,
 * failure-view and palette forms.
 */

import type { CommandRegistry } from "@comodor/commands";

import type { WindowContext } from "../commands.ts";
import { InertText } from "../view/InertText.tsx";
import { stateLabel } from "../view/StatusStrip.tsx";
import { WORKBENCH_COMMAND_IDS } from "./commands.ts";
import type { CoreReport } from "./reports.ts";

const NOT_REPORTED = "not reported yet";
/** Longer values are cut on screen and given whole on focus and hover. Each value
 * shows in its own direction (`dir="auto"`); the layout itself never mirrors. */
const LONG = 40;

const ACTIONS = [WORKBENCH_COMMAND_IDS.workspaceChange, WORKBENCH_COMMAND_IDS.checkAgain, WORKBENCH_COMMAND_IDS.retry];

function Value({ text, reported = true }: { text: string | null; reported?: boolean }) {
  if (text === null || !reported) return <span className="core-missing">{NOT_REPORTED}</span>;
  if (text.length <= LONG) return <InertText text={text} linked={false} />;
  return (
    <span className="core-value" title={text} tabIndex={0}>
      <InertText text={text} linked={false} />
    </span>
  );
}

export function CorePanel({ report, registry, context, onRun }: {
  report: CoreReport;
  registry: CommandRegistry<WindowContext>;
  context: WindowContext;
  onRun: (id: string) => void;
}) {
  const actions = ACTIONS.flatMap((id) => {
    const command = registry.get(id);
    return command && (!command.enabled || command.enabled(context)) ? [command] : [];
  });
  return (
    <div className="core-panel" data-testid="core-panel">
      <h3 className="panel-section">VALUES</h3>
      <dl className="core-values">
        <dt>State</dt><dd dir="auto">{stateLabel(report.state)}</dd>
        <dt>Workspace</dt><dd dir="auto"><Value text={report.workspace} /></dd>
        <dt>Core</dt><dd dir="auto"><Value text={report.core} /></dd>
        <dt>Protocol version</dt><dd dir="auto"><Value text={report.protocolVersion === null ? null : String(report.protocolVersion)} /></dd>
        <dt>Provider</dt><dd dir="auto"><Value text={report.provider} /></dd>
        <dt>Model</dt><dd dir="auto"><Value text={report.model} /></dd>
        <dt>Configured</dt><dd dir="auto"><Value text={report.configured === null ? null : report.configured ? "Yes" : "No"} /></dd>
        <dt>Restarts</dt><dd dir="auto">{report.restarts.count} of {report.restarts.limit}</dd>
        {report.failure !== null && (
          <>
            <dt>Failure</dt>
            <dd dir="auto"><Value text={`${report.failure.class}: ${report.failure.message}`} /></dd>
          </>
        )}
      </dl>
      {actions.length > 0 && <h3 className="panel-section">ACTIONS</h3>}
      {actions.length > 0 && (
        <div className="actions">
          {actions.map((command) => (
            <button key={command.id} type="button" onClick={() => onRun(command.id)}>{command.title}</button>
          ))}
        </div>
      )}
    </div>
  );
}
