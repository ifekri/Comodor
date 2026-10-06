/**
 * The mode, as the Core last confirmed it, and a way to ask for another.
 * The label is drawn from the confirmed mode only, so it changes when the
 * Core says the mode changed; what a mode permits is the Core's to enforce,
 * never this control's.
 */

import { CYCLE, type Mode, MODES } from "@comodor/modes";
import type { ModeIntent } from "@comodor/session";

export function ModeControl({ intent, held, onChoose }: {
  intent: ModeIntent;
  /** While the session is being checked or read again: nothing is sent. */
  held: boolean;
  onChoose: (mode: Mode) => void;
}) {
  const current = MODES[intent.confirmed];
  return (
    <nav className="mode-control" data-testid="mode" aria-label="Mode">
      <span className={`mode-current mode-${current.id}`} data-current title={current.summary}>
        {current.label}
      </span>
      {CYCLE.map((mode) => (
        <button key={mode} type="button" title={MODES[mode].summary} disabled={held}
                aria-pressed={mode === intent.confirmed}
                className={mode === intent.desired && mode !== intent.confirmed
                  ? "mode-option asked" : "mode-option"}
                onClick={() => onChoose(mode)}>
          {MODES[mode].label}
        </button>
      ))}
      {intent.refused !== undefined && <span className="mode-refused">{intent.refused}</span>}
    </nav>
  );
}
