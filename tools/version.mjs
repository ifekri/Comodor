/**
 * Does the version the page claims still exist?
 *
 * `site.config.ts` carries a version number and the page puts it into its
 * structured data as `softwareVersion`, which is a machine-readable claim
 * about a real artefact. It went stale without anybody noticing: the page said
 * 0.3.0 for long enough that twelve releases went out underneath it, and
 * nothing looked wrong at any point, because a wrong number renders exactly as
 * well as a right one.
 *
 * So it is checked against PyPI, which is the thing being described.
 *
 *   node tools/version.mjs
 *   node tools/version.mjs http://localhost:4300/   the built page as well
 *
 * A network failure is not a test failure. This is a claim worth checking when
 * it can be, not a reason to block a build on somebody else's uptime.
 */
import { readFile } from 'node:fs/promises';

const PACKAGE = 'comodor';
const CONFIG = new URL('../lib/site.config.ts', import.meta.url);
const PATIENCE = 15000;

let failed = false;
const ok = (message) => console.log(`  ok    ${message}`);
const bad = (message) => {
  console.log(`  FAIL  ${message}`);
  failed = true;
};

/**
 * `fetch` with a deadline that is cleaned up afterwards.
 *
 * `AbortSignal.timeout` looks like the right tool and leaves its timer armed:
 * on Windows the process then ends with a libuv assertion instead of an exit
 * status, which reads as the checker crashing rather than the check failing.
 */
async function get(url) {
  const giveUp = new AbortController();
  const timer = setTimeout(() => giveUp.abort(), PATIENCE);
  try {
    return await fetch(url, { signal: giveUp.signal });
  } finally {
    clearTimeout(timer);
  }
}

const source = await readFile(CONFIG, 'utf8');
const claimed = source.match(/version:\s*'([^']+)'/)?.[1];
if (!claimed) {
  console.log('\n  FAIL  no version in site.config.ts\n');
  process.exitCode = 1;
} else {
  console.log(`\nThe page claims ${claimed}\n`);

  let published = null;
  try {
    const response = await get(`https://pypi.org/pypi/${PACKAGE}/json`);
    if (!response.ok) throw new Error(`PyPI answered ${response.status}`);
    published = (await response.json()).info.version;
  } catch (error) {
    console.log(`  skip  PyPI could not be reached (${error.message})`);
    console.log('        The claim is unchecked, not wrong.\n');
  }

  if (published !== null) {
    if (claimed === published) {
      ok(`PyPI has ${published}`);
    } else {
      bad(`PyPI has ${published}, the page says ${claimed}`);
      console.log('        Structured data quotes this, so it is a wrong claim');
      console.log('        about a real package, not a cosmetic slip.');
    }

    // And the built page, when one is being served.
    const site = process.argv[2];
    if (site) {
      try {
        const html = await (await get(site)).text();
        const inPage = html.match(/"softwareVersion":\s*"([^"]+)"/)?.[1];
        if (!inPage) bad('the page has no softwareVersion in its structured data');
        else if (inPage === published) ok(`the built page also says ${inPage}`);
        else bad(`the built page says ${inPage}`);
      } catch (error) {
        console.log(`  skip  ${site} could not be read (${error.message})`);
      }
    }

    console.log(failed
      ? '\nthe version on the page is wrong\n'
      : '\nthe page describes a release that exists\n');
  }
}

process.exitCode = failed ? 1 : 0;
