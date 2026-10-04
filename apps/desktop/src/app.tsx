/**
 * The window: one screen, driven by what the native side and the Core
 * report. Nothing here decides anything the Core owns (FR-024).
 */

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import type { NativeApi } from "./bridge.ts";
import { Connection } from "./connection.ts";
import type { Kept } from "./state.ts";
import { ClosingView, StopOutcome } from "./view/ClosingView.tsx";
import { FailureView } from "./view/FailureView.tsx";
import { OpenLink } from "./view/InertText.tsx";
import { SessionView } from "./view/SessionView.tsx";
import { StatusStrip } from "./view/StatusStrip.tsx";
import { WorkspaceGate } from "./view/WorkspaceGate.tsx";

export function App({ api }: { api: NativeApi }) {
  const connection = useMemo(() => new Connection(api), [api]);
  useEffect(() => {
    void connection.open();
    return () => connection.dispose();
  }, [connection]);
  const { status, client } = useSyncExternalStore(connection.subscribe, () => connection.snapshot);
  // Kept for the window's whole life, across Core restarts (R12).
  const kept = useRef<Kept>({ storedId: undefined, unsentTurn: undefined }).current;

  const [diagnostics, setDiagnostics] = useState("");
  const failed = status?.state === "failed";
  useEffect(() => {
    if (!failed) return;
    let alive = true;
    api.invoke<string>("diagnostics")
      .then((text) => {
        if (alive) setDiagnostics(text);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [api, failed, status?.failure?.message]);

  const retry = () => void api.invoke("retry").catch(() => {});
  const quitNow = () => void api.invoke("quit_now").catch(() => {});
  const checkAgain = () => void api.invoke("check_again").catch(() => {});
  const choose = () => void api.invoke("choose_workspace").catch(() => {});
  const open = useMemo(() => (url: string) => void api.invoke("open_external", { url }).catch(() => {}),
                       [api]);

  if (status === null) {
    return <main className="window" data-testid="window"><p className="quiet">Starting…</p></main>;
  }
  if (status.state === "ready" && client !== null) {
    return (
      <OpenLink.Provider value={open}>
        <main className="window" data-testid="window">
          <StopOutcome outcome={status.stop_outcome} />
          <SessionView client={client} kept={kept} status={status} onCheckAgain={checkAgain}
                       onChangeWorkspace={choose} />
        </main>
      </OpenLink.Provider>
    );
  }
  return (
    <OpenLink.Provider value={open}>
      <main className="window" data-testid="window">
        <StatusStrip status={status} model={null} onChangeWorkspace={choose} />
        <StopOutcome outcome={status.stop_outcome} />
        {status.state === "stopping" && (
          <ClosingView secondsRemaining={status.closing?.seconds_remaining ?? 0} onQuitNow={quitNow} />
        )}
        {status.state === "absent" && <WorkspaceGate notice={status.notice} onChoose={choose} />}
        {status.state === "failed" && status.failure !== null && (
          <FailureView failure={status.failure} diagnostics={diagnostics}
                       restarts={{ count: status.restart_count, limit: status.restart_limit }}
                       onRetry={retry} onChoose={choose} />
        )}
      </main>
    </OpenLink.Provider>
  );
}
