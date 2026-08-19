'use client';

import { useEffect, useState } from 'react';

/**
 * Light and dark.
 *
 * Three things this has to get right, in order of how badly they hurt when
 * they are wrong:
 *
 * **No flash.** The stored choice is applied by a blocking script in `<head>`
 * before the first paint (see `layout.tsx`). React cannot do that job — by the
 * time a component mounts the wrong theme has already been on screen for a
 * frame, and on a page this dark or this pale, one frame is very visible. This
 * component only *reflects* what that script already decided.
 *
 * **A default that is not a guess.** Until somebody chooses, the system
 * preference wins and nothing is stored. Writing a choice on first visit would
 * mean a reader who later changes their OS setting is stuck with whatever they
 * happened to have in January.
 *
 * **Honest labelling.** The button says what it will do, not what is currently
 * true, and `aria-pressed` is deliberately not used: this is not a thing that
 * is on or off, it is a switch between two named states.
 */

type Theme = 'light' | 'dark';

const STORAGE_KEY = 'comodor-theme';

export function ThemeToggle() {
  // Rendered as null until mounted. The server has no idea which theme this
  // visitor gets, so rendering a guess here is a hydration mismatch and a
  // visible flicker of the wrong icon.
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const current = document.documentElement.dataset.theme;
    setTheme(current === 'dark' ? 'dark' : 'light');

    // Somebody who has never chosen should keep following their system. Once
    // they have, this listener stops applying.
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const follow = (event: MediaQueryListEvent) => {
      if (localStorage.getItem(STORAGE_KEY)) return;
      const next: Theme = event.matches ? 'dark' : 'light';
      apply(next);
      setTheme(next);
    };

    media.addEventListener('change', follow);
    return () => media.removeEventListener('change', follow);
  }, []);

  function apply(next: Theme) {
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
    // Browser chrome — the address bar on mobile — follows the page rather
    // than staying whatever the server said.
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', next === 'dark' ? '#13110d' : '#faf8f4');
  }

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    apply(next);
    setTheme(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private browsing, or storage denied. The switch still works for this
      // visit, which is the part that matters.
    }
  }

  if (theme === null) {
    // A placeholder of the right size, so the header does not reflow when the
    // real control arrives.
    return <div className="theme" aria-hidden="true" />;
  }

  const goingDark = theme === 'light';

  return (
    <button
      type="button"
      className="theme"
      onClick={toggle}
      title={goingDark ? 'Switch to dark' : 'Switch to light'}
    >
      <span className="theme__icon" aria-hidden="true">
        {goingDark ? <Moon /> : <Sun />}
      </span>
      <span className="theme__label">{goingDark ? 'Dark' : 'Light'}</span>
    </button>
  );
}

/*
 * Drawn rather than imported. Two icons is not worth a dependency, and these
 * are set to the same hairline weight as the rules on the page — a heavier
 * stroke, which is what most icon sets ship, would be the loudest thing in the
 * corner of a very quiet layout.
 */

function Sun() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1" strokeLinecap="round">
      <circle cx="8" cy="8" r="3.1" />
      <path d="M8 1.4v1.7M8 12.9v1.7M1.4 8h1.7M12.9 8h1.7
               M3.3 3.3l1.2 1.2M11.5 11.5l1.2 1.2
               M12.7 3.3l-1.2 1.2M4.5 11.5l-1.2 1.2" />
    </svg>
  );
}

function Moon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none"
         stroke="currentColor" strokeWidth="1" strokeLinecap="round"
         strokeLinejoin="round">
      <path d="M13.4 9.6A5.8 5.8 0 0 1 6.4 2.6a5.9 5.9 0 1 0 7 7Z" />
    </svg>
  );
}
