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
import { mkdir, readFile, stat } from 'node:fs/promises';
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
/*
 * The icons, all of them, from `icon.svg`.
 *
 * That file is the mark; everything raster is a rendering of it. Before this
 * they were twenty-eight files uploaded by hand, which works until the logo
 * changes - and then somebody has to remember every name, every size, and
 * which ones a browser still asks for. The ones they miss stay wrong for as
 * long as nobody notices, and nobody notices a favicon.
 *
 * The list is exactly what the page, the manifest and `browserconfig.xml` name,
 * plus the two paths that get fetched without any HTML being read. Nothing is
 * generated because a generator could: a folder of files nothing references is
 * how there came to be twenty-eight.
 *
 * `favicon.ico` is left alone. It is a container format rather than a PNG, the
 * one in place is right, and rebuilding it would mean hand-rolling an ICO
 * around a render for no gain.
 */
const RENDER = [
  // what <link rel="icon"> asks for
  [16, 'favicon-16x16.png'], [32, 'favicon-32x32.png'], [96, 'favicon-96x96.png'],
  // the manifest
  [36, 'android-icon-36x36.png'], [48, 'android-icon-48x48.png'],
  [72, 'android-icon-72x72.png'], [96, 'android-icon-96x96.png'],
  [144, 'android-icon-144x144.png'], [192, 'android-icon-192x192.png'],
  [512, 'icon-512.png'],
  // iOS, which picks the largest it is offered and ignores the rest - the
  // smaller ones are what an older device takes instead of scaling badly
  [57, 'apple-icon-57x57.png'], [60, 'apple-icon-60x60.png'],
  [72, 'apple-icon-72x72.png'], [76, 'apple-icon-76x76.png'],
  [114, 'apple-icon-114x114.png'], [120, 'apple-icon-120x120.png'],
  [144, 'apple-icon-144x144.png'], [152, 'apple-icon-152x152.png'],
  [180, 'apple-icon-180x180.png'], [192, 'apple-icon.png'],
  [192, 'apple-icon-precomposed.png'],
  // fetched by name, with or without a tag pointing at it
  [180, 'apple-touch-icon.png'],
  // browserconfig.xml
  [70, 'ms-icon-70x70.png'], [150, 'ms-icon-150x150.png'],
  [144, 'ms-icon-144x144.png'], [310, 'ms-icon-310x310.png'],
];

{
  const svg = await readFile(path.join(out, 'icon.svg'), 'utf8');
  // One page per size rather than one reused: a viewport resize leaves the
  // previous render's layout behind often enough to matter, and these are
  // cheap.
  for (const [size, name] of RENDER) {
    const page = await browser.newPage({
      viewport: { width: size, height: size },
      deviceScaleFactor: 1,
    });
    await page.setContent(
      `<body style="margin:0">${svg
        .replace(/width="\d+"/, `width="${size}"`)
        .replace(/height="\d+"/, `height="${size}"`)}</body>`,
    );
    await page.screenshot({ path: path.join(out, name), omitBackground: true });
    await page.close();
  }
  console.log(`  ${RENDER.length} icons rendered from icon.svg`);
}

await browser.close();

const PROMISED = [
  'icon.svg', 'icon-512.png',
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

