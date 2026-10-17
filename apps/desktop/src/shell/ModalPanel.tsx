/**
 * The reference window's modal panel (spec Clarifications, 2026-10-17), for
 * the D2 surfaces that are not the conversation: the Core panel, diagnostics
 * and the keyboard shortcuts. A breadcrumb, a title and a line of
 * description; the surface's sections; "Esc to close" and Close. It opens,
 * closes, is restored and takes focus as the side panel did (FR-007, FR-019,
 * FR-021); it is not resized. Escape, a click on the backdrop, the close
 * control and Close all close it; nothing traps focus.
 */

import type { ReactNode, RefObject } from "react";

import type { PanelSurface } from "./layout.ts";

export type Surface = "conversation" | PanelSurface;

export const SURFACE_NAMES: Readonly<Record<Surface, string>> = {
  conversation: "Conversation",
  core: "Core",
  diagnostics: "Diagnostics",
  shortcuts: "Keyboard shortcuts",
};

const HEADINGS: Readonly<Record<PanelSurface, { crumb: string; description: string }>> = {
  core: { crumb: "CORE / STATUS", description: "What the native side and the Core reported for the current Core." },
  diagnostics: { crumb: "CORE / DIAGNOSTICS", description: "The Core's recent diagnostic output, shown as plain text." },
  shortcuts: { crumb: "HELP / KEYBOARD", description: "Every shortcut of this window, and the command it runs." },
};

export function ModalPanel({ surface, panelRef, onClose, children }: {
  surface: PanelSurface;
  panelRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  children: ReactNode;
}) {
  const name = SURFACE_NAMES[surface];
  const heading = HEADINGS[surface];
  return (
    <div className="modal-layer">
      <div className="modal-backdrop" data-testid="panel-backdrop" aria-hidden="true" onClick={onClose} />
      <section ref={panelRef as RefObject<HTMLElement>} role="dialog" aria-label={name}
               className="modal-panel" data-testid="side-panel" data-surface={surface} tabIndex={-1}>
        <div className="modal-head">
          <div className="modal-titles">
            <span className="modal-crumb">{heading.crumb}</span>
            <h2 className="modal-title">{name}</h2>
            <span className="modal-description">{heading.description}</span>
          </div>
          <button type="button" className="modal-close" aria-label="Close the panel" title="Close (Esc)" onClick={onClose}>
            <span className="icon" data-icon="close" aria-hidden="true" />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-foot">
          <span className="modal-hint">Esc to close</span>
          <button type="button" className="modal-done" onClick={onClose}>Close</button>
        </div>
      </section>
    </div>
  );
}
