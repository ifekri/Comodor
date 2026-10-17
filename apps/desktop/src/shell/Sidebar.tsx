/**
 * The left sidebar of the reference window (spec Clarifications,
 * 2026-10-17): its toolbar, its WORKSPACE and EXPLORER tabs, and the
 * SESSION, AGENTS and TASKS sections. Everything listed is what the Core
 * reported for the open session — the session itself, its background
 * delegates, its task list — read-only; with nothing reported a section says
 * so. Later-phase controls keep the reference's place and say they arrive
 * later. Nothing is invented.
 */

import type { Delegate, Task } from "@comodor/session";
import { type ReactNode, useState } from "react";

import { InertText } from "../view/InertText.tsx";
import { LaterButton } from "./Later.tsx";
import type { SharedSession } from "./session-store.ts";

const TASK_ICONS: Readonly<Record<Task["state"], string>> = {
  done: "check_box", active: "indeterminate_check_box", pending: "check_box_outline_blank", blocked: "disabled_by_default",
};

const LIVE: ReadonlySet<Delegate["state"]> = new Set(["running", "stopping"]);

function Section({ label, count, open, onToggle, actions, children }: {
  label: string;
  count: string;
  open: boolean;
  onToggle: () => void;
  actions: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={open ? "side-section open" : "side-section"} aria-label={label}>
      <div className="side-section-head">
        <button type="button" className="side-section-toggle" aria-expanded={open} onClick={onToggle}>
          <span className="icon side-chevron" data-icon="expand_more" aria-hidden="true" />
          <span className="side-section-label">{label.toUpperCase()}</span>
          <span className="side-count">{count}</span>
        </button>
        <span className="side-section-actions">{actions}</span>
      </div>
      {open && <div className="side-section-body">{children}</div>}
    </section>
  );
}

