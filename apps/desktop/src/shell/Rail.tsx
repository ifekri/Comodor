/**
 * The navigation rail: exactly the D2 surfaces (FR-004, FR-006) and the
 * palette control. Nothing for a later phase, not even disabled (FR-005).
 */

import type { PanelSurface } from "./layout.ts";

export type Surface = "conversation" | PanelSurface;

export const SURFACE_NAMES: Readonly<Record<Surface, string>> = {
  conversation: "Conversation",
  core: "Core",
  diagnostics: "Diagnostics",
  shortcuts: "Keyboard shortcuts",
};

/** One Material Symbols icon per control, drawn by the stylesheet from
 * `data-icon`, so the icon's name is never part of the button's text. */
const ICONS: Readonly<Record<Surface | "palette", string>> = {
  conversation: "forum",
  core: "deployed_code",
  diagnostics: "bug_report",
  shortcuts: "keyboard",
  palette: "keyboard_command_key",
};

export function Rail({ active, keys, onShow, onPalette }: {
  /** The surface shown: the open side-panel surface, else the conversation. */
  active: Surface;
  /** Each control's shortcut as a person reads it, if it has one. */
  keys: Readonly<Record<Surface | "palette", string | undefined>>;
  onShow: (surface: Surface) => void;
  onPalette: () => void;
}) {
  const title = (name: string, key: string | undefined) => (key ? `${name} (${key})` : name);
  return (
    <nav className="rail" aria-label="Workbench" data-testid="rail">
      {(Object.keys(SURFACE_NAMES) as Surface[]).map((surface) => (
        <button key={surface} type="button" className="rail-button" data-surface={surface}
                aria-label={SURFACE_NAMES[surface]} aria-current={surface === active ? "true" : "false"}
                title={title(SURFACE_NAMES[surface], keys[surface])}
                onClick={() => onShow(surface)}>
          <span className="icon rail-icon" data-icon={ICONS[surface]} aria-hidden="true" />
        </button>
      ))}
      <button type="button" className="rail-button rail-palette" aria-label="Commands"
              title={title("Commands", keys.palette)} onClick={onPalette}>
        <span className="icon rail-icon" data-icon={ICONS.palette} aria-hidden="true" />
      </button>
    </nav>
  );
}
