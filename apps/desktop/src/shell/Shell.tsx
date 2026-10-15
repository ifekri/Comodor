/**
 * The workbench shell (contracts/workbench-shell.md): the navigation rail,
 * the main area — D1's own `<main>` — the side panel and the status bar, with
 * the command palette and the keyboard over them. It presents; nothing the
 * Core owns is decided here, and everything that reaches the Core goes
 * through D1's session functions and native operations (FR-029).
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
import { cycleRegions, fallbackTarget, FocusReturn, focusInto } from "./focus.ts";
import { currentPlatform, displayKey, isEditable, isReserved, keyName, reachesShell } from "./keys.ts";
import {
  closePanel, DEFAULT_LAYOUT, type LayoutPreference, PANEL_MAX, PANEL_MIN, type PanelSurface, resizePanel,
  shellLayout, showSurface, stepPanel,
} from "./layout.ts";
import type { LayoutStore } from "./preference.ts";
import { Palette } from "./Palette.tsx";
import { Rail, type Surface, SURFACE_NAMES } from "./Rail.tsx";
import { coreReport } from "./reports.ts";
import { ShellRun } from "./run-context.ts";
import type { SessionStore } from "./session-store.ts";
import { ShortcutsPanel } from "./ShortcutsPanel.tsx";
import { type PanelEdge, SidePanel } from "./SidePanel.tsx";
import { StatusBar } from "./StatusBar.tsx";

/** The rail's width, as `styles.css` draws it. */
export const RAIL_WIDTH = 56;

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
  /** The main area's content: D1's views. */
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

  const shell = shellLayout(width, RAIL_WIDTH, layout);
  const upper = Math.min(shell.room, PANEL_MAX);
  // A drag in progress: shown as it moves, written once when it ends.
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const latestLayout = useRef({ layout, room: shell.room, upper });
  latestLayout.current = { layout, room: shell.room, upper };
  const edge: PanelEdge | undefined = shell.mode !== "beside" ? undefined : {
    min: PANEL_MIN,
    max: upper,
    onKey: (key) => {
      if (key === "ArrowLeft") setLayout(stepPanel(layout, 1, shell.room));
      else if (key === "ArrowRight") setLayout(stepPanel(layout, -1, shell.room));
      else if (key === "Home") setLayout(resizePanel(layout, PANEL_MIN, shell.room));
      else setLayout(resizePanel(layout, upper, shell.room));
    },
    onDragStart: (startX) => {
      const startWidth = shell.shownWidth;
      let last = startWidth;
      const move = (event: PointerEvent | MouseEvent) => {
        // The panel sits to the right: moving its edge left widens it.
        last = Math.min(Math.max(startWidth + startX - event.clientX, PANEL_MIN), latestLayout.current.upper);
        setDragWidth(last);
      };
      const end = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        setDragWidth(null);
        const { layout: now, room } = latestLayout.current;
        setLayout(resizePanel(now, last, room));
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", end);
    },
  };
  const state: ShellState = {
    status, session, paletteOpen,
    panelOpen: layout.panel_open, panelSurface: layout.panel_surface, panelMode: shell.mode,
    canWiden: shell.mode === "beside" && shell.shownWidth < upper,
    canNarrow: shell.mode === "beside" && shell.shownWidth > PANEL_MIN,
  };
  const root = () => rootRef.current ?? document;

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
    if (!layout.panel_open) focusReturn.push(document.activeElement);
    setLayout(showSurface(layout, surface));
    panelFocusDue.current = true;
    setAnnouncement(`${SURFACE_NAMES[surface]} panel opened`);
  };
  const showConversation = () => {
    if (shell.mode === "covering" && layout.panel_open) {
      setLayout(closePanel(layout));
      focusReturn.drop();
    }
    fallbackTarget(mainRef.current ?? document)?.focus();
  };

  const act: ShellActions = {
    openPalette: () => {
      focusReturn.push(document.activeElement);
      setPaletteOpen(true);
    },
    showConversation,
    showSurface: showPanel,
    closePanel: close,
    widenPanel: () => setLayout(stepPanel(layout, 1, shell.room)),
    narrowPanel: () => setLayout(stepPanel(layout, -1, shell.room)),
    resetLayout: () => {
      const wasOpen = layout.panel_open;
      setLayout(DEFAULT_LAYOUT);
      if (wasOpen) focusReturn.restore(root());
    },
    nextRegion: () => cycleRegions(root(), 1),
    previousRegion: () => cycleRegions(root(), -1),
    focusComposer: () => fallbackTarget(mainRef.current ?? document)?.focus(),
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

  // Focus moves into a panel once it is drawn.
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

  const closePalette = () => {
    setPaletteOpen(false);
    focusReturn.restore(root());
  };
  const runFromPalette = (id: string) => {
    closePalette();
    run(id);
  };
  const announceCount = useCallback((count: number) => {
    setAnnouncement(`${count} ${count === 1 ? "command" : "commands"}`);
  }, []);

  // The keyboard (FR-016–FR-019): one listener for the window. Keys typed in
  // a text field reach it only when modified (and F6); the composer keeps
  // Enter and Escape; reserved keys are never taken.
  const keyState = useRef({ paletteOpen, covering: shell.mode === "covering" });
  keyState.current = { paletteOpen, covering: shell.mode === "covering" };
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || keyState.current.paletteOpen) return;
      const name = keyName(event, platform);
      if (name === undefined) return;
      if (name === "escape") {
        // Palette (handled by its own field) → covering panel → composer.
        if (keyState.current.covering) {
          event.preventDefault();
          run(WORKBENCH_COMMAND_IDS.panelClose);
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
  const active: Surface = layout.panel_open ? layout.panel_surface : "conversation";
  const RAIL_COMMANDS: Record<Surface, string> = {
    conversation: WORKBENCH_COMMAND_IDS.viewConversation,
    core: WORKBENCH_COMMAND_IDS.viewCore,
    diagnostics: WORKBENCH_COMMAND_IDS.viewDiagnostics,
    shortcuts: WORKBENCH_COMMAND_IDS.viewShortcuts,
  };

  return (
    <ShellRun.Provider value={run}>
      <div ref={rootRef} className={`shell shell-${shell.compact ? "compact" : "wide"}`} data-testid="shell"
           data-width={String(width)} data-mode={shell.compact ? "covering" : "beside"}
           data-panel={layout.panel_open ? "open" : "closed"} data-reduced-motion={String(reducedMotion)}>
        <Rail active={active} onShow={(surface) => run(RAIL_COMMANDS[surface])}
              onPalette={() => run(WORKBENCH_COMMAND_IDS.paletteOpen)}
              keys={{
                conversation: keyFor(RAIL_COMMANDS.conversation),
                core: keyFor(RAIL_COMMANDS.core),
                diagnostics: keyFor(RAIL_COMMANDS.diagnostics),
                shortcuts: keyFor(RAIL_COMMANDS.shortcuts),
                palette: keyFor(WORKBENCH_COMMAND_IDS.paletteOpen),
              }} />
        <main ref={mainRef} className="window" data-testid="window" tabIndex={-1}>{children}</main>
        {shell.mode === "covering" && (
          <div className="panel-backdrop" data-testid="panel-backdrop" aria-hidden="true"
               onClick={() => run(WORKBENCH_COMMAND_IDS.panelClose)} />
        )}
        {shell.mode !== "closed" && (
          <SidePanel surface={layout.panel_surface} mode={shell.mode} width={dragWidth ?? shell.shownWidth}
                     panelRef={panelRef} edge={edge}
                     onClose={() => run(WORKBENCH_COMMAND_IDS.panelClose)}>
            {layout.panel_surface === "shortcuts" && <ShortcutsPanel registry={commands} platform={platform} />}
            {layout.panel_surface === "diagnostics" && (
              <DiagnosticsPanel api={api} refreshes={refreshes} failure={status?.failure ?? null} />
            )}
            {layout.panel_surface === "core" && status !== null && (
              <CorePanel report={coreReport(status, client, session)} registry={commands} context={context}
                         onRun={run} />
            )}
          </SidePanel>
        )}
        <StatusBar status={status} session={session} announcement={announcement} notice={notice}
                   paletteKey={keyFor(WORKBENCH_COMMAND_IDS.paletteOpen)}
                   onChangeWorkspace={() => run(WORKBENCH_COMMAND_IDS.workspaceChange)}
                   onPalette={() => run(WORKBENCH_COMMAND_IDS.paletteOpen)} />
        {paletteOpen && (
          <Palette registry={commands} context={context} platform={platform} onClose={closePalette}
                   onRun={runFromPalette} onCount={announceCount} />
        )}
      </div>
    </ShellRun.Provider>
  );
}
