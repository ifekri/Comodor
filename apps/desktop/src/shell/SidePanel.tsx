/**
 * The side panel: one supporting surface, beside the main area or covering
 * it in a narrow window (FR-025, FR-026). It is not modal and traps nothing.
 */

import type { KeyboardEvent, PointerEvent, ReactNode, Ref } from "react";

import type { PanelSurface } from "./layout.ts";
import { SURFACE_NAMES } from "./Rail.tsx";

/** The panel's edge beside the main area: a window splitter (FR-025). */
export interface PanelEdge {
  readonly min: number;
  readonly max: number;
  /** Arrow keys, Home and End, on the focused edge only. */
  onKey(key: "ArrowLeft" | "ArrowRight" | "Home" | "End"): void;
  /** A drag starts at this pointer position. */
  onDragStart(clientX: number): void;
}

const EDGE_KEYS = new Set(["ArrowLeft", "ArrowRight", "Home", "End"]);

export function SidePanel({ surface, mode, width, panelRef, edge, onClose, children }: {
  surface: PanelSurface;
  mode: "beside" | "covering";
  /** The width shown, in logical pixels. */
  width: number;
  panelRef?: Ref<HTMLElement> | undefined;
  /** Beside the main area only: covering, the panel is not resized. */
  edge?: PanelEdge | undefined;
  onClose: () => void;
  children: ReactNode;
}) {
  const name = SURFACE_NAMES[surface];
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!edge || !EDGE_KEYS.has(event.key) || event.ctrlKey || event.metaKey || event.altKey) return;
    event.preventDefault();
    edge.onKey(event.key as "ArrowLeft" | "ArrowRight" | "Home" | "End");
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!edge || event.button !== 0) return;
    event.preventDefault();
    edge.onDragStart(event.clientX);
  };
  return (
    <aside ref={panelRef} className={`side-panel side-panel-${mode}`} aria-label={name}
           data-testid="side-panel" data-surface={surface} tabIndex={-1} style={{ width: `${width}px` }}>
      {edge && (
        <div className="side-panel-edge" role="separator" aria-orientation="vertical"
             aria-label="Resize the side panel" aria-valuenow={Math.round(width)} aria-valuemin={edge.min}
             aria-valuemax={Math.round(edge.max)} tabIndex={0} onKeyDown={onKeyDown} onPointerDown={onPointerDown} />
      )}
      <div className="side-panel-header">
        <h2 className="side-panel-title">{name}</h2>
        <button type="button" className="side-panel-close" aria-label="Close the side panel"
                title="Close the side panel" onClick={onClose}>
          <span className="icon" data-icon="close" aria-hidden="true" />
        </button>
      </div>
      <div className="side-panel-body">{children}</div>
    </aside>
  );
}
