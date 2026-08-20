'use client';

import { EASE, gsap, useGSAP } from './motion';

/**
 * The entrance, and the one lever the artwork responds to.
 *
 * This renders nothing. The hero is markup and one large inlined drawing, none
 * of it interactive, so none of it needs to ship as a client component; the
 * only thing that has to run in the browser is the entrance, and it can run
 * from a sibling that returns null.
 *
 * Selectors are absolute rather than scoped, because there is no element here
 * to scope to. There is exactly one hero on the page.
 *
 * The entrance is a single staged timeline rather than six independent fades.
 * Order carries meaning: rule, then title, then the lede, then the install
 * command — the reason anybody is here, so it arrives early rather than last.
 * The whole thing is over in about a second. A reader's eye is led once,
 * deliberately, and then left alone.
 */
export function HeroEntrance() {
  useGSAP(() => {
    const media = gsap.matchMedia();

    media.add(
      {
        motion: '(prefers-reduced-motion: no-preference)',
        still: '(prefers-reduced-motion: reduce)',
      },
      (context) => {
        // The artwork animates itself, in SMIL, which no media query can
        // reach. `pauseAnimations` is the one lever the DOM offers, and
        // honouring the preference matters more here than anywhere else on
        // the page: 698 simultaneous animations is exactly the kind of thing
        // the setting exists to switch off.
        const drawing = document.querySelector('.earth svg');
        if (drawing instanceof SVGSVGElement) {
          if (context.conditions?.motion) drawing.unpauseAnimations();
          else drawing.pauseAnimations();
        }

        if (!context.conditions?.motion) return;

        // Brisk on purpose. An entrance is a way of establishing reading
        // order, not a performance to sit through: the whole thing is over
        // in about a second, and the install command — the reason anybody
        // is here — arrives early rather than last.
        const timeline = gsap.timeline({
          defaults: { ease: EASE, duration: 0.55 },
        });

        timeline
          .from('.hero__rule', { scaleX: 0, duration: 0.8 })
          // Each line rises from behind its own overflow clip, so the type
          // is uncovered rather than faded — closer to how a printed line
          // would be revealed.
          .from(
            '.hero__line > span',
            { yPercent: 108, duration: 0.75, stagger: 0.06 },
            '-=0.62',
          )
          .from('.hero__lede', { opacity: 0, y: 10 }, '-=0.45')
          .from('.hero__install', { opacity: 0, y: 10 }, '-=0.36')
          // The globe arrives by growing into place rather than sliding:
          // a sphere that slides reads as a disc on a track.
          .from(
            '.hero__figure',
            { opacity: 0, scale: 0.92, duration: 0.9, transformOrigin: '50% 50%' },
            '-=0.5',
          )
          .from('.hero__meta > *', { opacity: 0, stagger: 0.05 }, '-=0.6');
      },
    );
  });

  return null;
}
