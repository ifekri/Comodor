'use client';

import { useEffect, useState } from 'react';
import { detectOs } from '@/lib/detect-os';
import { installTargets, type OsId } from '@/lib/site.config';
import { CopyButton } from './CopyButton';

/**
 * The command this page exists to deliver.
 *
 * Every platform's command is in the markup from the first byte; detection
 * only decides which tab opens. That ordering matters more than it looks — a
 * client-side-only version would show a visitor with JavaScript disabled, or
 * one behind a stripped user agent, an empty box where the install command
 * should be. Here the worst case is having to click one tab.
 */
export function InstallCommand() {
  const [selected, setSelected] = useState<OsId>('macos');
  const [detected, setDetected] = useState<OsId | null>(null);

  useEffect(() => {
    const os = detectOs();
    if (os) {
      setDetected(os);
      setSelected(os);
    }
  }, []);

  const active = installTargets.find((target) => target.id === selected)!;

  return (
    <div className="install">
      <div className="install__tabs" role="tablist" aria-label="Operating system">
        {installTargets.map((target) => (
          <button
            key={target.id}
            role="tab"
            type="button"
            id={`tab-${target.id}`}
            aria-selected={target.id === selected}
            aria-controls={`panel-${target.id}`}
            className="install__tab"
            data-active={target.id === selected}
            onClick={() => setSelected(target.id)}
          >
            {target.label}
            {detected === target.id ? (
              <span className="install__badge" title="Detected from your browser">
                yours
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <div
        className="install__command"
        role="tabpanel"
        id={`panel-${active.id}`}
        aria-labelledby={`tab-${active.id}`}
      >
        <code>
          <span className="install__prompt" aria-hidden="true">
            {active.shell}
          </span>
          <span className="install__text">{active.command}</span>
        </code>
        <CopyButton value={active.command} />
      </div>

      <p className="install__note">{active.note}</p>

      {/*
        The tabs above are interactive; this list is the same content in a form
        that survives with scripting off, and it is hidden from assistive tech
        when the tabs are working so nothing is announced twice.
      */}
      <noscript>
        <ul className="install__fallback">
          {installTargets.map((target) => (
            <li key={target.id}>
              <strong>{target.label}</strong>
              <code>{target.command}</code>
            </li>
          ))}
        </ul>
      </noscript>
    </div>
  );
}
