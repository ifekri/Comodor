'use client';

import { useRef } from 'react';
import { countUp, gsap, useGSAP } from './motion';

/**
 * The performance figures.
 *
 * These count up, and the reason is not decoration: the claim *is* that the
 * number does not change between three thousand lessons and twenty thousand.
 * Two figures arriving at the same value, side by side, makes that point
 * faster than the sentence underneath does.
 *
 * The final values are in the markup. Reduced motion, or no JavaScript at all,
 * shows the right numbers immediately — a counter that starts at zero and
 * depends on script to become true would be a lie in the failure case.
 */

const ROWS = [
  { label: 'Recall, 3,000 lessons', value: 0.38, decimals: 2, unit: 'ms' },
  { label: 'Recall, 20,000 lessons', value: 0.38, decimals: 2, unit: 'ms', flat: true },
  { label: 'Deduplication', value: 0.25, decimals: 2, unit: 'ms' },
  { label: 'Pinned-rule lookup', value: 0.1, decimals: 2, unit: 'ms' },
  { label: 'Recording reinforcement', value: 0.001, decimals: 3, unit: 'ms' },
];

export function Figures() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const media = gsap.matchMedia();

      media.add('(prefers-reduced-motion: no-preference)', () => {
        gsap.utils.toArray<HTMLElement>('.figure__value').forEach((element) => {
          countUp(element, { decimals: Number(element.dataset.decimals ?? 0) });
        });
        gsap.from('.figure', {
          opacity: 0,
          y: 12,
          duration: 0.7,
          stagger: 0.07,
          ease: 'power3.out',
          scrollTrigger: { trigger: root.current, start: 'top 80%', once: true },
        });
      });
    },
    { scope: root },
  );

  return (
    <div className="figures" ref={root}>
      {ROWS.map((row) => (
        <div className="figure" key={row.label}>
          <span className="figure__label">{row.label}</span>
          <span className="figure__reading">
            <span
              className="figure__value tabular"
              data-value={row.value}
              data-decimals={row.decimals}
            >
              {row.value.toFixed(row.decimals)}
            </span>
            <span className="figure__unit">{row.unit}</span>
            {row.flat ? <span className="figure__flat">flat</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}
