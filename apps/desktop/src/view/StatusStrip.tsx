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
  failed: "Stopped",
  stopping: "Closing…",
  stopped: "Stopped",
};

export function stateLabel(state: string): string {
  return STATE_LABELS[state] ?? state;
}

export function StatusStrip({ status, model }: {
  status: CoreStatus;
  model: ModelInfo | null;
}) {
  return (
    <header className="status-strip" data-testid="status-strip" data-state={status.state}>
      <span className={`status-state state-${status.state}`}>{stateLabel(status.state)}</span>
      {status.workspace !== null && (
        <span className="status-workspace" title={status.workspace}><InertText text={status.workspace} /></span>
      )}
      {status.state === "restarting" && status.notice !== null && (
        <span className="status-notice"><InertText text={status.notice} /></span>
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
