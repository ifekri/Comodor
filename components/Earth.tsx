'use client';

import { useEffect, useRef } from 'react';

/**
 * The hero figure: the supplied artwork, unaltered.
 *
 * `public/earth.svg` is byte-for-byte what was handed over — 468 paths and 698
 * SMIL animations, md5 b39560c3 — and nothing here edits it. It is fetched and
 * placed into the document rather than pointed at with an `<img>`, because an
 * `<img>` seals a drawing inside its own document where no stylesheet can
 * reach it. Inside the page it is ordinary markup, and the recolouring is a
 * few CSS rules matching the two greens the file already carries. See `.earth`
 * in components.css.
 *
 * **Why it is fetched rather than inlined at build time.** Inlining was tried
 * and measured. App Router carries the rendered server tree in the flight
 * payload as well as in the HTML, so the page shipped the drawing twice — 1.0
 * MB of markup. That is nearly free under Brotli, where the second copy is one
 * back-reference, and it is not free at all under gzip, whose window is 32 KB
 * and cannot see back across half a megabyte to find the first copy. GitHub
 * Pages serves gzip and does not serve Brotli. Measured on the live site:
 *
 *     inlined      168 KB on the wire, one request
 *     fetched       41 KB of HTML, plus 74 KB of artwork
 *
 * Fetching also gives the artwork its own cache entry, and lets the sentence
 * and the install command paint without waiting for it.
 *
 * The fetch is started by a `<link rel="preload">` in the document head, so it
 * is in flight long before this effect runs.
 */

const source = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/earth.svg`;

export function Earth() {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = host.current;
    if (!node || node.firstChild) return undefined;

    const abort = new AbortController();

    fetch(source, { signal: abort.signal })
      .then((response) => (response.ok ? response.text() : Promise.reject(response.status)))
      .then((markup) => {
        node.innerHTML = markup;

        // The drawing animates itself, in SMIL, which no media query can
        // reach and no stylesheet can switch off. `pauseAnimations` is the
        // only lever the DOM offers, and honouring the preference matters
        // more here than anywhere else on this page: 698 simultaneous
        // animations is exactly what the setting exists to stop.
        const drawing = node.firstElementChild;
        if (
          drawing instanceof SVGSVGElement &&
          window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ) {
          drawing.pauseAnimations();
        }
      })
      // A hero illustration that fails to arrive leaves a gap. Nothing else on
      // the page depends on it, and an error in the console helps nobody.
      .catch(() => {});

    return () => abort.abort();
  }, []);

  return (
    <div
      ref={host}
      className="earth"
      role="img"
      aria-label="A globe drawn as a network of connected points"
    />
  );
}
