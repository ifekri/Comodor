/**
 * Does the install command ever need a scrollbar?
 *
 * It must not. A horizontal scrollbar inside a one-line command is ugly, and
 * worse than ugly: it hides the end of the very string the page exists to
 * deliver, and nothing on screen says there is more to see. The bug only shows
 * on the long commands (macOS and Linux), which is exactly why it survived —
 * the Windows tab is short enough to fit and looks fine.
 *
 * Checked on every tab at every width, because the failure is a function of
 * both.
 */

import { chromium } from 'playwright';

const base = process.argv[2] || 'http://localhost:3300';
const WIDTHS = [360, 390, 414, 500, 620, 700, 768, 820, 900, 1024, 1180, 1280, 1440, 1680];

let failures = 0;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(base, { waitUntil: 'networkidle' });
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(1800);

for (const width of WIDTHS) {
  await page.setViewportSize({ width, height: 900 });
  await page.waitForTimeout(260);

  for (const tab of ['macOS', 'Linux', 'Windows']) {
    await page.click(`.install__tab:has-text("${tab}")`);
    await page.waitForTimeout(140);

    const state = await page.evaluate(() => {
      const results = [];
      for (const code of document.querySelectorAll('.install__command code')) {
        const overflow = code.scrollWidth - code.clientWidth;
        const block = code.closest('.install__command');
        results.push({
          overflow,
          // The text must also stay inside the dark panel it sits in.
          spills: Math.round(
            code.getBoundingClientRect().right - block.getBoundingClientRect().right,
          ),
          text: code.textContent.trim().slice(0, 34),
        });
      }
      return results;
    });

    for (const item of state) {
      if (item.overflow > 1 || item.spills > 1) {
        failures += 1;
        console.log(
          `  FAIL  ${String(width).padEnd(5)} ${tab.padEnd(8)} ` +
          `overflow ${item.overflow}px, spills ${item.spills}px  "${item.text}…"`,
        );
      }
    }
  }
}

// The page itself must not gain a scrollbar either.
for (const width of [360, 768, 1440]) {
  await page.setViewportSize({ width, height: 900 });
  await page.waitForTimeout(260);
  const page_overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (page_overflow > 1) {
    failures += 1;
    console.log(`  FAIL  the page scrolls sideways at ${width}px (${page_overflow}px)`);
  }
}

await browser.close();

if (failures) {
  console.log(`\n${failures} failed\n`);
  process.exit(1);
}
console.log(`\nthe command fits at every width, on every tab\n`);
