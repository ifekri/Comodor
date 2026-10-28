/**
 * The EXPLORER tab (D3a): the workspace's folders and files, as the Core
 * lists them.
 *
 * A WAI-ARIA tree with one tab stop: Up and Down move, Right opens a folder
 * (or moves into it), Left closes it (or moves to its parent), Enter opens a
 * file, Home and End go to the ends. A folder is read a page at a time;
 * "Show more" asks the Core for the next page. A refused entry is listed
 * with a lock and its reason, and opens nothing. Names are inert text.
 */

import type { CoreClient } from "@comodor/client";
import { type KeyboardEvent, useCallback, useEffect, useReducer, useRef, useState } from "react";

import { InertText } from "../view/InertText.tsx";
import {
  EMPTY_TREE, listPage, reasonText, refusalReason, type Row, treeReducer, visibleRows,
} from "./files.ts";

/** A row's depth, as the CSS custom property its indent is drawn from (CSSOM, not a style attribute). */
function depthRef(depth: number) {
  return (element: HTMLElement | null) => element?.style.setProperty("--depth", String(depth));
}

function rowKey(row: Row): string {
  return row.kind === "entry" ? `e:${row.entry.path}` : `${row.kind}:${row.path}`;
}

export function Explorer({ client, workspaceName, workspaceId, activePath, onOpen }: {
  client: CoreClient;
  workspaceName: string;
  /** Changes exactly when the workspace does: the tree starts again. */
  workspaceId: string;
  /** The file shown in the canvas, if any: its row is marked. */
  activePath: string | null;
  onOpen: (path: string) => void;
}) {
  const [tree, dispatch] = useReducer(treeReducer, EMPTY_TREE);
  const [focused, setFocused] = useState(0);
  const treeRef = useRef<HTMLDivElement>(null);
  const generation = useRef(0);

  const load = useCallback(async (path: string, cursor?: string) => {
    const mine = generation.current;
    dispatch({ type: "loading", path });
    try {
      const page = await listPage(client, path, cursor);
      if (mine === generation.current) dispatch({ type: "page", path, page, append: Boolean(cursor) });
    } catch (problem) {
      if (mine !== generation.current) return;
      dispatch({ type: "failed", path, reason: refusalReason(problem) ?? "unknown" });
    }
  }, [client]);

  const refresh = useCallback(() => {
    generation.current += 1;
    dispatch({ type: "reset" });
    void load("");
  }, [load]);

  useEffect(() => {
    refresh();
  }, [refresh, workspaceId]);

  const rows = visibleRows(tree);
  const at = Math.min(focused, Math.max(rows.length - 1, 0));

  const toggle = (path: string) => {
    if (!tree.expanded.has(path) && !tree.folders[path]) void load(path);
    dispatch({ type: "toggle", path });
  };

  const activate = (row: Row) => {
    if (row.kind === "more") void load(row.path, tree.folders[row.path]?.cursor);
    else if (row.kind === "entry" && !row.entry.refused) {
      if (row.entry.kind === "directory") toggle(row.entry.path);
      else onOpen(row.entry.path);
    }
  };

  const moveTo = (index: number) => {
    const next = Math.max(0, Math.min(index, rows.length - 1));
    setFocused(next);
    treeRef.current?.querySelector<HTMLElement>(`[data-row="${next}"]`)?.focus();
  };

  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const row = rows[at];
    if (!row) return;
    let handled = true;
    switch (event.key) {
      case "ArrowDown": moveTo(at + 1); break;
      case "ArrowUp": moveTo(at - 1); break;
      case "Home": moveTo(0); break;
      case "End": moveTo(rows.length - 1); break;
      case "Enter": case " ": activate(row); break;
      case "ArrowRight":
        if (row.kind === "entry" && row.entry.kind === "directory" && !row.entry.refused) {
          if (!row.expanded) toggle(row.entry.path);
          else moveTo(at + 1);
        }
        break;
      case "ArrowLeft": {
        if (row.kind === "entry" && row.expanded) toggle(row.entry.path);
        else {
          const parent = row.kind === "entry" ? row.entry.path.split("/").slice(0, -1).join("/") : row.path;
          const index = rows.findIndex((other) => other.kind === "entry" && other.entry.path === parent);
          if (index >= 0) moveTo(index);
        }
        break;
      }
      default: handled = false;
    }
    if (handled) event.preventDefault();
  };

  const root = tree.folders[""];
  const shownFiles = root ? root.entries.length : 0;
  return (
    <div className="explorer" data-testid="explorer">
      <div className="side-section-head explorer-head">
        <span className="side-section-label" dir="auto"><InertText text={workspaceName.toUpperCase()} linked={false} /></span>
        <span className="side-count" aria-label={`${shownFiles} entries shown`}>{shownFiles}</span>
        <span className="side-section-actions explorer-actions">
          <button type="button" className="side-mini" aria-label="Refresh the explorer" title="Refresh" onClick={refresh}>
            <span className="icon" data-icon="refresh" aria-hidden="true" />
          </button>
          <button type="button" className="side-mini" aria-label="Collapse all folders" title="Collapse all"
                  onClick={() => dispatch({ type: "collapseAll" })}>
            <span className="icon" data-icon="unfold_less" aria-hidden="true" />
          </button>
        </span>
      </div>
      {root?.error ? (
        <p className="side-empty" role="status" data-testid="explorer-refused">{root.error}</p>
      ) : (
        <div ref={treeRef} className="explorer-tree" role="tree" aria-label="Workspace files" onKeyDown={onKey}>
          {rows.map((row, index) => {
            const common = {
              "data-row": index, tabIndex: index === at ? 0 : -1, onFocus: () => setFocused(index),
              ref: depthRef(row.depth),
            };
            if (row.kind === "loading" || row.kind === "error") {
              return <div key={rowKey(row)} ref={depthRef(row.depth)} className="explorer-row explorer-note"
                          role="none">{row.kind === "loading" ? "Loading…" : row.text}</div>;
            }
            if (row.kind === "more") {
              return (
                <div key={rowKey(row)} {...common} role="treeitem" aria-level={row.depth + 1}
                     className="explorer-row explorer-more" data-testid="explorer-more"
                     onClick={() => activate(row)}>
                  Show more ({row.shown} shown)
                </div>
              );
            }
            const { entry } = row;
            const locked = entry.refused !== undefined;
            const isDir = entry.kind === "directory";
            return (
              <div key={rowKey(row)} {...common} role="treeitem" aria-level={row.depth + 1}
                   aria-expanded={isDir && !locked ? row.expanded : undefined}
                   aria-selected={entry.path === activePath}
                   aria-disabled={locked || undefined}
                   title={locked ? reasonText(entry.refused!) : entry.path}
                   className={["explorer-row", isDir ? "is-dir" : "is-file", locked ? "is-locked" : "",
                               entry.path === activePath ? "is-active" : ""].join(" ").trim()}
                   data-path={entry.path} data-kind={entry.kind} data-refused={entry.refused}
                   onClick={() => { setFocused(index); activate(row); }}>
                <span className="icon explorer-chevron" aria-hidden="true"
                      data-icon={isDir && !locked ? (row.expanded ? "expand_more" : "chevron_right") : ""} />
                <span className="icon" aria-hidden="true"
                      data-icon={locked ? "lock" : isDir ? (row.expanded ? "folder_open" : "folder") : "description"} />
                <span className="explorer-name" dir="auto"><InertText text={entry.name} linked={false} /></span>
                {locked && <span className="sr-only">, {reasonText(entry.refused!)}</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
