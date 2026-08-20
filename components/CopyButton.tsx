'use client';

import { useEffect, useRef, useState } from 'react';

interface CopyButtonProps {
  value: string;
  label?: string;
}

/** Every label this button can show, so the widest can be reserved. */
const LABELS = { idle: 'copy', copied: 'copied', failed: 'failed' } as const;

/**
 * Copy to clipboard, at a size that never changes.
 *
 * The fixed width is not tidiness. The label used to run `copy` → `copied` →
 * `press ⌘C`, which grew the button by fifteen pixels the instant it was
 * clicked; that squeezed the command beside it and pushed it onto a second
 * line, so pressing copy visibly rearranged the page. A hidden sizer holding
 * the longest label reserves the space up front, and every state now fits the
 * box that was already there.
 *
 * All three labels are the same short length for the same reason: whatever is
 * reserved is width taken away from the command, which is the thing people
 * actually came for.
 *
 * The Clipboard API needs a secure context and can be refused outright, so the
 * failure is announced rather than mimed — a button that silently does nothing
 * is the worst outcome on a page whose whole job is handing over a command.
 */
export function CopyButton({ value, label = LABELS.idle }: CopyButtonProps) {
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
    timer.current = setTimeout(() => setState('idle'), 2200);
  }

  const shown =
    state === 'copied' ? LABELS.copied
      : state === 'failed' ? LABELS.failed
        : label;

  // The longest of everything this button can display, including the caller's
  // own label — so a longer one passed in still cannot make it jump.
  const widest = [label, LABELS.copied, LABELS.failed]
    .reduce((a, b) => (b.length > a.length ? b : a));

  return (
    <button
      type="button"
      className="copy"
      onClick={copy}
      data-state={state}
      aria-label={`Copy command: ${value}`}
      title={state === 'failed'
        ? 'Copying was blocked — select the command and copy it'
        : `Copy: ${value}`}
    >
      <span className="copy__slot" aria-hidden="true">
        <span className="copy__sizer">{widest}</span>
        <span className="copy__text">{shown}</span>
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
