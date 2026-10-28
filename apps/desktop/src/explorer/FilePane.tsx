/**
 * The canvas's tabs and the read-only file view (D3a).
 *
 * The thread — the conversation — is the first tab and is never closed; each
 * file opened from the explorer is a tab after it. A file's text comes from
 * the Core (`workspace.read`) and is shown read-only; a file the Core refuses,
 * or cannot show as text, says why instead.
 */

import type { CoreClient } from "@comodor/client";
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { flushSync } from "react-dom";

import { InertText } from "../view/InertText.tsx";
import { EOL_NAMES, type FileContent, LANGUAGE_NAMES, languageOf, readFile, reasonText } from "./files.ts";
import { baseName, type TabsStore } from "./tabs.ts";
import { createViewer, type Viewer } from "./viewer.ts";

function TabStrip({ tabs, onKeyShown }: { tabs: TabsStore; onKeyShown?: () => void }) {
  const state = useSyncExternalStore(tabs.subscribe, tabs.get);
  const ids: (string | null)[] = [null, ...state.open];
  const stripRef = useRef<HTMLDivElement>(null);
  const closeTab = (path: string) => {
    const canvas = stripRef.current?.parentElement;
    const closing = [...(stripRef.current?.querySelectorAll<HTMLElement>("[role=tab]") ?? [])]
      .find((tab) => tab.dataset["path"] === path);
    const hadFocus = closing?.contains(closing.ownerDocument.activeElement) ?? false;
    // The replacement tab must be committed before focus moves to it. When
    // the last file closes, the strip disappears and the conversation remains.
    flushSync(() => tabs.close(path));
    if (hadFocus) {
      const selected = stripRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
      (selected ?? canvas?.querySelector<HTMLElement>(".canvas-body"))?.focus();
    }
  };
  const focusTab = (index: number) => {
    const next = (index + ids.length) % ids.length;
    tabs.show(ids[next] ?? null);
    stripRef.current?.querySelectorAll<HTMLElement>("[role=tab]")[next]?.focus();
  };
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const at = ids.indexOf(state.active);
    if (event.key === "ArrowRight") focusTab(at + 1);
    else if (event.key === "ArrowLeft") focusTab(at - 1);
    else if (event.key === "Home") focusTab(0);
    else if (event.key === "End") focusTab(ids.length - 1);
    else if (event.key === "Delete" && state.active !== null) closeTab(state.active);
    else return;
    event.preventDefault();
    onKeyShown?.();
  };
  return (
    <div ref={stripRef} className="file-tabs" role="tablist" aria-label="Open files" onKeyDown={onKey}
         data-testid="file-tabs">
      {ids.map((path) => {
        const shown = path === state.active;
        return (
          // Only tabs belong to a tablist: the close mark is part of its tab,
          // not a control of its own; the keyboard closes the shown tab with Delete.
          <button key={path ?? "thread"} type="button" role="tab" aria-selected={shown} tabIndex={shown ? 0 : -1}
                  className={shown ? "file-tab is-active" : "file-tab"} data-path={path ?? ""}
                  title={path === null ? "The conversation" : `${path} (Delete closes it)`}
                  aria-keyshortcuts={path === null ? undefined : "Delete"}
                  onClick={() => tabs.show(path)}>
            <span className="icon" aria-hidden="true" data-icon={path === null ? "forum" : "description"} />
            <span className="file-tab-name" dir="auto">
              {path === null ? "Thread" : <InertText text={baseName(path)} linked={false} />}
            </span>
            {path !== null && (
              <span className="file-tab-close" aria-hidden="true" data-close={path}
                    onClick={(event) => { event.stopPropagation(); closeTab(path); }}>
                <span className="icon" data-icon="close" />
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function Breadcrumb({ content, onCopyPath, copied }: { content: FileContent; onCopyPath: () => void; copied: boolean }) {
  const segments = content.path.split("/");
  const facts = content.kind === "text"
    ? [LANGUAGE_NAMES[languageOf(content.path)], `${content.lines.toLocaleString("en-US")} lines`,
       content.encoding.toUpperCase() + (content.bom ? " with BOM" : ""), EOL_NAMES[content.eol] ?? content.eol,
       ...(content.replaced ? ["some bytes could not be decoded"] : []), "Read-only"]
    : [];
  return (
    <div className="file-crumbs" data-testid="file-crumbs">
      <nav aria-label="Path" className="file-crumb-path">
        {segments.map((segment, at) => (
          <span key={at} className={at === segments.length - 1 ? "file-crumb is-last" : "file-crumb"} dir="auto">
            {at > 0 && <span className="icon" data-icon="chevron_right" aria-hidden="true" />}
            <InertText text={segment} linked={false} />
          </span>
        ))}
      </nav>
      <span className="file-facts" data-testid="file-facts">{facts.join(" · ")}</span>
      <button type="button" className="file-action" onClick={onCopyPath} aria-label="Copy the file's path">
        <span className="icon" data-icon={copied ? "check" : "content_copy"} aria-hidden="true" />
        {copied ? "Copied" : "Path"}
      </button>
    </div>
  );
}

export function FileView({ client, path }: { client: CoreClient; path: string }) {
  const [content, setContent] = useState<FileContent | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);

  useEffect(() => {
    let alive = true;
    setContent(null);
    setFailure(null);
    readFile(client, path).then(
      (read) => { if (alive) setContent(read); },
      (problem: Error) => { if (alive) setFailure(problem.message || "The Core could not show this file."); },
    );
    return () => { alive = false; };
  }, [client, path]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    viewer.current = createViewer(host);
    return () => {
      viewer.current?.destroy();
      viewer.current = null;
    };
  }, []);

  useEffect(() => {
    if (content?.kind === "text") void viewer.current?.show(content.text, languageOf(path), `${path} (read-only)`);
  }, [content, path]);

  const copyPath = () => {
    void navigator.clipboard?.writeText(path).then(() => setCopied(true), () => setCopied(false));
  };
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const notice: ReactNode = failure !== null ? failure
    : content === null ? "Reading…"
    : content.kind === "refused" ? content.message
    : content.kind === "unavailable" ? reasonText(content.reason, content.size)
    : null;
  return (
    <section className="file-view" aria-label={`File ${path}`} data-testid="file-view" data-path={path}
             data-state={content?.kind ?? (failure ? "failed" : "reading")}
             data-reason={content && content.kind !== "text" ? content.reason : undefined}>
      {content !== null && <Breadcrumb content={content} onCopyPath={copyPath} copied={copied} />}
      {notice !== null && <p className="file-notice" role="status" data-testid="file-notice">{notice}</p>}
      <div ref={hostRef} className="file-code" data-testid="file-code" hidden={content?.kind !== "text"} />
    </section>
  );
}

/** The canvas: the tab strip, then the thread or the shown file. */
export function CanvasTabs({ client, tabs, thread }: { client: CoreClient | null; tabs: TabsStore; thread: ReactNode }) {
  const state = useSyncExternalStore(tabs.subscribe, tabs.get);
  const showFiles = state.open.length > 0;
  return (
    <>
      {showFiles && <TabStrip tabs={tabs} />}
      <div className="canvas-body" tabIndex={-1} hidden={state.active !== null}>{thread}</div>
      {state.active !== null && client !== null && <FileView key={state.active} client={client} path={state.active} />}
    </>
  );
}
