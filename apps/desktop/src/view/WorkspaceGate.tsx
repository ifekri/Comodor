/**
 * Before a workspace is chosen (OD-3): no Core runs until there is one.
 */

import { InertText } from "./InertText.tsx";

export function WorkspaceGate({ notice, onChoose }: {
  notice: string | null;
  onChoose: () => void;
}) {
  return (
    <section className="workspace-gate" data-testid="workspace-gate">
      {notice === null
        ? <p>Choose the folder Comodor will work in.</p>
        : <p className="notice"><InertText text={notice} /></p>}
      {notice !== null && (
        <div className="actions">
          <button type="button" onClick={onChoose}>Choose workspace…</button>
        </div>
      )}
    </section>
  );
}
