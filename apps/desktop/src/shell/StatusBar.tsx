/**
 * The status bar (FR-003), in the reference's cells (spec Clarifications,
 * 2026-10-17): D1's status strip, once, with the values D1 gave it — the
 * Core's state, the workspace and model as the Core reported them, "Change
 * workspace…" — then Diagnostics (real), the later Terminal and the later
 * power control, and the one polite announcement region (FR-020).
 */

import type { CoreStatus } from "../bridge.ts";
import { StatusStrip } from "../view/StatusStrip.tsx";
import { LaterButton } from "./Later.tsx";
import type { SharedSession } from "./session-store.ts";

export function StatusBar({ status, session, announcement, notice, diagnosticsKey, onChangeWorkspace, onDiagnostics }: {
  status: CoreStatus | null;
  session: SharedSession | null;
  /** A layout that could not be saved, said quietly once. */
  notice: string | null;
  /** The last change worth telling a screen reader, said once. */
  announcement: string;
  diagnosticsKey: string | undefined;
  onChangeWorkspace: () => void;
  onDiagnostics: () => void;
}) {
  return (
    <footer className="status-bar" data-testid="status-bar">
      {/* A section, so the strip's own <header> is not a second banner. */}
      <section className="status-bar-content">
        {status !== null && (
          <StatusStrip status={status} model={session?.model ?? null} workspace={session?.workspace}
                       onChangeWorkspace={onChangeWorkspace} />
        )}
        {notice !== null && <span className="layout-notice" data-testid="layout-notice">{notice}</span>}
        <LaterButton label="Terminal" className="status-cell status-later">
          <span className="icon" data-icon="terminal" aria-hidden="true" />
          <span>Terminal</span>
        </LaterButton>
        <button type="button" className="status-cell status-diagnostics"
                title={diagnosticsKey ? `Diagnostics (${diagnosticsKey})` : "Diagnostics"} onClick={onDiagnostics}>
          <span className="icon" data-icon="bug_report" aria-hidden="true" />
          <span>Diagnostics</span>
        </button>
        <span className="status-spacer" />
        <LaterButton label="Quitting from here" icon="power_settings_new" className="status-cell status-power" />
      </section>
      <p className="announcer" role="status" aria-live="polite" aria-atomic="true">{announcement}</p>
    </footer>
  );
}
