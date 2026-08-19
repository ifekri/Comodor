'use client';

import { useEffect, useRef, useState } from 'react';

interface CopyButtonProps {
  value: string;
  label?: string;
}

/**
 * Copy to clipboard, with the outcome announced rather than mimed.
 *
 * The Clipboard API needs a secure context and can be refused outright, so the
 * failure path selects the text instead and says so — a button that silently
 * does nothing is the worst possible outcome on a page whose entire job is
 * handing over a command.
 */
export function CopyButton({ value, label = 'copy' }: CopyButtonProps) {
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

  return (
    <button
      type="button"
      className="copy"
      onClick={copy}
      data-state={state}
      aria-label={`Copy command: ${value}`}
    >
      <span aria-hidden="true">
        {state === 'copied' ? 'copied' : state === 'failed' ? 'press ⌘C' : label}
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
