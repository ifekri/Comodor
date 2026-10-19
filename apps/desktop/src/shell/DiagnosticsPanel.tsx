/**
 * The diagnostics panel (US5; FR-009): the native side's current diagnostic
 * tail, as inert text — control characters visible, no link, no markup —
 * fetched when it opens, on refresh, and whenever the Core fails. Available
 * in every state, not only on failure.
 */

import { useEffect, useState } from "react";

import type { NativeApi } from "../bridge.ts";
import { InertText } from "../view/InertText.tsx";

export function DiagnosticsPanel({ api, refreshes, failure }: {
  api: NativeApi;
  /** Bumped by "Refresh diagnostics". */
  refreshes: number;
  /** The Core's failure, if it failed: a new one fetches the tail again. */
  failure: unknown;
}) {
  const [tail, setTail] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.invoke<string>("diagnostics")
      .then((text) => {
        if (alive) setTail(text);
      })
      .catch(() => {
        if (alive) setTail(null);
      });
    return () => {
      alive = false;
    };
  }, [api, refreshes, failure]);
  if (tail === null) return <p className="quiet" data-testid="diagnostics-empty">No diagnostic output yet.</p>;
  if (tail === "") return <p className="quiet" data-testid="diagnostics-empty">The Core has written no diagnostics.</p>;
  return (
    <>
      <h3 className="panel-section">OUTPUT</h3>
      <pre className="diagnostics" data-testid="diagnostics-tail" dir="auto"><InertText text={tail} linked={false} /></pre>
    </>
  );
}
