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
 *
 * **The animation runs only while somebody can see it.** Six hundred and
 * ninety-eight SMIL animations are a main-thread loop: measured on the live
 * site over eight idle seconds they cost 104,746 style recalculations, 1.4s of
 * style recalculation and 3.9s of total task time, against 150ms with them
 * paused. None of that is visible in a byte count or a paint timing — the page
 * still paints in under 300ms — and all of it lands on the battery of somebody
 * who has scrolled past.
 */

const source = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/earth.svg`;

export function Earth() {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = host.current;
    if (!node || node.firstChild) return undefined;

    const abort = new AbortController();
    const teardown: Array<() => void> = [() => abort.abort()];

    fetch(source, { signal: abort.signal })
      .then((response) => (response.ok ? response.text() : Promise.reject(response.status)))
      .then((markup) => {
        node.innerHTML = markup;

        const drawing = node.firstElementChild;
        if (!(drawing instanceof SVGSVGElement)) return;

        // What this costs, measured on the live site over eight seconds of an
        // idle page: 104,746 style recalculations, 1.4s of recalc and 3.9s of
        // total task time. Paused, all three are zero. Six hundred and
        // ninety-eight simultaneous SMIL animations are a main-thread loop
        // that no stylesheet can reach and no compositor can take over.
        //
        // So it runs only while somebody can actually see it. Three things
        // decide that, and all three have to be watched rather than read once
        // — a preference can change, a tab can be hidden, and the globe is
        // scrolled past within a screen or two of the top.
        const still = window.matchMedia('(prefers-reduced-motion: reduce)');
        let onScreen = true;

        const settle = () => {
          const wanted = onScreen && !document.hidden && !still.matches;
          // `animationsPaused()` is not universally implemented, so the calls
          // are made unconditionally; both are idempotent.
          if (wanted) drawing.unpauseAnimations();
          else drawing.pauseAnimations();
        };

        if ('IntersectionObserver' in window) {
          const watcher = new IntersectionObserver(
            (entries) => {
              onScreen = entries.some((entry) => entry.isIntersecting);
              settle();
            },
            // A little early, so it is already moving by the time it is in
            // view rather than starting as somebody looks at it.
            { rootMargin: '200px' },
          );
          watcher.observe(node);
          teardown.push(() => watcher.disconnect());
        }

        document.addEventListener('visibilitychange', settle);
        teardown.push(() => document.removeEventListener('visibilitychange', settle));

        // Safari before 14 has `addListener` and not `addEventListener` here.
        if (still.addEventListener) {
          still.addEventListener('change', settle);
          teardown.push(() => still.removeEventListener('change', settle));
        }

        settle();
      })
      // A hero illustration that fails to arrive leaves a gap. Nothing else on
      // the page depends on it, and an error in the console helps nobody.
      .catch(() => {});

    return () => teardown.forEach((undo) => undo());
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
