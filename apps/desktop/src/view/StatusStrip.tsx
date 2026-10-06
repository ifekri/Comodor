/**
 * The strip along the top: where the Core works, what answers, and whether
 * it is ready — each as the native side and the Core reported it.
 */

import type { CoreStatus } from "../bridge.ts";
import { InertText } from "./InertText.tsx";

export interface ModelInfo {
  readonly provider: string;
  readonly model: string;
  readonly configured: boolean;
}

const STATE_LABELS: Readonly<Record<string, string>> = {
  absent: "No workspace",
  starting: "Starting…",
  handshaking: "Starting…",
  restarting: "Restarting…",
  ready: "Ready",
  checking: "Checking the Core…",
  failed: "Stopped",
  stopping: "Closing…",
  stopped: "Stopped",
};

export function stateLabel(state: string): string {
  return STATE_LABELS[state] ?? state;
}

/** Where a running or starting Core can be moved to another workspace
 * (FR-021); a failed or absent one has its own chooser, a stopping one is
 * already on its way out. */
const CHANGEABLE = new Set(["starting", "handshaking", "restarting", "ready", "checking"]);

export function StatusStrip({ status, model, workspace, onChangeWorkspace }: {
  status: CoreStatus;
  model: ModelInfo | null;
  /** Where the Core works, as it reports it; until then, the folder the
   * native side started it in. */
  workspace?: string | null | undefined;
  onChangeWorkspace?: (() => void) | undefined;
}) {
  return (
    <header className="status-strip" data-testid="status-strip" data-state={status.state}>
      <span className={`status-state state-${status.state}`}>{stateLabel(status.state)}</span>
      {(workspace ?? status.workspace) !== null && (
        <span className="status-workspace" title={workspace ?? status.workspace ?? ""}>
          <InertText text={workspace ?? status.workspace} linked={false} />
        </span>
      )}
      {onChangeWorkspace !== undefined && CHANGEABLE.has(status.state) && (
        <button type="button" className="status-change" onClick={onChangeWorkspace}>Change workspace…</button>
      )}
      {status.state === "restarting" && status.notice !== null && (
        <span className="status-notice"><InertText text={status.notice} linked={false} /></span>
      )}
      {model !== null && (
        <>
          <span className="status-provider"><InertText text={model.provider || "no provider"} /></span>
          <span className="status-model"><InertText text={model.model || "no model"} /></span>
          <span className={model.configured ? "status-configured" : "status-unconfigured"}>
            {model.configured ? "Configured" : "Not configured"}
          </span>
        </>
      )}
    </header>
  );
}
