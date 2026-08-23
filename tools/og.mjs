/**
 * Render the social card and the icons.
 *
 *   node tools/og.mjs
 *
 * Everything here is committed to `public/` rather than generated at request
 * time, because this site is a static export on GitHub Pages: there is no
 * server to run an ImageResponse route, and a card that 404s is how a link
 * ends up as a bare grey rectangle on every platform at once.
 *
 * Re-run it when the wording or the palette changes. The output is
 * deterministic apart from font rasterisation.
 */

import { chromium } from 'playwright';
import { mkdir, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.cwd();
const out = path.join(root, 'public');
await mkdir(out, { recursive: true });

const browser = await chromium.launch();

// -- the social card --------------------------------------------------------
{
  const page = await browser.newPage({
    viewport: { width: 1200, height: 630 },
    deviceScaleFactor: 1,
  });
  await page.goto(pathToFileURL(path.join(root, 'tools', 'og.html')).href);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForSelector('html[data-ready="yes"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, 'og.png') });
  await page.close();
  console.log('  public/og.png            1200x630');
}

// -- GitHub's social preview -------------------------------------------------
/*
 * A different aspect ratio, and no API to set it with: GitHub takes this image
 * through the web interface only, so it is committed to the agent repository
 * as `.github/social-preview.png` and uploaded once by hand under
 * Settings → General → Social preview.
 */
{
  const page = await browser.newPage({
    viewport: { width: 1280, height: 640 },
    deviceScaleFactor: 1,
  });
  await page.goto(pathToFileURL(path.join(root, 'tools', 'og.html')).href);
  await page.addStyleTag({ content: 'body { width: 1280px; height: 640px; }' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForSelector('html[data-ready="yes"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, 'social-preview.png') });
  await page.close();
  console.log('  public/social-preview.png  1280x640');
}

// -- the icons ----------------------------------------------------------------
/*
 * Not generated. They are the real mark, uploaded as a set, and this file used
 * to draw its own - a dark square with a prompt caret, which was a fair
 * placeholder while there was no logo and is not the logo.
 *
 * The code that made them is gone rather than commented out, because a
 * generator that overwrites the brand on every run is a trap: the next person
 * to render the card would put the placeholder back in every browser tab, and
 * nothing in the diff would say why.
 *
 * What is left is a check, since the metadata promises these by name and a
 * missing one is a broken icon in a tab rather than an error anybody sees.
 */
const PROMISED = [
  'favicon.ico',
  'favicon-16x16.png', 'favicon-32x32.png', 'favicon-96x96.png',
  'android-icon-192x192.png',
  'apple-icon-180x180.png', 'apple-icon-152x152.png',
  'apple-icon-120x120.png', 'apple-icon-76x76.png',
  'apple-touch-icon.png',
  'ms-icon-70x70.png', 'ms-icon-150x150.png', 'ms-icon-310x310.png',
  'site.webmanifest', 'browserconfig.xml',
];

{
  const missing = [];
  for (const name of PROMISED) {
    try {
      await stat(path.join(out, name));
    } catch {
      missing.push(name);
    }
  }
  if (missing.length) {
    console.error(`\n  missing from public/: ${missing.join(', ')}`);
    console.error('  the page asks browsers for these by name.');
    process.exitCode = 1;
  } else {
    console.log(`  ${PROMISED.length} icons present`);
  }
}

await browser.close();
