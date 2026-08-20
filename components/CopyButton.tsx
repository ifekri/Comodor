'use client';

import { useEffect, useRef, useState } from 'react';

interface CopyButtonProps {
  value: string;
}

/**
 * Copy to clipboard.
 *
 * An icon, not a word. The label used to run `copy` → `copied` → `press ⌘C`,
 * and each of those is a different width — so the button changed size the
 * instant it was clicked, squeezed the command beside it, and visibly
 * rearranged the page. Two glyphs in a fixed box cannot do that, whatever
 * state it is in or whatever language the page is read in.
 *
 * The word is still there for anyone who cannot see the icon: `aria-label`
 * names the action and the command, and a live region announces the result.
 * The Clipboard API needs a secure context and can be refused outright, so the
 * failure is announced rather than mimed — a button that silently does nothing
 * is the worst outcome on a page whose whole job is handing over a command.
 */
export function CopyButton({ value }: CopyButtonProps) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState('copied');
    } catch {
      setState('failed');
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState('idle'), 2000);
  }

  return (
    <button
      type="button"
      className="copy"
      onClick={copy}
      data-state={state}
      aria-label={`Copy command: ${value}`}
      title={
        state === 'copied' ? 'Copied'
          : state === 'failed' ? 'Copying was blocked — select the command and copy it'
            : 'Copy'
      }
    >
      {/* Both glyphs occupy the same cell, so the tick replaces the sheets
          without the box resizing by a single pixel. */}
      <span className="copy__slot" aria-hidden="true">
        <span className="copy__icon" data-show={state === 'idle'}>
          <Sheets />
        </span>
        <span className="copy__icon" data-show={state === 'copied'}>
          <Tick />
        </span>
        <span className="copy__icon" data-show={state === 'failed'}>
          <Warn />
        </span>
      </span>
      <span role="status" aria-live="polite" className="sr-only">
        {state === 'copied'
          ? 'Command copied to clipboard'
          : state === 'failed'
            ? 'Could not copy automatically. Select the command and copy it.'
            : ''}
      </span>
    </button>
  );
}

/*
 * Drawn at the same hairline weight as the rules on the page. An icon set's
 * default stroke would be the heaviest mark in a very quiet layout.
 */

function Sheets() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.15" strokeLinejoin="round">
      <rect x="5.6" y="5.6" width="8" height="8" rx="1.2" />
      <path d="M10.4 5.6V3.6a1.2 1.2 0 0 0-1.2-1.2H3.6a1.2 1.2 0 0 0-1.2 1.2v5.6a1.2 1.2 0 0 0 1.2 1.2h2" />
    </svg>
  );
}

function Tick() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
         strokeLinejoin="round">
      <path d="M3 8.4 6.4 11.8 13 5.2" />
    </svg>
  );
}

function Warn() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
      <circle cx="8" cy="8" r="5.6" />
      <path d="M8 5.2v3.4M8 10.9v.1" />
    </svg>
  );
}
