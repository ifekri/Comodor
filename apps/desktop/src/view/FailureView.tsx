/**
 * Why the Core is not running, one named view per failure class (SC-002).
 * The native side's message says what happened; the Core's last output is
 * shown as plain text, never interpreted.
 */

import type { CoreFailure } from "../bridge.ts";
import { InertText } from "./InertText.tsx";

const TITLES: Readonly<Record<string, string>> = {
  not_found: "Comodor was not found",
  spawn_failed: "Comodor could not be started",
  workspace_unavailable: "The workspace is not available",
  exited_before_ready: "The Core stopped while starting",
  protocol_mismatch: "This Core speaks a different protocol version",
  protocol_fault: "The Core sent something that is not protocol",
  crashed: "The Core stopped unexpectedly",
};

export function failureTitle(failureClass: string): string {
  return TITLES[failureClass] ?? "The Core is not running";
}

export function FailureView({ failure, restarts, diagnostics, onRetry, onChoose }: {
  failure: CoreFailure;
  /** The crash count and its limit (OD-1), when the Core had been ready. */
  restarts?: { count: number; limit: number };
  diagnostics: string;
  onRetry: () => void;
  onChoose: () => void;
}) {
  return (
    <section className="failure-view" data-testid="failure-view" data-class={failure.class}>
      <h1>{failureTitle(failure.class)}</h1>
      <p className="failure-message"><InertText text={failure.message} /></p>
      {(failure.class === "crashed" || failure.class === "protocol_fault")
        && restarts !== undefined && restarts.count >= restarts.limit && (
        <p className="failure-count">
          Stopped {restarts.count} of {restarts.limit} times in a row: it is not started again
          until you choose to.
        </p>
      )}
      {diagnostics !== "" && (
        <>
          <h2>The Core's last output</h2>
          <pre className="diagnostics"><InertText text={diagnostics} /></pre>
        </>
      )}
      <div className="actions">
        <button type="button" onClick={onRetry}>Try again</button>
        {failure.class === "workspace_unavailable" && (
          <button type="button" onClick={onChoose}>Choose workspace…</button>
        )}
      </div>
    </section>
  );
}
