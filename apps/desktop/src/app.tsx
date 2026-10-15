/**
 * The window: the workbench shell around D1's views, driven by what the
 * native side and the Core report. Nothing here decides anything the Core
 * owns (FR-024).
 */

import { type ReactNode, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import type { NativeApi } from "./bridge.ts";
import { Connection } from "./connection.ts";
import { SessionStore } from "./shell/session-store.ts";
import { WORKBENCH_COMMAND_IDS } from "./shell/commands.ts";
import { LayoutStore } from "./shell/preference.ts";
import { type NativeActions, Shell } from "./shell/Shell.tsx";
import { keptIn } from "./state.ts";
import { ClosingView, StopOutcome } from "./view/ClosingView.tsx";
import { FailureView } from "./view/FailureView.tsx";
import { OpenLink } from "./view/InertText.tsx";
import { SessionView } from "./view/SessionView.tsx";
import { WorkspaceGate } from "./view/WorkspaceGate.tsx";

/** The window's session storage, where it is available. */
function windowStorage(): Storage | undefined {
  try {
    return window.sessionStorage;
  } catch {
    return undefined;
  }
}

export function App({ api }: { api: NativeApi }) {
  const connection = useMemo(() => new Connection(api), [api]);
  // The one stored layout (D2), read once per page load — after `connect`,
  // so the read never delays or reorders it.
  const layouts = useMemo(() => new LayoutStore(api), [api]);
  useEffect(() => {
    void connection.open();
    void layouts.load();
    return () => connection.dispose();
  }, [connection, layouts]);
  const { status, client } = useSyncExternalStore(connection.subscribe, () => connection.snapshot);
  // Kept for the window's whole life, across Core restarts and reloads (R12).
  const [kept] = useState(() => keptIn(windowStorage()));
  // The open session, as the shell reads it; empty whenever none is open.
  const [store] = useState(() => new SessionStore());

  const [diagnostics, setDiagnostics] = useState("");
  const failed = status?.state === "failed";
  // Fetched on every report of the failure, not once: a faulted Core's last
  // output is read only after it exits, and the native side reports again
  // then.
  const failure = failed ? status : null;
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
  }, [api, failed, failure]);

  // D1's native operations. The shell's commands call these; D1's own
  // buttons run those commands, so each action is one command (FR-010).
  const native: NativeActions = useMemo(() => ({
    retry: () => void api.invoke("retry").catch(() => {}),
    quitNow: () => void api.invoke("quit_now").catch(() => {}),
    checkAgain: () => void api.invoke("check_again").catch(() => {}),
    changeWorkspace: () => void api.invoke("choose_workspace").catch(() => {}),
  }), [api]);
  const runRef = useRef<((id: string) => void) | null>(null);
  const command = (id: string) => () => runRef.current?.(id);
  const retry = command(WORKBENCH_COMMAND_IDS.retry);
  const quitNow = command(WORKBENCH_COMMAND_IDS.quitNow);
  const checkAgain = command(WORKBENCH_COMMAND_IDS.checkAgain);
  const choose = command(WORKBENCH_COMMAND_IDS.workspaceChange);
  const open = useMemo(() => (url: string) => void api.invoke("open_external", { url }).catch(() => {}),
                       [api]);

  // Every view sits in the workbench shell (D2): D1's <main>, framed by the
  // rail, the side panel and the status bar, which now carries the strip.
  let content: ReactNode;
  if (status === null) {
    content = <p className="quiet">Starting…</p>;
  } else if ((status.state === "ready" || status.state === "checking") && client !== null) {
    // While the Core is checked after the machine slept, the conversation
    // stays on screen; nothing can be sent until the Core has answered.
    content = (
      <>
        <StopOutcome outcome={status.stop_outcome} />
        <SessionView client={client} kept={kept} status={status} onCheckAgain={checkAgain}
                     store={store} />
      </>
    );
  } else {
    content = (
      <>
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
      </>
    );
  }
  return (
    <OpenLink.Provider value={open}>
      <Shell api={api} status={status} client={client} store={store} layouts={layouts} native={native}
             runRef={runRef}>
        {content}
      </Shell>
    </OpenLink.Provider>
  );
}
