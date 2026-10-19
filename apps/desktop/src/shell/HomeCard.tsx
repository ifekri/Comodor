/**
 * The reference's home card, on an empty conversation (spec Clarifications,
 * 2026-10-17): four tiles. Workspace is real — it changes the workspace;
 * Loop, Skill and Memory arrive later and say so.
 */

import { LaterButton } from "./Later.tsx";

const LATER = [
  { icon: "cycle", title: "LOOP", label: "Loops" },
  { icon: "school", title: "SKILL", label: "Skills" },
  { icon: "hub", title: "MEMORY", label: "Memory" },
] as const;

export function HomeCard({ canChangeWorkspace, onChangeWorkspace }: {
  canChangeWorkspace: boolean;
  onChangeWorkspace: () => void;
}) {
  return (
    <div className="home" data-testid="home">
      <div className="home-card">
        <button type="button" className="home-tile tile-0" disabled={!canChangeWorkspace} onClick={onChangeWorkspace}>
          <span className="icon home-icon" data-icon="stylus_note" aria-hidden="true" />
          <span className="home-title">WORKSPACE</span>
          <span className="home-sub">CHANGE THE WORKSPACE</span>
        </button>
        {LATER.map((tile, at) => (
          <LaterButton key={tile.title} label={tile.label} className={`home-tile tile-${at + 1}`}>
            <span className="icon home-icon" data-icon={tile.icon} aria-hidden="true" />
            <span className="home-title">{tile.title}</span>
            <span className="home-sub">ARRIVES LATER</span>
          </LaterButton>
        ))}
      </div>
      <span className="home-hint">Write a message below to start.</span>
    </div>
  );
}
