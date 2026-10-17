/**
 * The workbench shell, in the composition of the owner's reference window
 * (spec Clarifications, 2026-10-17; contracts/workbench-shell.md): a top bar
 * with the menus, the search (the palette's place) and the actions; the left
 * sidebar; the canvas — D1's own `<main>` with the conversation over the
 * prompt area; the status bar; and the modal panel for the Core panel,
 * diagnostics and the keyboard shortcuts. It presents; nothing the Core owns
 * is decided here, and everything that reaches the Core goes through D1's
 * session functions and native operations (FR-029).
 */

import {
  type MutableRefObject, type ReactNode, type RefObject, useCallback, useEffect, useLayoutEffect, useMemo, useRef,
  useState, useSyncExternalStore,
} from "react";

import type { CoreClient } from "@comodor/client";

import type { CoreStatus, NativeApi } from "../bridge.ts";
import { commands, type WindowContext } from "../commands.ts";
import { stateLabel } from "../view/StatusStrip.tsx";
import { type ShellActions, type ShellContext, type ShellState, WORKBENCH_COMMAND_IDS } from "./commands.ts";
import { CorePanel } from "./CorePanel.tsx";
import { DiagnosticsPanel } from "./DiagnosticsPanel.tsx";
import { cycleRegions, fallbackTarget, focusBack, FocusReturn, focusInto, isUsable } from "./focus.ts";
import { currentPlatform, displayKey, isEditable, isReserved, keyName, reachesShell } from "./keys.ts";
import { closePanel, COMPACT_BELOW, DEFAULT_LAYOUT, type LayoutPreference, type PanelSurface, showSurface } from "./layout.ts";
import { LaterNotice, laterText } from "./Later.tsx";
import { ModalPanel, SURFACE_NAMES } from "./ModalPanel.tsx";
import type { LayoutStore } from "./preference.ts";
import { Palette } from "./Palette.tsx";
import { coreReport } from "./reports.ts";
import { ShellRun } from "./run-context.ts";
import type { SessionStore } from "./session-store.ts";
import { ShortcutsPanel } from "./ShortcutsPanel.tsx";
import { Sidebar } from "./Sidebar.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { TopBar } from "./TopBar.tsx";

/** Below this measured width the reference's menus fold into one "Menu" (its `min-width`). */
export const MENUS_FOLD_BELOW = 760;

/** How long a later-phase notice stays. */
const NOTICE_MS = 2600;

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/** Whether the system asks for reduced motion, following its changes (FR-020). */
function useReducedMotion(): boolean {
  const query = () => (typeof window.matchMedia === "function" ? window.matchMedia(REDUCED_MOTION) : undefined);
  const [reduced, setReduced] = useState(() => query()?.matches === true);
  useEffect(() => {
    const list = query();
    if (!list) return;
    const changed = () => setReduced(list.matches);
    list.addEventListener?.("change", changed);
    return () => list.removeEventListener?.("change", changed);
  }, []);
  return reduced;
}

/** D1's native operations, as the window already calls them. */
export interface NativeActions {
  changeWorkspace(): void;
  checkAgain(): void;
  retry(): void;
  quitNow(): void;
}

/**
 * The shell root's measured width: its `ResizeObserver` content width, in
 * fractional logical pixels, never rounded. Before the first observation —
 * and where there is no layout engine — the window's inner width stands in.
 */
function useMeasuredWidth(root: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(() => (typeof window === "undefined" ? 0 : window.innerWidth));
  useLayoutEffect(() => {
    const element = root.current;
    let observed = false;
    const observer = typeof ResizeObserver === "undefined" || element === null ? undefined
      : new ResizeObserver((entries) => {
        const measured = entries[0]?.contentRect.width ?? 0;
        if (measured > 0) {
          observed = true;
          setWidth(measured);
        }
      });
    if (element !== null) observer?.observe(element);
    const onResize = () => {
      if (!observed) setWidth(window.innerWidth);
    };
    window.addEventListener("resize", onResize);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", onResize);
    };
  }, [root]);
  return width;
}

