'use client';

import { useRef } from 'react';
import { EASE_IN_OUT, gsap, useGSAP } from './motion';

/**
 * The one place on this page that earns a pinned, scroll-scrubbed animation.
 *
 * Reflex is a loop in time: the agent writes something, you change it, the next
 * answer is different. Prose has to describe that sequentially and the reader
 * has to assemble it. Scrubbing hands them the timeline — they scroll forward
 * and the correction happens, they scroll back and it un-happens. Nobody has to
 * be told what "learns from your corrections" means after operating it once.
 *
 * It is scrubbed rather than played because a played animation is a video: it
 * runs at its own pace and you watch. Scrubbed, the reader sets the pace, can
 * stop on the beat they did not follow, and can go back. That difference is the
 * entire justification for pinning a screen's worth of scroll.
 *
 * With reduced motion the pin never exists: the three beats stack as three
 * captioned figures, which is the same information without the mechanism.
 */

const BEATS = [
  {
    n: '01',
    title: 'It writes',
    body: 'Double quotes, because that is what the model produces by default.',
  },
  {
    n: '02',
    title: 'You correct it',
    body: 'You change them by hand. You do not explain, or teach, or configure.',
  },
  {
    n: '03',
    title: 'It reads the diff',
    body: 'A rule, with the evidence attached — and it is announced, not silent.',
  },
];

export function ReflexScroll() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const media = gsap.matchMedia();

      media.add('(prefers-reduced-motion: no-preference)', () => {
        // The dim state belongs here, not in the markup. When it was an inline
        // style, a reader with motion disabled got beats two and three greyed
        // out permanently — the timeline that was supposed to light them never
        // ran. Set from inside the motion branch, the still version is simply
        // three equal, fully legible steps.
        gsap.set('.reflex__step:not([data-step="1"])', { opacity: 0.25 });

        const timeline = gsap.timeline({
          defaults: { ease: EASE_IN_OUT, duration: 1 },
          scrollTrigger: {
            trigger: '.reflex__stage',
            start: 'top top',
            end: '+=2600',
            pin: true,
            // A little catch-up, so a trackpad flick does not snap through a
            // beat before the eye lands on it.
            scrub: 0.8,
          },
        });

        // Beat 1 -> 2: the quotes the user changed, changing.
        timeline
          .to('.reflex__step[data-step="1"]', { opacity: 0.25, duration: 0.5 })
          .to('.reflex__step[data-step="2"]', { opacity: 1, duration: 0.5 }, '<')
          .to('.reflex__quote', { color: 'var(--term-ember)' }, '<')
          .to('.reflex__double', { opacity: 0, yPercent: -60, duration: 0.6 }, '<')
          .from(
            '.reflex__single',
            { opacity: 0, yPercent: 60, duration: 0.6 },
            '<',
          )
          .to('.reflex__cursor', { opacity: 1, duration: 0.2 }, '<')

          // Beat 2 -> 3: the rule appears, with its evidence.
          .to('.reflex__step[data-step="2"]', { opacity: 0.25, duration: 0.5 })
          .to('.reflex__step[data-step="3"]', { opacity: 1, duration: 0.5 }, '<')
          .to('.reflex__cursor', { opacity: 0, duration: 0.2 }, '<')
          .from(
            '.reflex__learned',
            { opacity: 0, y: 16, duration: 0.7 },
            '<+=0.1',
          )
          .from(
            '.reflex__evidence',
            { opacity: 0, y: 10, duration: 0.6 },
            '<+=0.2',
          )
          .from(
            '.reflex__next',
            { opacity: 0, y: 12, duration: 0.7 },
            '<+=0.15',
          );
      });
    },
    { scope: root },
  );

  return (
    <div className="reflex" ref={root}>
      <div className="reflex__stage">
        <div className="wrap reflex__inner">
          <ol className="reflex__steps">
            {BEATS.map((beat, index) => (
              <li
                key={beat.n}
                className="reflex__step"
                data-step={index + 1}
              >
                <span className="reflex__n">{beat.n}</span>
                <h3>{beat.title}</h3>
                <p>{beat.body}</p>
              </li>
            ))}
          </ol>

          <div className="reflex__screen">
            <div className="term term--tall">
              <div className="term__bar" aria-hidden="true">
                <span className="term__dot" />
                <span className="term__dot" />
                <span className="term__dot" />
                <span className="term__title">src/defaults.py</span>
              </div>

              <div className="term__body reflex__code">
                <p className="term__row">
                  <span className="term__gut">1</span>
                  <span>
                    <span className="reflex__key">TIMEOUT</span> ={' '}
                    <span className="reflex__quote">
                      <span className="reflex__double">&quot;30s&quot;</span>
                      <span className="reflex__single">&apos;30s&apos;</span>
                    </span>
                    <span className="reflex__cursor" aria-hidden="true" />
                  </span>
                </p>
                <p className="term__row">
                  <span className="term__gut">2</span>
                  <span>
                    <span className="reflex__key">RETRIES</span> ={' '}
                    <span className="reflex__num">3</span>
                  </span>
                </p>
                <p className="term__row">
                  <span className="term__gut">3</span>
                  <span>
                    <span className="reflex__key">BACKOFF</span> ={' '}
                    <span className="reflex__num">1.5</span>
                  </span>
                </p>
                <p className="term__row">
                  <span className="term__gut">4</span>
                  <span />
                </p>
                <p className="term__row">
                  <span className="term__gut">5</span>
                  <span className="term__dim"># connection</span>
                </p>
                <p className="term__row">
                  <span className="term__gut">6</span>
                  <span>
                    <span className="reflex__key">POOL_SIZE</span> ={' '}
                    <span className="reflex__num">12</span>
                  </span>
                </p>

                <div className="reflex__learned">
                  <span className="term__prompt">◈</span>
                  <span>
                    learned:{' '}
                    <strong>Use single quotes for string literals.</strong>
                  </span>
                </div>
                <p className="reflex__evidence">
                  31 of 34 literals · from an edit you made ·{' '}
                  <span className="term__dim">/rules forget 1 to undo</span>
                </p>

                <p className="reflex__next">
                  <span className="term__prompt">›</span>
                  <span>
                    add the retry backoff →{' '}
                    <span className="reflex__now">&apos;exponential&apos;</span>
                  </span>
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
