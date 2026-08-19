'use client';

/**
 * One place where GSAP is registered, and one shared idea of what motion is for
 * on this page.
 *
 * The rule the whole site follows: an animation has to be doing a job that the
 * static page cannot. There are exactly four here — an entrance that
 * establishes reading order, a scroll-scrubbed demonstration that explains the
 * product better than a paragraph would, figures that count up because the
 * number is the point, and hairlines that draw themselves. Everything else is
 * still.
 *
 * `gsap.matchMedia()` rather than a manual check: it takes care of reverting
 * everything if the preference changes mid-visit, which a bare
 * `matchMedia(...).matches` at setup time does not.
 */

import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(useGSAP, ScrollTrigger);

/** The house easing. One curve, used everywhere, so the page feels like one thing. */
export const EASE = 'power3.out';
export const EASE_IN_OUT = 'power2.inOut';

/**
 * Reveal a group of elements as they enter, once.
 *
 * A short travel and a fast fade — 14 pixels, not 60. Large entrance movement
 * reads as a template; the amount here is just enough to signal that something
 * arrived without making the reader wait for it.
 */
export function revealOnEnter(
  targets: gsap.DOMTarget,
  options: { stagger?: number; y?: number; start?: string; delay?: number } = {},
) {
  const { stagger = 0.06, y = 14, start = 'top 88%', delay = 0 } = options;

  return gsap.from(targets, {
    opacity: 0,
    y,
    duration: 0.7,
    delay,
    ease: EASE,
    stagger,
    scrollTrigger: { trigger: targets as gsap.DOMTarget, start, once: true },
  });
}

/** A hairline drawing itself from the left as its section arrives. */
export function drawRule(rule: gsap.DOMTarget) {
  return gsap.from(rule, {
    scaleX: 0,
    duration: 1.1,
    ease: EASE,
    scrollTrigger: { trigger: rule as gsap.DOMTarget, start: 'top 92%', once: true },
  });
}

/**
 * Count a figure up to its value.
 *
 * Only used where the number *is* the claim — 0.38 ms, 20,000 lessons. The
 * text content is the final value in the markup, so a reader without
 * JavaScript, or with motion turned off, sees the right number rather than a
 * zero that never moves.
 */
export function countUp(element: HTMLElement, options: { decimals?: number } = {}) {
  const { decimals = 0 } = options;
  const target = parseFloat(element.dataset.value ?? element.textContent ?? '0');
  if (!Number.isFinite(target)) return;

  const state = { value: 0 };
  return gsap.to(state, {
    value: target,
    duration: 1.4,
    ease: EASE,
    onUpdate: () => {
      element.textContent = state.value.toFixed(decimals);
    },
    scrollTrigger: { trigger: element, start: 'top 88%', once: true },
  });
}

export { gsap, ScrollTrigger, useGSAP };
