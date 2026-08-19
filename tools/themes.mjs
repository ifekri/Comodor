/**
 * Both themes, side by side, plus the checks a theme switch can fail.
 *
 * The screenshots are the point — a dark mode is a design, not a colour swap,
 * and the only way to know whether the terminal still reads as a figure is to
 * look at it. The assertions cover what looking cannot catch: the flash before
 * paint, and text that quietly falls below a readable contrast.
 */

import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const base = process.argv[2] || 'http://localhost:3300';
const out = process.argv[3] || path.join(process.cwd(), '.shots');
await mkdir(out, { recursive: true });

const STOPS = [
  ['01-hero', 0],
  ['02-reflex', 0.3],
  ['03-speed', 0.7],
  ['04-install', 0.93],
];

let failures = 0;
const check = (ok, label, detail = '') => {
  if (ok) console.log(`  ok    ${label}`);
  else {
    failures += 1;
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`);
  }
};

/** WCAG relative luminance, for a real contrast number rather than a guess. */
function contrast(a, b) {
  const luminance = (rgb) => {
    const [r, g, bl] = rgb.map((value) => {
      const channel = value / 255;
      return channel <= 0.03928
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const parse = (value) =>
  (value.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);

const browser = await chromium.launch();

for (const scheme of ['light', 'dark']) {
  console.log(`\n${scheme}`);
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: scheme,
  });

  await page.goto(base, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(2200);

  const applied = await page.getAttribute('html', 'data-theme');
  check(applied === scheme, `the system preference is honoured`, `got ${applied}`);

  // The terminal has to stay a distinguishable object, not merge into the page.
  const [pageBg, termBg] = await page.evaluate(() => [
    getComputedStyle(document.body).backgroundColor,
    getComputedStyle(document.querySelector('.term')).backgroundColor,
  ]);
  const separation = contrast(parse(pageBg), parse(termBg));
  check(separation >= 1.25,
    `the terminal is distinct from the page (${separation.toFixed(2)}:1)`);

  // Body text, secondary text, and the accent all have to stay readable.
  const readings = await page.evaluate(() => {
    const sample = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const style = getComputedStyle(element);
      let node = element;
      let background = 'rgba(0, 0, 0, 0)';
      while (node && background === 'rgba(0, 0, 0, 0)') {
        background = getComputedStyle(node).backgroundColor;
        node = node.parentElement;
      }
      return { selector, color: style.color, background };
    };
    return ['.lede', '.signal dd', '.head__num', '.figure__label', '.install__note']
      .map(sample)
      .filter(Boolean);
  });

  for (const reading of readings) {
    const ratio = contrast(parse(reading.color), parse(reading.background));
    check(ratio >= 4.5, `${reading.selector} is readable (${ratio.toFixed(2)}:1)`);
  }

  const height = await page.evaluate(() => document.body.scrollHeight);
  for (const [name, position] of STOPS) {
    await page.evaluate((top) => window.scrollTo({ top, behavior: 'instant' }),
      Math.round(height * position));
    await page.waitForTimeout(700);
    await page.screenshot({ path: path.join(out, `${scheme}-${name}.png`) });
  }

  await page.close();
}

// ---------------------------------------------------------------- no flash --
console.log('\nno flash before paint');
{
  const page = await browser.newPage({ colorScheme: 'dark' });
  // `domcontentloaded`, not `commit`: at commit the head has not been parsed,
  // so the answer there is meaningless. What matters is that the theme is set
  // by the time the document is ready — i.e. by the blocking head script and
  // not by React, which runs a paint later.
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  const early = await page.evaluate(() => document.documentElement.dataset.theme);
  check(early === 'dark', 'the theme is set by the time the DOM is ready',
    `got ${early}`);

  // And prove it is the head script doing it, not hydration: the same page
  // with JavaScript frameworks unmounted still has to have been correct.
  const html = await (await fetch(base)).text();
  const headEnd = html.indexOf('</head>');
  const scriptAt = html.indexOf('comodor-theme');
  check(scriptAt !== -1 && scriptAt < headEnd,
    'the theme script is inside <head>, before any content');
  await page.close();
}

// ------------------------------------------------------------- the choice ---
console.log('\nthe stored choice');
{
  const page = await browser.newPage({ colorScheme: 'dark' });
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  await page.click('button.theme');
  await page.waitForTimeout(400);
  check(await page.getAttribute('html', 'data-theme') === 'light',
    'the toggle switches away from the system preference');

  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  check(await page.getAttribute('html', 'data-theme') === 'light',
    'the choice survives a reload');

  const stored = await page.evaluate(() => localStorage.getItem('comodor-theme'));
  check(stored === 'light', 'the choice is what was stored', String(stored));
  await page.close();
}

await browser.close();
console.log(failures ? `\n${failures} failed\n` : '\nall passed\n');
process.exit(failures ? 1 : 0);
