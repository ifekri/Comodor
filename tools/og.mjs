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
import { mkdir, writeFile } from 'node:fs/promises';
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

// -- the icons --------------------------------------------------------------
/*
 * The mark is the prompt caret the interface itself opens every line with, in
 * ember on the page's paper. It has to survive being sixteen pixels wide in a
 * browser tab, which rules out the globe: at that size a mesh of hairlines is
 * a grey smudge, and one bold glyph is not.
 */
const ICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#17150f"/>
  <path d="M20 19 L36 32 L20 45" fill="none" stroke="#e2703a" stroke-width="7"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M40 45 H48" stroke="#f6f2ea" stroke-width="7" stroke-linecap="round"/>
</svg>`;

await writeFile(path.join(out, 'icon.svg'), ICON, 'utf8');
console.log('  public/icon.svg');

for (const size of [180, 192, 512]) {
  const page = await browser.newPage({
    viewport: { width: size, height: size },
    deviceScaleFactor: 1,
  });
  await page.setContent(
    `<body style="margin:0">${ICON.replace('viewBox', `width="${size}" height="${size}" viewBox`)}</body>`,
  );
  const name = size === 180 ? 'apple-touch-icon.png' : `icon-${size}.png`;
  await page.screenshot({ path: path.join(out, name), omitBackground: true });
  await page.close();
  console.log(`  public/${name}`.padEnd(27) + `${size}x${size}`);
}

// A real .ico, because /favicon.ico is requested by things that never read the
// HTML: feed readers, link unfurlers, and older browsers.
{
  const page = await browser.newPage({ viewport: { width: 32, height: 32 } });
  await page.setContent(
    `<body style="margin:0">${ICON.replace('viewBox', 'width="32" height="32" viewBox')}</body>`,
  );
  const png = await page.screenshot({ omitBackground: true });
  await page.close();
  await writeFile(path.join(out, 'favicon.ico'), ico(png));
  console.log('  public/favicon.ico       32x32');
}

await browser.close();

/** Wrap a 32x32 PNG in an ICO container. Every browser reads PNG-in-ICO. */
function ico(png) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);        // reserved
  header.writeUInt16LE(1, 2);        // type: icon
  header.writeUInt16LE(1, 4);        // one image

  const entry = Buffer.alloc(16);
  entry.writeUInt8(32, 0);           // width
  entry.writeUInt8(32, 1);           // height
  entry.writeUInt8(0, 2);            // palette: none
  entry.writeUInt8(0, 3);            // reserved
  entry.writeUInt16LE(1, 4);         // colour planes
  entry.writeUInt16LE(32, 6);        // bits per pixel
  entry.writeUInt32LE(png.length, 8);
  entry.writeUInt32LE(22, 12);       // offset: header + entry

  return Buffer.concat([header, entry, png]);
}
