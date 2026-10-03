/**
 * The window: one screen, driven by what the native side and the Core
 * report. Nothing here decides anything the Core owns (FR-024).
 */

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

import type { NativeApi } from "./bridge.ts";
import { Connection } from "./connection.ts";
import { FailureView } from "./view/FailureView.tsx";
import { type ModelInfo, StatusStrip } from "./view/StatusStrip.tsx";
import { WorkspaceGate } from "./view/WorkspaceGate.tsx";

export function App({ api }: { api: NativeApi }) {
  const connection = useMemo(() => new Connection(api), [api]);
  useEffect(() => {
    void connection.open();
    return () => connection.dispose();
  }, [connection]);
  const { status, client } = useSyncExternalStore(connection.subscribe, () => connection.snapshot);

  // What answers: asked once per client. Best effort — a Core that cannot
  // answer still has a working session; the strip then shows no model.
  const [model, setModel] = useState<ModelInfo | null>(null);
  useEffect(() => {
    setModel(null);
    if (!client) return;
    let alive = true;
    client.call("model.get")
      .then((info) => {
        if (alive) setModel(info as unknown as ModelInfo);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [client]);

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
  const choose = () => void api.invoke("choose_workspace").catch(() => {});

  if (status === null) {
    return <main className="window" data-testid="window"><p className="quiet">Starting…</p></main>;
  }
  return (
    <main className="window" data-testid="window">
      <StatusStrip status={status} model={status.state === "ready" ? model : null} />
      {status.state === "absent" && <WorkspaceGate notice={status.notice} onChoose={choose} />}
      {status.state === "failed" && status.failure !== null && (
        <FailureView failure={status.failure} diagnostics={diagnostics}
                     onRetry={retry} onChoose={choose} />
      )}
    </main>
  );
}
