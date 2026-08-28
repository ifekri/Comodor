/**
 * The checks that matter more than the screenshots.
 *
 * A scroll-scrubbed pin is the animation most likely to hide content from
 * somebody who never sees it run, so the first and most important test here is
 * the page with motion turned off: everything the timelines touch must be
 * fully opaque and in place. The rest is the ordinary floor — headings in
 * order, images described, the install command present without JavaScript.
 */

import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.argv[2] || 'http://localhost:3300';
let failures = 0;

function check(ok, label, detail = '') {
  if (ok) {
    console.log(`  ok    ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

const browser = await chromium.launch();

// ------------------------------------------------------------ reduced motion
console.log('\nprefers-reduced-motion: reduce');
{
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    reducedMotion: 'reduce',
  });
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1500);

  const hidden = await page.evaluate(() => {
    const selectors = [
      '.hero__lede', '.hero__install', '.hero__meta', '.hero__row',
      '.reflex__learned', '.reflex__evidence', '.reflex__next',
      '.reflex__step', '.figure', '.signal', '.card', '.note',
      '[data-reveal]',
    ];
    const faint = [];
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        const style = getComputedStyle(element);
        if (parseFloat(style.opacity) < 0.9) {
          faint.push(`${selector} @ ${style.opacity}`);
        }
      }
    }
    return faint;
  });
  check(hidden.length === 0, 'nothing is left faded', hidden.slice(0, 4).join('; '));

  const pinned = await page.evaluate(
    () => document.querySelectorAll('.pin-spacer').length,
  );
  check(pinned === 0, 'no pinning is created');

  // The whole point: the install command has to be reachable and readable.
  const command = await page.textContent('.install__command code');
  check(Boolean(command && command.includes('comodor.ai')),
    'the install command is present', command || 'missing');

  await page.close();
}

// ------------------------------------------------------------- no JavaScript
console.log('\nJavaScript disabled');
{
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: 'domcontentloaded' });

  const text = await page.textContent('body');
  // Read from the config rather than written out here. The install address has
  // changed twice, and both times this line kept asserting the old one — it
  // was looking for `irm https://` long after the page settled on the shorter
  // `irm get.comodor.ai`, and reported a missing command that was on screen.
  const installUrl = (await readFile(
    new URL('../lib/site.config.ts', import.meta.url), 'utf8'))
    .match(/installUrl:\s*'([^']+)'/)?.[1] ?? 'get.comodor.ai';
  check(text.includes('curl -fsSL'), 'a macOS/Linux command is in the markup');
  check(text.includes(`irm ${installUrl}`),
        `the Windows command is in the markup (irm ${installUrl})`);
  check(text.includes('It learns the way'), 'the headline is in the markup');
  check(text.includes('Filesystem'), 'later sections are in the markup');

  await context.close();
}

// -------------------------------------------------------------------- markup
console.log('\nStructure');
{
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(base, { waitUntil: 'networkidle' });

  const headings = await page.evaluate(() =>
    [...document.querySelectorAll('h1, h2, h3')].map((h) => Number(h.tagName[1])),
  );
  check(headings.filter((level) => level === 1).length === 1,
    'exactly one h1', `found ${headings.filter((l) => l === 1).length}`);

  let skipped = '';
  for (let i = 1; i < headings.length; i += 1) {
    if (headings[i] - headings[i - 1] > 1) {
      skipped = `h${headings[i - 1]} → h${headings[i]}`;
      break;
    }
  }
  check(!skipped, 'no heading level is skipped', skipped);

  const unnamed = await page.evaluate(
    () => [...document.querySelectorAll('button')]
      .filter((b) => !b.textContent.trim() && !b.getAttribute('aria-label')).length,
  );
  check(unnamed === 0, 'every button has an accessible name');

  const noAlt = await page.evaluate(
    () => [...document.querySelectorAll('img')].filter((i) => !i.hasAttribute('alt')).length,
  );
  check(noAlt === 0, 'every image has alt text');

  const lang = await page.getAttribute('html', 'lang');
  check(lang === 'en', 'the document declares its language');

  // Horizontal overflow is the defect a phone shows and a desktop hides.
  for (const width of [360, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(350);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    check(overflow <= 1, `no sideways scrolling at ${width}px`, `${overflow}px over`);
  }

  await page.close();
}

await browser.close();

console.log(failures ? `\n${failures} failed\n` : '\nall passed\n');
process.exit(failures ? 1 : 0);
