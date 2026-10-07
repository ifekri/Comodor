/**
 * While the Core stops (OD-2): "Closing…", the seconds left of its grace,
 * and "Quit now". The native side ends the wait at the deadline either way;
 * the countdown here only shows it.
 */

import { useEffect, useState } from "react";

/** What the window says after a forced stop. Nothing is claimed saved. */
export const FORCED_NOTICE =
  "Comodor was stopped before it finished; work it had not saved may be lost.";

/** How often the countdown is redrawn: once a second, as it counts seconds. */
const TICK_MS = 1_000;

export function ClosingView({ secondsRemaining, onQuitNow }: {
  secondsRemaining: number;
  onQuitNow: () => void;
}) {
  const [left, setLeft] = useState(secondsRemaining);
  useEffect(() => {
    setLeft(secondsRemaining);
    const timer = setInterval(() => setLeft((was) => Math.max(0, was - 1)), TICK_MS);
    return () => clearInterval(timer);
  }, [secondsRemaining]);
  return (
    <section className="closing" data-testid="closing" aria-live="polite">
      <h1>Closing…</h1>
      <p>
        Comodor is finishing what it was doing. It will be stopped in <span>{left}</span>{" "}
        {left === 1 ? "second" : "seconds"} if it has not finished by then.
      </p>
      <div className="actions">
        <button type="button" onClick={onQuitNow}>Quit now</button>
      </div>
    </section>
  );
}

export function StopOutcome({ outcome }: { outcome: string | null }) {
  if (outcome !== "forced") return null;
  return <p className="stop-outcome" data-testid="stop-outcome">{FORCED_NOTICE}</p>;
}
