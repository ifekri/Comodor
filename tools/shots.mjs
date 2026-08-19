/**
 * Screenshot the site so a design can be judged by looking at it.
 *
 * A page can pass every build check and every accessibility probe and still be
 * badly set. This exists because reading the CSS is not the same as seeing the
 * result, and the difference is the whole job.
 *
 *   node tools/shots.mjs [baseUrl] [outDir]
 */

import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const base = process.argv[2] || 'http://localhost:3300';
const out = process.argv[3] || path.join(process.cwd(), '.shots');

const VIEWS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'laptop', width: 1180, height: 800 },
  { name: 'tablet', width: 820, height: 1100 },
  { name: 'phone', width: 390, height: 844 },
];

// Where to stop and look. The scroll section needs several, because the whole
// point of it is what happens between them.
const STOPS = [
  { name: '01-hero', y: 0 },
  { name: '02-reflex-intro', y: 0.16 },
  { name: '03-reflex-mid', y: 0.28 },
  { name: '04-reflex-end', y: 0.36 },
  { name: '05-signals', y: 0.46 },
  { name: '06-skills', y: 0.58 },
  { name: '07-speed', y: 0.7 },
  { name: '08-control', y: 0.8 },
  { name: '09-install', y: 0.93 },
];

await mkdir(out, { recursive: true });

const browser = await chromium.launch();

for (const view of VIEWS) {
  const page = await browser.newPage({
    viewport: { width: view.width, height: view.height },
    deviceScaleFactor: 2,
  });

  await page.goto(base, { waitUntil: 'networkidle' });
  // Fonts change metrics, and a screenshot taken before they land measures
  // the fallback rather than the design.
  await page.evaluate(() => document.fonts.ready);
  // Long enough for every entrance to have finished. A screenshot taken
  // mid-timeline measures the animation, not the design.
  await page.waitForTimeout(2200);

  const height = await page.evaluate(() => document.body.scrollHeight);

  for (const stop of STOPS) {
    await page.evaluate((top) => window.scrollTo({ top, behavior: 'instant' }),
      Math.round(height * stop.y));
    await page.waitForTimeout(700);
    await page.screenshot({
      path: path.join(out, `${view.name}-${stop.name}.png`),
    });
  }

  // The whole page in one image, for proportion and rhythm.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await page.screenshot({
    path: path.join(out, `${view.name}-full.png`),
    fullPage: true,
  });

  console.log(`${view.name}: ${STOPS.length + 1} shots, page ${height}px`);
  await page.close();
}

await browser.close();
console.log(`\nwritten to ${out}`);
