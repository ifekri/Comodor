/**
 * Elements of a later phase (spec Clarifications, 2026-10-17): the
 * reference's structure, never a working pretence. A later control is marked
 * unavailable (`aria-disabled`), keeps its place and its focus, says so when
 * chosen — "… arrives in a later version." — and runs nothing.
 */

import { createContext, type ReactNode, useContext } from "react";

/** How the shell says that something arrives later: a short notice. */
export const LaterNotice = createContext<(what: string) => void>(() => {});

export function laterText(what: string): string {
  return `${what} arrives in a later version.`;
}

/** A control of a later phase: unavailable, and saying so when chosen. */
export function LaterButton({ label, icon, className, children }: {
  /** What it would be, in the reference's words ("New file", "Terminal"). */
  label: string;
  /** A Material Symbols name, drawn from `data-icon`. */
  icon?: string | undefined;
  className?: string | undefined;
  /** Visible text, when the control has some; the label names it otherwise. */
  children?: ReactNode;
}) {
  const notice = useContext(LaterNotice);
  return (
    <button type="button" className={`later ${className ?? ""}`.trim()} aria-disabled="true"
            aria-label={children === undefined ? label : undefined} title={laterText(label)} data-later={label}
            onClick={(event) => {
              event.preventDefault();
              notice(label);
            }}>
      {icon && <span className="icon" data-icon={icon} aria-hidden="true" />}
      {children}
    </button>
  );
}