export function Sidebar({ session, workspace, mode, canChangeWorkspace, onChangeWorkspace, onShowConversation }: {
  session: SharedSession | null;
  /** The workspace as reported (the Core's, else the native side's); null when there is none. */
  workspace: string | null;
  mode: "beside" | "covering";
  canChangeWorkspace: boolean;
  onChangeWorkspace: () => void;
  onShowConversation: () => void;
}) {
  const [tab, setTab] = useState<"workspace" | "explorer">("workspace");
  const [open, setOpen] = useState({ session: true, agents: true, tasks: true });
  const toggle = (key: keyof typeof open) => () => setOpen((now) => ({ ...now, [key]: !now[key] }));
  const shown = session?.shown === true;
  const delegates = session?.delegates ?? [];
  const tasks = session?.tasks ?? [];
  const folder = workspace?.split(/[\\/]/).filter(Boolean).at(-1) ?? null;

  return (
    <nav className={`sidebar sidebar-${mode}`} aria-label="Workbench" data-testid="sidebar">
      <div className="side-toolbar">
        <LaterButton label="New file" icon="note_add" className="side-tool" />
        <button type="button" className="side-tool" aria-label="Open folder" title="Open folder (change workspace)"
                disabled={!canChangeWorkspace} onClick={onChangeWorkspace}>
          <span className="icon" data-icon="create_new_folder" aria-hidden="true" />
        </button>
        <LaterButton label="New agent" icon="smart_toy" className="side-tool" />
        <LaterButton label="Sync workspace" icon="sync" className="side-tool" />
        <LaterButton label="Settings" icon="settings" className="side-tool" />
        <span className="side-spacer" />
        <LaterButton label="Sidebar options" icon="more_vert" className="side-tool" />
      </div>
      <div className="side-tabs" role="tablist" aria-label="Sidebar">
        {(["workspace", "explorer"] as const).map((name) => (
          <button key={name} type="button" role="tab" aria-selected={tab === name} className="side-tab"
                  onClick={() => setTab(name)}>
            <span className="icon" data-icon={name === "workspace" ? "dashboard" : "folder_open"} aria-hidden="true" />
            <span>{name.toUpperCase()}</span>
          </button>
        ))}
      </div>
      {tab === "workspace" ? (
        <div className="side-sections" role="tabpanel" aria-label="Workspace">
          <Section label="Session" count={shown ? "1" : "0"} open={open.session} onToggle={toggle("session")}
                   actions={<>
                     <LaterButton label="Filter sessions" icon="search" className="side-mini" />
                     <LaterButton label="New session" icon="add" className="side-mini" />
                   </>}>
            {shown ? (
              <div className="side-row active" title={session?.sessionId ? `Session ${session.sessionId}` : undefined}>
                <button type="button" className="side-row-open" onClick={onShowConversation}>
                  <span className="icon" data-icon="subdirectory_arrow_right" aria-hidden="true" />
                  <span className="side-row-title" dir="auto">
                    {session?.firstMessage ? <InertText text={session.firstMessage} linked={false} /> : "This session"}
                  </span>
                </button>
                <LaterButton label="Fork session" icon="account_tree" className="side-mini" />
                <LaterButton label="Reveal in workspace" icon="folder_open" className="side-mini" />
              </div>
            ) : (
              <p className="side-empty">No session is open.</p>
            )}
          </Section>
          <div className="side-split" aria-hidden="true" />
          <Section label="Agents" count={`${delegates.filter((delegate) => LIVE.has(delegate.state)).length}/${delegates.length}`}
                   open={open.agents} onToggle={toggle("agents")}
                   actions={<>
                     <LaterButton label="Pause all agents" icon="pause_circle" className="side-mini" />
                     <LaterButton label="New agent" icon="add" className="side-mini" />
                   </>}>
            {delegates.length === 0 ? (
              <p className="side-empty">No agents in this session. Background delegates the Core starts appear here.</p>
            ) : delegates.map((delegate, at) => (
              <div key={delegate.id} className={LIVE.has(delegate.state) ? "agent-card" : "agent-card ended"}
                   data-delegate={delegate.id}>
                <div className="agent-head">
                  <span className="icon" data-icon="smart_toy" aria-hidden="true" />
                  <span className="agent-tag">[AGENT]</span>
                  <span className="agent-name">Delegate</span>
                  <span className="agent-num">{String(at + 1).padStart(2, "0")}</span>
                </div>
                <div className="agent-line">
                  <span className={`agent-dot agent-${delegate.state}`} aria-hidden="true" />
                  <span className="agent-task" dir="auto"><span className="agent-task-label">Task</span> : <InertText text={delegate.label} linked={false} /></span>
                  <span className={`agent-state agent-${delegate.state}`}>{delegate.state.toUpperCase()}</span>
                </div>
              </div>
            ))}
          </Section>
          <div className="side-split" aria-hidden="true" />
          <Section label="Tasks" count={`${tasks.filter((task) => task.state === "done").length}/${tasks.length}`}
                   open={open.tasks} onToggle={toggle("tasks")}
                   actions={<>
                     <LaterButton label="Hide completed tasks" icon="visibility" className="side-mini" />
                     <LaterButton label="New task" icon="add" className="side-mini" />
                   </>}>
            {tasks.length === 0 ? (
              <p className="side-empty">No tasks in this session. The Core's task list appears here.</p>
            ) : tasks.map((task, at) => (
              <div key={`${at}:${task.text}`} className={`task-row task-${task.state}`} data-task-state={task.state}>
                <span className="icon" data-icon={TASK_ICONS[task.state]} aria-hidden="true" />
                <span className="task-text" dir="auto"><InertText text={task.text} linked={false} /></span>
                <span className="task-state">{task.state}</span>
              </div>
            ))}
          </Section>
        </div>
      ) : (
        <div className="side-explorer" role="tabpanel" aria-label="Explorer">
          <div className="side-section-head">
            <span className="side-section-label" dir="auto">{(folder ?? "Workspace").toUpperCase()}</span>
          </div>
          <p className="side-empty">Browsing the workspace's files arrives in a later version.</p>
          {workspace && <p className="side-path" dir="auto"><InertText text={workspace} linked={false} /></p>}
        </div>
      )}
    </nav>
  );
}
