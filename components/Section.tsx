'use client';

import { useRef, type ReactNode } from 'react';
import { drawRule, gsap, revealOnEnter, useGSAP } from './motion';

/**
 * A numbered section with a hairline across the top.
 *
 * The rule is the only thing that animates by default, and it animates by
 * drawing itself — the quietest entrance available, and the one that reads as
 * typesetting rather than as a web page performing. Content inside can opt into
 * a reveal by carrying `data-reveal`; most of it does not need to.
 */
export function Section({
  id,
  number,
  children,
  className = '',
}: {
  id: string;
  number: string;
  children: ReactNode;
  className?: string;
}) {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const media = gsap.matchMedia();

      media.add('(prefers-reduced-motion: no-preference)', () => {
        drawRule('.head__rule');
        const revealed = gsap.utils.toArray<HTMLElement>('[data-reveal]');
        if (revealed.length) revealOnEnter(revealed, { stagger: 0.07 });
      });
    },
    { scope: root },
  );

  return (
    <section id={id} className={className} ref={root}>
      <div className="wrap">
        <div className="head">
          <span className="head__num">{number}</span>
          <span className="head__rule" aria-hidden="true" />
        </div>
        {children}
      </div>
    </section>
  );
}
