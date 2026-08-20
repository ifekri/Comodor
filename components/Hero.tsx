'use client';

import { useRef } from 'react';
import { EASE, gsap, useGSAP } from './motion';
import { InstallCommand } from './InstallCommand';
import { site } from '@/lib/site.config';

/**
 * The opening.
 *
 * One idea, held for the whole viewport: the sentence, then the thing itself.
 * The terminal is set dark against the paper so it reads as a figure rather
 * than as decoration, and it carries the transcript that proves the claim in
 * the headline — the agent was corrected once and obeyed on the next turn.
 *
 * The entrance is a single staged timeline rather than six independent fades.
 * Order carries meaning: rule, then title, then the transcript filling in line
 * by line, then the install command. A reader's eye is led once, deliberately,
 * and then left alone.
 */
export function Hero() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const media = gsap.matchMedia();

      media.add(
        {
          motion: '(prefers-reduced-motion: no-preference)',
          still: '(prefers-reduced-motion: reduce)',
        },
        (context) => {
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
            .from('.hero__figure', { opacity: 0, y: 18, duration: 0.7 }, '-=0.5')
            .from(
              '.hero__row',
              { opacity: 0, x: -8, duration: 0.34, stagger: 0.05 },
              '-=0.45',
            )
            .from('.hero__meta > *', { opacity: 0, stagger: 0.05 }, '-=0.5');
        },
      );
    },
    { scope: root },
  );

  return (
    <header className="hero" ref={root} id="top">
      <div className="wrap">
        <div className="hero__rule" aria-hidden="true" />

        <div className="hero__grid">
          <div className="hero__text">
            <h1 className="hero__title">
              <span className="hero__line">
                <span>It learns the way</span>
              </span>
              <span className="hero__line">
                <span>
                  you <em>correct</em> it.
                </span>
              </span>
            </h1>

            <p className="lede hero__lede">
              A terminal coding agent that reads the edits you make to its
              output and turns them into rules — no second model call, no
              waiting, nothing to configure. Fix something once and the next
              answer already obeys.
            </p>

            <dl className="hero__meta">
              <div>
                <dt>Providers</dt>
                <dd>
                  <span className="tabular">18</span>, or your own
                </dd>
              </div>
              <div>
                <dt>Recall</dt>
                <dd>
                  <span className="tabular">0.38 ms</span>, flat
                </dd>
              </div>
              <div>
                <dt>Runs</dt>
                <dd>anywhere with a terminal</dd>
              </div>
            </dl>
          </div>

          <figure className="hero__figure">
            <div className="term">
              <div className="term__bar" aria-hidden="true">
                <span className="term__dot" />
                <span className="term__dot" />
                <span className="term__dot" />
                <span className="term__title">{site.command}</span>
              </div>

              <div className="term__body">
                <p className="hero__row term__row">
                  <span className="term__prompt">›</span>
                  <span>create defaults.py with 6 string constants</span>
                </p>
                <p className="hero__row term__row term__row--dim">
                  <span className="term__prompt">⚙</span>
                  <span>write src/defaults.py — 6 constants</span>
                </p>
                <p className="hero__row term__row term__row--gap">
                  <span className="term__prompt term__prompt--edit">✎</span>
                  <span className="term__dim">
                    you edited the file:{' '}
                    <span className="term__was">&quot;30s&quot;</span> →{' '}
                    <span className="term__now">&apos;30s&apos;</span>
                  </span>
                </p>
                <p className="hero__row term__row">
                  <span className="term__prompt">›</span>
                  <span>now add the timeout constants</span>
                </p>
                <p className="hero__row term__row term__row--learn">
                  <span className="term__prompt">◈</span>
                  <span>
                    learned: <strong>Use single quotes for string literals.</strong>
                  </span>
                </p>
                <p className="hero__row term__row term__row--dim">
                  <span className="term__prompt">⚙</span>
                  <span>
                    write src/defaults.py —{' '}
                    <span className="term__now">&apos;30s&apos;</span>,{' '}
                    <span className="term__now">&apos;5m&apos;</span>
                  </span>
                </p>

                <div className="term__status">
                  <span>
                    <span className="term__dim">Mode</span> Act
                  </span>
                  <span>
                    <span className="term__dim">Loop</span> On
                  </span>
                  <span>
                    <span className="term__dim">Rules</span>{' '}
                    <span className="term__amber">7</span>
                  </span>
                  <span className="term__status__right term__dim">
                    143K used · $0.041
                  </span>
                </div>
              </div>
            </div>

            <figcaption className="hero__caption">
              A real transcript. Nobody told it anything — it read the edit.
            </figcaption>
          </figure>
        </div>

        {/*
          Full width, below both columns, rather than tucked into the text.
          The command is 44 characters and the text column is barely 500px, so
          inside it the choice was a scrollbar, a second line, or type too
          small to read. Given the whole measure it is one legible line — and
          it is the most important element on the page, so the prominence is
          right anyway.
        */}
        <div className="hero__install">
          <InstallCommand />
        </div>
      </div>
    </header>
  );
}
