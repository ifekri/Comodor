/**
 * The demo set: what changed, in both themes, at several sizes, plus frames
 * far enough apart to show the globe has actually turned.
 *
 *   node tools/demo.mjs [baseUrl] [outDir]
 */

import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const base = process.argv[2] || 'http://localhost:3300';
const out = process.argv[3] || path.join(process.cwd(), '.demo');
await mkdir(out, { recursive: true });

const browser = await chromium.launch();

async function open(width, height, scheme) {
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 2,
    colorScheme: scheme,
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(2400);
  return page;
}

// -- the hero, in both themes ------------------------------------------------
for (const scheme of ['light', 'dark']) {
  const page = await open(1440, 940, scheme);
  await page.screenshot({ path: path.join(out, `1-hero-${scheme}.png`) });
  await page.close();
}

// -- the globe, three moments, to prove it turns -----------------------------
{
  const page = await open(1440, 940, 'light');
  const globe = await page.locator('.hero__figure').boundingBox();
  const clip = {
    x: globe.x - 10, y: globe.y - 10,
    width: globe.width + 20, height: globe.height + 20,
  };
  for (const [index, wait] of [[1, 0], [2, 9000], [3, 9000]]) {
    if (wait) await page.waitForTimeout(wait);
    await page.screenshot({ path: path.join(out, `2-globe-turn-${index}.png`), clip });
  }

  // The globe rewrites eleven attributes a frame. Say so with a number rather
  // than hoping, because "it felt smooth on my machine" is not a measurement.
  const fps = await page.evaluate(
    () =>
      new Promise((done) => {
        let frames = 0;
        const start = performance.now();
        const tick = () => {
          frames += 1;
          const elapsed = performance.now() - start;
          if (elapsed < 3000) requestAnimationFrame(tick);
          else done(frames / (elapsed / 1000));
        };
        requestAnimationFrame(tick);
      }),
  );
  console.log(`  globe       ${fps.toFixed(1)} frames per second`);
  await page.close();
}

// -- the install command, idle and copied ------------------------------------
{
  const page = await open(1440, 940, 'light');
  await page.locator('.hero__install .install__tab', { hasText: 'Linux' }).click();
  await page.waitForTimeout(250);

  const block = await page.locator('.hero__install').boundingBox();
  const clip = {
    x: block.x - 20, y: block.y - 46,
    width: block.width + 40, height: block.height + 70,
  };

  await page.screenshot({ path: path.join(out, '3-install-idle.png'), clip });
  const command = page.locator('.hero__install .install__command');
  const before = await command.boundingBox();

  await page.locator('.hero__install .copy').click();
  await page.waitForTimeout(320);
  await page.screenshot({ path: path.join(out, '4-install-copied.png'), clip });

  const after = await command.boundingBox();
  const copied = await page.evaluate(() => navigator.clipboard.readText());

  console.log(`  box before  ${Math.round(before.width)}x${Math.round(before.height)}`);
  console.log(`  box after   ${Math.round(after.width)}x${Math.round(after.height)}`);
  console.log(`  clipboard   ${JSON.stringify(copied)}`);
  await page.close();
}

// -- a phone, both themes ----------------------------------------------------
for (const scheme of ['light', 'dark']) {
  const page = await open(390, 844, scheme);
  await page.screenshot({ path: path.join(out, `5-phone-${scheme}.png`) });
  await page.close();
}

await browser.close();
console.log(`\nwritten to ${out}`);