export function Shell({ api, status, client, store, layouts, native, runRef, children }: {
  api: NativeApi;
  status: CoreStatus | null;
  /** The current Core's client, once started: its handshake is a Core report. */
  client: CoreClient | null;
  store: SessionStore;
  /** The one stored layout: read once per page load, written after each change. */
  layouts: LayoutStore;
  native: NativeActions;
  /** Where the window finds `run`, for D1's own buttons. */
  runRef?: MutableRefObject<((id: string) => void) | null> | undefined;
  /** The canvas's content: D1's views. */
  children: ReactNode;
}) {
  const session = useSyncExternalStore(store.subscribe, store.get);
  const platform = useMemo(currentPlatform, []);
  const rootRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const width = useMeasuredWidth(rootRef);
  const { layout, notice } = useSyncExternalStore(layouts.subscribe, layouts.get);
  const setLayout = (next: LayoutPreference) => layouts.set(next);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [refreshes, setRefreshes] = useState(0);
  const [focusReturn] = useState(() => new FocusReturn());
  const panelFocusDue = useRef(false);
  const reducedMotion = useReducedMotion();

  // The sidebar: beside from the compact threshold up (the person may hide
  // it); below, hidden, and covering the canvas while opened (FR-026).
  const compact = width < COMPACT_BELOW;
  const folded = width < MENUS_FOLD_BELOW;
  const [sidebarHidden, setSidebarHidden] = useState(false);
  const [sidebarCovering, setSidebarCovering] = useState(false);
  const sidebarShown = compact ? sidebarCovering : !sidebarHidden;
  useEffect(() => {
    if (!compact) setSidebarCovering(false);
  }, [compact]);

  // A later-phase item says so, briefly, and once to assistive technology.
  const [later, setLater] = useState<{ text: string; at: number } | null>(null);
  const sayLater = useCallback((what: string) => {
    const text = laterText(what);
    setLater({ text, at: Date.now() });
    setAnnouncement(text);
  }, []);
  useEffect(() => {
    if (later === null) return;
    const timer = setTimeout(() => setLater(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [later]);

  const state: ShellState = {
    status, session, paletteOpen, panelOpen: layout.panel_open, panelSurface: layout.panel_surface, sidebarShown,
  };
  const root = () => rootRef.current ?? document;
  // The palette's opener while it waits to be drawn again (the top bar's
  // search, replaced by the palette): what a command run from the palette
  // records as its own opener, and where focus goes once the palette is gone.
  const pendingOpener = useRef<{ element: Element | null; focusAtClose: Element | null } | null>(null);
  const currentFocus = () => (pendingOpener.current !== null ? pendingOpener.current.element : document.activeElement);

  const close = () => {
    if (!layout.panel_open) return;
    setLayout(closePanel(layout));
    focusReturn.restore(root());
  };
  const showPanel = (surface: PanelSurface) => {
    if (layout.panel_open && layout.panel_surface === surface) {
      close();
      return;
    }
    if (!layout.panel_open) focusReturn.push(currentFocus());
    setLayout(showSurface(layout, surface));
    panelFocusDue.current = true;
    setAnnouncement(`${SURFACE_NAMES[surface]} panel opened`);
  };
  const closeSidebarCover = (restore: boolean) => {
    if (!sidebarCovering) return;
    setSidebarCovering(false);
    if (restore) focusReturn.restore(root());
    else focusReturn.drop();
  };
  const showConversation = () => {
    if (layout.panel_open) {
      setLayout(closePanel(layout));
      focusReturn.drop();
    }
    closeSidebarCover(false);
    fallbackTarget(mainRef.current ?? document)?.focus();
  };
  const toggleSidebar = () => {
    if (!compact) {
      setSidebarHidden((hidden) => !hidden);
      return;
    }
    if (sidebarCovering) {
      closeSidebarCover(true);
      return;
    }
    focusReturn.push(currentFocus());
    setSidebarCovering(true);
    requestAnimationFrame(() => focusInto(rootRef.current?.querySelector<HTMLElement>(".sidebar") ?? null));
  };

  const act: ShellActions = {
    openPalette: () => {
      focusReturn.push(document.activeElement);
      setPaletteOpen(true);
    },
    showConversation,
    showSurface: showPanel,
    closePanel: close,
    toggleSidebar,
    resetLayout: () => {
      const wasOpen = layout.panel_open;
      setLayout(DEFAULT_LAYOUT);
      setSidebarHidden(false);
      if (wasOpen) focusReturn.restore(root());
    },
    nextRegion: () => cycleRegions(root(), 1),
    previousRegion: () => cycleRegions(root(), -1),
    // The composer may be behind a panel or the covering sidebar: show it first.
    focusComposer: showConversation,
    jumpToNewest: () => {
      const conversation = mainRef.current?.querySelector<HTMLElement>('[data-testid="conversation"]');
      if (conversation) conversation.scrollTop = conversation.scrollHeight;
    },
    refreshDiagnostics: () => setRefreshes((count) => count + 1),
    changeWorkspace: native.changeWorkspace,
    checkAgain: native.checkAgain,
    retry: native.retry,
    quitNow: native.quitNow,
  };
  const shellContext: ShellContext = { state, act };
  const composer = session?.composer() ?? null;
  const context: WindowContext = {
    shell: shellContext,
    busy: session?.busy ?? false,
    // D1's Send rule, and (in the palette) a draft to send.
    ready: session !== null && session.shown && !session.gated && session.model?.configured === true
      && composer?.hasText === true,
    cancellable: session !== null && !session.gated,
    send: () => composer?.send(),
    cancel: () => session?.cancel(),
  };

  // The context as of the last render: what a key or a click acts on.
  const latest = useRef(context);
  latest.current = context;
  const run = useCallback((id: string) => {
    void commands.run(id, latest.current);
  }, []);
  useLayoutEffect(() => {
    if (runRef) runRef.current = run;
  }, [runRef, run]);

  // Focus moves into the panel once it is drawn.
  useLayoutEffect(() => {
    if (panelFocusDue.current && panelRef.current) {
      panelFocusDue.current = false;
      focusInto(panelRef.current);
    }
  });

  // The Core's state, said once per change (FR-020).
  const coreState = status?.state;
  useEffect(() => {
    if (coreState !== undefined) setAnnouncement(`Core: ${stateLabel(coreState)}`);
  }, [coreState]);

  // Closing the palette gives focus back to its opener at once when it is
  // still there; an opener drawn anew in the palette's place (the top bar's
  // search) takes it once the palette is gone — unless the command chosen in
  // the palette has placed focus itself.
  const closePalette = () => {
    const opener = focusReturn.take();
    setPaletteOpen(false);
    if (isUsable(opener)) opener.focus();
    else pendingOpener.current = { element: opener, focusAtClose: document.activeElement };
  };
  useLayoutEffect(() => {
    const pending = pendingOpener.current;
    if (pending === null || paletteOpen) return;
    pendingOpener.current = null;
    const active = document.activeElement;
    const placed = active !== null && active !== document.body && active.isConnected && active !== pending.focusAtClose;
    if (!placed) focusBack(pending.element, root());
  });
  const runFromPalette = (id: string) => {
    closePalette();
    run(id);
  };
  const announceCount = useCallback((count: number) => {
    setAnnouncement(`${count} ${count === 1 ? "command" : "commands"}`);
  }, []);

  // The keyboard (FR-016–FR-019): one listener for the window. Keys typed in
  // a text field reach it only when modified (and F6); the composer keeps
  // Enter and Escape; reserved keys are never taken. Escape closes the
  // topmost of: the palette, an open menu (its own handler), the panel, the
  // covering sidebar.
  const keyState = useRef({ paletteOpen, panelOpen: layout.panel_open, covering: sidebarCovering, closePalette,
                            closeCover: () => closeSidebarCover(true) });
  keyState.current = { paletteOpen, panelOpen: layout.panel_open, covering: sidebarCovering, closePalette,
                       closeCover: () => closeSidebarCover(true) };
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const name = keyName(event, platform);
      if (keyState.current.paletteOpen) {
        // The palette does not trap focus: from anywhere, Escape closes it
        // (its own field handles Escape first, when it has the focus).
        if (name === "escape") {
          event.preventDefault();
          keyState.current.closePalette();
        }
        return;
      }
      if (name === undefined) return;
      if (name === "escape") {
        if (keyState.current.panelOpen) {
          event.preventDefault();
          run(WORKBENCH_COMMAND_IDS.panelClose);
        } else if (keyState.current.covering) {
          event.preventDefault();
          keyState.current.closeCover();
        }
        return;
      }
      if (!reachesShell(name, isEditable(event.target)) || isReserved(name)) return;
      const command = commands.forKey(name);
      if (command === undefined || command.id === "conversation.send") return;
      event.preventDefault();
      run(command.id);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [platform, run]);

  const keyFor = (id: string) => {
    const binding = commands.allBindings().find((entry) => entry.command === id);
    return binding ? displayKey(binding.key, platform) : undefined;
  };
  const workspace = session?.workspace ?? status?.workspace ?? null;
  const changeEnabled = commands.get(WORKBENCH_COMMAND_IDS.workspaceChange)?.enabled?.(context) ?? false;
  const palette = paletteOpen ? (
    <Palette registry={commands} context={context} platform={platform} onClose={closePalette}
             onRun={runFromPalette} onCount={announceCount} />
  ) : null;

  return (
    <ShellRun.Provider value={run}>
      <LaterNotice.Provider value={sayLater}>
        <div ref={rootRef} className={["shell", compact ? "shell-compact" : "shell-wide", folded ? "shell-folded" : "",
                                       sidebarShown ? "sidebar-shown" : "sidebar-hidden"].join(" ").trim()}
             data-testid="shell" data-width={String(width)} data-mode={compact ? "covering" : "beside"}
             data-panel={layout.panel_open ? "open" : "closed"} data-sidebar={sidebarShown ? "shown" : "hidden"}
             data-reduced-motion={String(reducedMotion)}>
          <TopBar narrow={folded} registry={commands} context={context} keyFor={keyFor} onRun={run} palette={palette} />
          {sidebarShown && compact && (
            <div className="sidebar-backdrop" data-testid="sidebar-backdrop" aria-hidden="true"
                 onClick={() => closeSidebarCover(true)} />
          )}
          {sidebarShown && (
            <Sidebar session={session} workspace={workspace} mode={compact ? "covering" : "beside"}
                     canChangeWorkspace={changeEnabled} onChangeWorkspace={() => run(WORKBENCH_COMMAND_IDS.workspaceChange)}
                     onShowConversation={() => run(WORKBENCH_COMMAND_IDS.viewConversation)} />
          )}
          <div className="canvas">
            <button type="button" className="sidebar-toggle" aria-label={sidebarShown ? "Hide the sidebar" : "Show the sidebar"}
                    aria-expanded={sidebarShown} title={keyFor(WORKBENCH_COMMAND_IDS.sidebarToggle)
                      ? `Show or hide the sidebar (${keyFor(WORKBENCH_COMMAND_IDS.sidebarToggle)})` : "Show or hide the sidebar"}
                    onClick={() => run(WORKBENCH_COMMAND_IDS.sidebarToggle)}>
              <span className="icon" data-icon="chevron_left" aria-hidden="true" />
            </button>
            <main ref={mainRef} className="window" data-testid="window" tabIndex={-1}>{children}</main>
          </div>
          <StatusBar status={status} session={session} announcement={announcement} notice={notice}
                     diagnosticsKey={keyFor(WORKBENCH_COMMAND_IDS.viewDiagnostics)}
                     onChangeWorkspace={() => run(WORKBENCH_COMMAND_IDS.workspaceChange)}
                     onDiagnostics={() => run(WORKBENCH_COMMAND_IDS.viewDiagnostics)} />
          {layout.panel_open && (
            <ModalPanel surface={layout.panel_surface} panelRef={panelRef}
                        onClose={() => run(WORKBENCH_COMMAND_IDS.panelClose)}>
              {layout.panel_surface === "shortcuts" && <ShortcutsPanel registry={commands} platform={platform} />}
              {layout.panel_surface === "diagnostics" && (
                <DiagnosticsPanel api={api} refreshes={refreshes} failure={status?.failure ?? null} />
              )}
              {layout.panel_surface === "core" && status !== null && (
                <CorePanel report={coreReport(status, client, session)} registry={commands} context={context}
                           onRun={run} />
              )}
            </ModalPanel>
          )}
          {later !== null && (
            <div key={later.at} className="toast" data-testid="later-notice" aria-hidden="true">
              <span className="icon" data-icon="error" aria-hidden="true" />
              <span>{later.text}</span>
            </div>
          )}
        </div>
      </LaterNotice.Provider>
    </ShellRun.Provider>
  );
}
