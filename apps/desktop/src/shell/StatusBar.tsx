/**
 * The status bar (FR-003): D1's status strip, once, with the values D1 gave
 * it — the Core's state, the workspace and model as the Core reported them —
 * the palette control, and the one polite announcement region (FR-020).
 */

import type { CoreStatus } from "../bridge.ts";
import { StatusStrip } from "../view/StatusStrip.tsx";
import type { SharedSession } from "./session-store.ts";

export function StatusBar({ status, session, announcement, notice, paletteKey, onChangeWorkspace, onPalette }: {
  status: CoreStatus | null;
  session: SharedSession | null;
  /** A layout that could not be saved, said quietly once. */
  notice: string | null;
  /** The last change worth telling a screen reader, said once. */
  announcement: string;
  paletteKey: string | undefined;
  onChangeWorkspace: () => void;
  onPalette: () => void;
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
        <button type="button" className="status-palette" aria-label="Commands"
                title={paletteKey ? `Commands (${paletteKey})` : "Commands"} onClick={onPalette}>
          <span className="icon" data-icon="keyboard_command_key" aria-hidden="true" />Commands
        </button>
      </section>
      <p className="announcer" role="status" aria-live="polite" aria-atomic="true">{announcement}</p>
    </footer>
  );
}
