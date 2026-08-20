'use client';

import { useEffect, useRef, useState } from 'react';
import { detectOs } from '@/lib/detect-os';
import { installTargets, type InstallId } from '@/lib/site.config';
import { CopyButton } from './CopyButton';

/**
 * The command this page exists to deliver.
 *
 * One box, several sources. The automatic installers come first and one of
 * them is selected on arrival, because they are what works on a machine nobody
 * has prepared — they find or fetch a Python, build an isolated environment,
 * and put the command on PATH. The package managers sit after a divider, for
 * anyone who already has one and would rather use it.
 *
 * Every command is in the markup from the first byte; detection only decides
 * which one opens. That ordering matters more than it looks — a client-only
 * version would show a visitor with JavaScript disabled, or one behind a
 * stripped user agent, an empty box where the install command should be. Here
 * the worst case is having to click one label.
 */
export function InstallCommand() {
  const [selected, setSelected] = useState<InstallId>('macos');
  const [detected, setDetected] = useState<InstallId | null>(null);
  const [clipped, setClipped] = useState(false);
  const text = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const os = detectOs();
    if (os) {
      setDetected(os);
      setSelected(os);
    }
  }, []);

  const active =
    installTargets.find((target) => target.id === selected) ?? installTargets[0];

  /*
   * Does the command actually run past the end of the box?
   *
   * The fading right edge is the honest way to show that a clipped command
   * continues, but it was applied unconditionally, so a command that fitted
   * perfectly well still had its last two characters ghosted — `| sh` read as
   * though something had been cut off when nothing had. It is measured now:
   * the fade appears only when there is something behind it. Fonts settle
   * after first paint and change the answer, hence the second measurement.
   */
  useEffect(() => {
    const node = text.current;
    if (!node) return undefined;

    const measure = () => setClipped(node.scrollWidth - node.clientWidth > 1);
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(node);
    document.fonts?.ready.then(measure).catch(() => {});

    return () => observer.disconnect();
  }, [active.command]);
  const auto = installTargets.filter((target) => target.kind === 'auto');
  const manual = installTargets.filter((target) => target.kind === 'manual');

  const tab = (target: (typeof installTargets)[number]) => (
    <button
      key={target.id}
      role="tab"
      type="button"
      id={`tab-${target.id}`}
      aria-selected={target.id === selected}
      aria-controls="install-panel"
      className="install__tab"
      data-active={target.id === selected}
      data-kind={target.kind}
      onClick={() => setSelected(target.id)}
    >
      {target.label}
      {detected === target.id ? (
        <span className="install__badge" title="Detected from your browser">
          yours
        </span>
      ) : null}
    </button>
  );

  return (
    <div className="install">
      <div className="install__tabs" role="tablist" aria-label="How to install">
        {auto.map(tab)}
        {/* Not decoration: it is the line between "this will sort everything
            out for you" and "you already have the tools". */}
        <span className="install__divider" aria-hidden="true" />
        {manual.map(tab)}
      </div>

      <div
        className="install__command"
        role="tabpanel"
        id="install-panel"
        aria-labelledby={`tab-${active.id}`}
      >
        <code>
          <span className="install__prompt" aria-hidden="true">
            {active.shell}
          </span>
          <span className="install__text" ref={text} data-clipped={clipped}>
            {active.command}
          </span>
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
