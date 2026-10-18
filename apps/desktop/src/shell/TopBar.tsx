/**
 * The top bar of the reference window (spec Clarifications, 2026-10-17): the
 * wordmark, the eight menus, the search — the palette's place — and the
 * actions. A menu item or action either runs a real command of the window's
 * registry or is a later-phase item that says so and runs nothing. Below
 * 760 px the menus fold into one "Menu" and the search into its icon.
 *
 * The menus are a WAI-ARIA menubar: one tab stop, Left and Right (Home and
 * End) between the menus, Down, Enter or Space into one; an open menu closes
 * when focus leaves the menubar, so nothing is left open behind it.
 */

import type { CommandRegistry } from "@comodor/commands";
import { type KeyboardEvent, type ReactNode, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";

import { COMMAND_IDS, type WindowContext } from "../commands.ts";
import { WORKBENCH_COMMAND_IDS as ID } from "./commands.ts";
import { LaterButton, LaterNotice, laterText } from "./Later.tsx";

interface MenuItem {
  readonly label: string;
  /** The command it runs; none for a later-phase item. */
  readonly command?: string;
  /** A rule above it, as in the reference. */
  readonly separator?: boolean;
}

interface Menu {
  readonly label: string;
  readonly items: readonly MenuItem[];
}

/** The reference's menus, item for item; the window's own commands where they exist. */
export const MENUS: readonly Menu[] = [
  { label: "File", items: [
    { label: "New Workspace" }, { label: "Open Folder", command: ID.workspaceChange },
    { label: "Save Session", separator: true }, { label: "Export Thread" }, { label: "Exit", separator: true },
  ] },
  { label: "Model", items: [{ label: "Select Model" }, { label: "Providers" }, { label: "Parameters" }] },
  { label: "Memory", items: [
    { label: "Browse Memory" }, { label: "Add Entry" }, { label: "Clear Session Memory", separator: true },
  ] },
  { label: "Skills", items: [{ label: "Manage Skills" }, { label: "New Skill" }] },
  { label: "Context", items: [
    { label: "Add Files" }, { label: "Attach URL" }, { label: "Context Window", separator: true },
  ] },
  { label: "Agent", items: [{ label: "New Agent" }, { label: "Sub-Agents" }, { label: "Pause All", separator: true }] },
  { label: "Option", items: [
    { label: "Providers" }, { label: "Thread Space" }, { label: "Workspaces" }, { label: "Tools" },
    { label: "Function" }, { label: "Settings", separator: true },
    { label: "Core", command: ID.viewCore, separator: true }, { label: "Diagnostics", command: ID.viewDiagnostics },
    { label: "Keyboard Shortcuts", command: ID.viewShortcuts }, { label: "Commands", command: ID.paletteOpen },
    { label: "Reset Layout", command: ID.layoutReset },
  ] },
  { label: "MCP", items: [{ label: "Servers" }, { label: "Add Server" }, { label: "Logs" }] },
];

function Menus({ narrow, registry, context, keyFor, onRun }: {
  narrow: boolean;
  registry: CommandRegistry<WindowContext>;
  context: WindowContext;
  keyFor: (id: string) => string | undefined;
  onRun: (id: string) => void;
}) {
  const notice = useContext(LaterNotice);
  const [open, setOpen] = useState<string | null>(null);
  // The menubar's one tab stop: the menu last focused.
  const [stop, setStop] = useState(0);
  const bar = useRef<HTMLDivElement>(null);
  const menus: readonly Menu[] = narrow
    ? [{ label: "Menu", items: MENUS.flatMap((menu) => menu.items.map((item, at) => (
      { ...item, label: `${menu.label} · ${item.label}`, separator: at === 0 && menu !== MENUS[0] }))) }]
    : MENUS;
  const tabStop = Math.min(stop, menus.length - 1);

  // Folding or unfolding (the window crossing 760 px) redraws the triggers:
  // focus held in the menubar moves to the corresponding trigger — "Menu"
  // when folding; when unfolding, the menu whose item had it, else the first.
  const wasNarrow = useRef(narrow);
  const refocus = useRef<string | null>(null);
  if (narrow !== wasNarrow.current) {
    const active = document.activeElement;
    if (active instanceof HTMLElement && bar.current?.contains(active)) {
      const item = active.querySelector(".menu-label")?.textContent ?? "";
      refocus.current = narrow ? "Menu"
        : MENUS.find((menu) => item.startsWith(`${menu.label} · `))?.label ?? MENUS[0]!.label;
    }
    wasNarrow.current = narrow;
  }
  useLayoutEffect(() => {
    const label = refocus.current;
    if (label === null) return;
    refocus.current = null;
    setOpen(null);
    const at = menus.findIndex((menu) => menu.label === label);
    if (at >= 0) setStop(at);
    bar.current?.querySelector<HTMLButtonElement>(`[data-menu="${label}"]`)?.focus();
  });

  // A click anywhere else closes the open menu, as in the reference.
  useEffect(() => {
    if (open === null) return;
    const outside = (event: MouseEvent) => {
      if (!bar.current?.contains(event.target as Node)) setOpen(null);
    };
    // Focus leaving the menubar (Tab, F6, a click) closes it too.
    const left = (event: FocusEvent) => {
      if (!bar.current?.contains(event.target as Node)) setOpen(null);
    };
    window.addEventListener("mousedown", outside);
    window.addEventListener("focusin", left);
    return () => {
      window.removeEventListener("mousedown", outside);
      window.removeEventListener("focusin", left);
    };
  }, [open]);

  const trigger = (label: string) => bar.current?.querySelector<HTMLButtonElement>(`[data-menu="${label}"]`);
  const items = (label: string) =>
    [...(bar.current?.querySelectorAll<HTMLElement>(`[data-menu-of="${label}"] [role="menuitem"]`) ?? [])];
  const openAt = (label: string, focusFirst: boolean) => {
    setOpen(label);
    if (focusFirst) requestAnimationFrame(() => items(label)[0]?.focus());
  };
  const close = (label: string) => {
    setOpen(null);
    trigger(label)?.focus();
  };
  const focusMenu = (at: number) => {
    const next = menus[(at + menus.length) % menus.length]!.label;
    if (open !== null) openAt(next, false);
    trigger(next)?.focus();
  };
  const neighbour = (label: string, by: 1 | -1) => {
    const at = menus.findIndex((menu) => menu.label === label);
    return menus[(at + by + menus.length) % menus.length]!.label;
  };
  const enabled = (id: string) => {
    const command = registry.get(id);
    return command !== undefined && (!command.enabled || command.enabled(context));
  };
  const choose = (label: string, item: MenuItem) => {
    setOpen(null);
    trigger(label)?.focus();
    if (item.command === undefined) notice(item.label.split(" · ").at(-1)!);
    else if (enabled(item.command)) onRun(item.command);
  };
  const onMenuKey = (label: string) => (event: KeyboardEvent<HTMLElement>) => {
    const all = items(label);
    const at = all.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(label);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const by = event.key === "ArrowDown" ? 1 : -1;
      all[(at + by + all.length) % all.length]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      (event.key === "Home" ? all[0] : all.at(-1))?.focus();
    } else if ((event.key === "ArrowRight" || event.key === "ArrowLeft") && menus.length > 1) {
      event.preventDefault();
      openAt(neighbour(label, event.key === "ArrowRight" ? 1 : -1), true);
    }
  };

  return (
    <div ref={bar} role="menubar" aria-label="Menu" className="menubar" data-testid="menubar">
      {menus.map((menu, place) => {
        const isOpen = open === menu.label;
        return (
          <div key={menu.label} className="menu-anchor" role="none">
            <button type="button" role="menuitem" className={isOpen ? "menu-trigger open" : "menu-trigger"}
                    data-menu={menu.label} aria-haspopup="menu" aria-expanded={isOpen}
                    tabIndex={place === tabStop ? 0 : -1} onFocus={() => setStop(place)}
                    onClick={() => (isOpen ? setOpen(null) : openAt(menu.label, false))}
                    onMouseEnter={() => {
                      if (open !== null && !isOpen) setOpen(menu.label);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openAt(menu.label, true);
                      } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                        event.preventDefault();
                        focusMenu(place + (event.key === "ArrowRight" ? 1 : -1));
                      } else if (event.key === "Home" || event.key === "End") {
                        event.preventDefault();
                        focusMenu(event.key === "Home" ? 0 : menus.length - 1);
                      } else if (event.key === "Escape" && isOpen) {
                        event.preventDefault();
                        event.stopPropagation();
                        close(menu.label);
                      }
                    }}>
              {menu.label}
            </button>
            {isOpen && (
              <div role="menu" aria-label={menu.label} className="menu" data-menu-of={menu.label}
                   onKeyDown={onMenuKey(menu.label)}>
                {menu.items.map((item) => {
                  const later = item.command === undefined;
                  const unavailable = later || !enabled(item.command!);
                  const key = later ? undefined : keyFor(item.command!);
                  return [
                    item.separator ? <div key={`${item.label}-rule`} role="separator" className="menu-rule" /> : null,
                    <button key={item.label} type="button" role="menuitem" tabIndex={-1}
                            className={later ? "menu-item later" : "menu-item"}
                            aria-disabled={unavailable ? "true" : undefined} data-command={item.command}
                            title={later ? laterText(item.label.split(" · ").at(-1)!) : undefined}
                            onClick={() => choose(menu.label, item)}>
                      <span className="menu-label">{item.label}</span>
                      <span className="menu-key">{later ? "Later" : key ?? ""}</span>
                    </button>,
                  ];
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function TopBar({ narrow, registry, context, keyFor, onRun, palette }: {
  narrow: boolean;
  registry: CommandRegistry<WindowContext>;
  context: WindowContext;
  keyFor: (id: string) => string | undefined;
  onRun: (id: string) => void;
  /** The open palette, drawn in the search's place; null when closed. */
  palette: ReactNode;
}) {
  const paletteKey = keyFor(ID.paletteOpen);
  const cancellable = context.busy && context.cancellable;
  return (
    <header className={palette ? "top-bar palette-open" : "top-bar"} data-testid="top-bar">
      <div className="wordmark">
        <span className="wordmark-mark" aria-hidden="true" />
        <span className="wordmark-text">Comodor</span>
      </div>
      <Menus narrow={narrow} registry={registry} context={context} keyFor={keyFor} onRun={onRun} />
      <div className={narrow ? "top-search narrow" : "top-search"}>
        {palette ?? (
          <button type="button" className="top-search-field" aria-label={narrow ? "Search commands" : undefined}
                  data-focus-key="palette-control"
                  title={paletteKey ? `Commands (${paletteKey})` : "Commands"} onClick={() => onRun(ID.paletteOpen)}>
            {!narrow && <span className="top-search-hint">Search commands…</span>}
            <span className="icon" data-icon={narrow ? "search" : "auto_awesome"} aria-hidden="true" />
          </button>
        )}
      </div>
      <div className="top-actions">
        <LaterButton label="Re-run last prompt" icon="replay" className="top-action" />
        <button type="button" className="top-action" aria-label="Cancel the running turn"
                title={cancellable ? "Cancel the running turn" : "Nothing is running"} disabled={!cancellable}
                onClick={() => onRun(COMMAND_IDS.cancel)}>
          <span className="icon" data-icon="crop_square" aria-hidden="true" />
        </button>
        <LaterButton label="Resume all agents" icon="play_arrow" className="top-action" />
        <LaterButton label="New thread" icon="add_comment" className="top-action" />
      </div>
    </header>
  );
}
