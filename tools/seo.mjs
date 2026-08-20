/**
 * What a crawler and a link unfurler actually get.
 *
 *   node tools/seo.mjs [baseUrl]
 *
 * Written against the served page rather than the source, because most of the
 * ways this breaks are not visible in the source. A card that names an image
 * the host does not have looks perfect in `layout.tsx` and renders as a grey
 * rectangle in Slack; a canonical without the trailing slash and a sitemap
 * with one are two URLs to a search engine, and both look fine on their own.
 *
 * So every asset the page names is fetched, and the size of the card is read
 * off the bytes rather than trusted from the tag it was declared in.
 */

import { chromium } from 'playwright';

const base = (process.argv[2] || 'http://localhost:4300').replace(/\/$/, '');
let failures = 0;

function check(ok, label, detail = '') {
  if (!ok) failures += 1;
  const mark = ok ? '  ok  ' : '  FAIL';
  console.log(`${mark}  ${label}${detail ? `  ${detail}` : ''}`);
}

/**
 * Anything the page names, as something this run can fetch.
 *
 * The tags carry absolute production URLs, which is what they must carry —
 * `og:image` is read by servers that have no idea what page it came from. But
 * a local run has to test the local files, so a production URL is mapped back
 * onto whatever is being checked.
 */
function here(href) {
  const absolute = new URL(href, `${base}/`);
  return `${base}${absolute.pathname}${absolute.search}`;
}

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(`${base}/`, { waitUntil: 'domcontentloaded' });

const meta = await page.evaluate(() => {
  const value = (selector, attribute = 'content') =>
    document.querySelector(selector)?.getAttribute(attribute) ?? '';
  return {
    title: document.title,
    description: value('meta[name="description"]'),
    canonical: value('link[rel="canonical"]', 'href'),
    robots: value('meta[name="robots"]'),
    ogTitle: value('meta[property="og:title"]'),
    ogImage: value('meta[property="og:image"]'),
    ogUrl: value('meta[property="og:url"]'),
    ogAlt: value('meta[property="og:image:alt"]'),
    twitterCard: value('meta[name="twitter:card"]'),
    twitterImage: value('meta[name="twitter:image"]'),
    manifest: value('link[rel="manifest"]', 'href'),
    icons: [...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"]')]
      .map((node) => node.getAttribute('href')),
    jsonLd: [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map((node) => node.textContent || ''),
    h1: [...document.querySelectorAll('h1')].map((node) => node.textContent?.trim()),
    lang: document.documentElement.lang,
    imagesWithoutAlt: [...document.querySelectorAll('img')]
      .filter((node) => !node.getAttribute('alt')).length,
  };
});

console.log('\nThe page');
check(meta.title.length > 10 && meta.title.length <= 65,
      'the title is a usable length', `${meta.title.length} chars`);
check(meta.description.length >= 50 && meta.description.length <= 160,
      'the description fits a search snippet', `${meta.description.length} chars`);
check(meta.lang === 'en', 'the document declares its language', meta.lang);
check(meta.h1.length === 1, 'exactly one h1');
check(meta.imagesWithoutAlt === 0, 'every image has alt text');
check(meta.robots.includes('index'), 'it asks to be indexed', meta.robots);

console.log('\nOne page, one URL');
// Absolute and https whatever it is served from, because a canonical is read
// by crawlers that arrived from somewhere else entirely.
check(meta.canonical.startsWith('https://') && new URL(meta.canonical).pathname === '/',
      'the canonical is an absolute https URL for this page', meta.canonical);
check(meta.ogUrl === meta.canonical, 'og:url agrees with the canonical');

console.log('\nThe card');
check(meta.twitterCard === 'summary_large_image', 'a large card is declared');
check(Boolean(meta.ogImage), 'an image is named', meta.ogImage);
check(meta.twitterImage === meta.ogImage, 'both cards name the same image');
check(Boolean(meta.ogAlt), 'the image has alt text');

if (meta.ogImage) {
  const response = await page.request.get(here(meta.ogImage));
  check(response.ok(), 'the image is actually there', `${response.status()}`);
  if (response.ok()) {
    const bytes = await response.body();
    // PNG: width and height are big-endian at byte 16 of the IHDR chunk.
    const width = bytes.readUInt32BE(16);
    const height = bytes.readUInt32BE(20);
    check(width === 1200 && height === 630,
          'it is the size every platform crops from', `${width}x${height}`);
    check(bytes.length < 5_000_000, 'it is small enough to unfurl',
          `${Math.round(bytes.length / 1024)} KB`);
  }
}

console.log('\nWhat it says it is');
check(meta.jsonLd.length > 0, 'structured data is present');
for (const block of meta.jsonLd) {
  let parsed = null;
  try {
    parsed = JSON.parse(block);
  } catch {
    check(false, 'structured data parses as JSON');
    continue;
  }
  const nodes = parsed['@graph'] ?? [parsed];
  const types = nodes.map((node) => node['@type']);
  check(types.includes('SoftwareApplication'), 'it describes the software',
        types.join(', '));
  // Ratings nobody gave are the fastest way to lose a rich result, and a lie.
  check(!JSON.stringify(parsed).includes('aggregateRating'),
        'it claims no ratings it does not have');
}

console.log('\nEverything it points at');
for (const href of [...meta.icons, meta.manifest].filter(Boolean)) {
  const response = await page.request.get(here(href));
  check(response.ok(), `${href}`, `${response.status()}`);
}

console.log('\nFor the crawler');
const robots = await page.request.get(`${base}/robots.txt`);
check(robots.ok(), 'robots.txt is served');
const robotsText = robots.ok() ? await robots.text() : '';
check(robotsText.includes('Sitemap:'), 'robots.txt names the sitemap');

const sitemap = await page.request.get(`${base}/sitemap.xml`);
check(sitemap.ok(), 'sitemap.xml is served');
if (sitemap.ok()) {
  const xml = await sitemap.text();
  check(xml.includes(`<loc>${meta.canonical}</loc>`),
        'the sitemap lists the canonical URL, trailing slash and all');
}

await browser.close();

if (failures) {
  console.log(`\n${failures} failed\n`);
  process.exit(1);
}
console.log('\neverything a crawler needs is there, and everything it names exists\n');
