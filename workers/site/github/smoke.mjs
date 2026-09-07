/**
 * Ask the deployed Worker for an install URL, and check it is the right one.
 *
 * This exists because a green suite is not a deployed Worker. The unit tests
 * passed throughout the weeks production was handing out
 * `github.com/apps/comodor/installations/new`, a 404 — they passed *because*
 * every fixture agreed with the same wrong value, and they would have kept
 * passing if the Worker had never deployed at all.
 *
 * So this talks to the real origin. It is not a unit test and is not in
 * `npm test`: it needs the network, and a test that needs the network fails
 * for reasons that have nothing to do with the change under review. It is a
 * post-deploy check, run by hand or by a workflow after a deploy:
 *
 *   node workers/site/github/smoke.mjs
 *   node workers/site/github/smoke.mjs https://staging.example
 *
 * **It creates nothing.** `POST /install` mints a signed state and returns a
 * link. Nobody follows the link, no app is installed, no repository is
 * touched, and the state expires unused in fifteen minutes. No credential is
 * needed or read.
 *
 * The key it sends is generated here and thrown away. It has to be a real
 * P-256 point because the endpoint checks, which is itself worth knowing still
 * works.
 */

import { APP_SLUG } from './app-identity.test-support.mjs';

const DEFAULT_ORIGIN = 'https://comodor.ai';
const PATH = '/api/integrations/github/install';

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function throwawayKey() {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  return base64url(await crypto.subtle.exportKey('raw', pair.publicKey));
}

const problems = [];
function expect(condition, said) {
  if (!condition) problems.push(said);
  console.log(`${condition ? 'ok  ' : 'FAIL'}  ${said}`);
}

async function main() {
  const origin = (process.argv[2] || DEFAULT_ORIGIN).replace(/\/+$/, '');
  console.log(`checking ${origin}${PATH}\n`);

  const answer = await fetch(`${origin}${PATH}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'application/json',
      // Cloudflare's bot rules answer 1010 to a bare script user agent, which
      // looks exactly like the endpoint being broken. Saying what this is
      // avoids half an hour spent debugging the wrong thing.
      'user-agent': 'comodor-deploy-smoke/1 (+https://comodor.ai)',
    },
    body: JSON.stringify({
      public_key: await throwawayKey(),
      client: 'deploy-smoke',
      protocol: 2,
    }),
  });

  expect(answer.status === 200, `install answered 200 (got ${answer.status})`);
  if (answer.status !== 200) {
    console.log((await answer.text()).slice(0, 200));
    process.exit(1);
  }

  const body = await answer.json();
  let url;
  try {
    url = new URL(body.url || '');
  } catch {
    expect(false, 'it returned a URL');
    process.exit(1);
  }

  expect(url.protocol === 'https:', 'the URL is https');
  expect(url.host === 'github.com', `the URL is on github.com (got ${url.host})`);
  expect(url.pathname === `/apps/${APP_SLUG}/installations/new`,
    `the URL names ${APP_SLUG} (got ${url.pathname})`);
  expect(!url.pathname.startsWith('/apps/comodor/'),
    'and not the slug that 404s');
  expect(Boolean(url.searchParams.get('state')), 'the URL carries a state');
  expect(url.searchParams.get('state') === body.state,
    'and it is the state the Worker issued');
  expect(Number(body.expires_in) > 0,
    `expires_in is positive (got ${body.expires_in})`);
  expect(Boolean(body.nonce), 'a nonce came back');

  // Not a failure. A deployment without the Durable Object binding answers
  // protocol 1, which still works — but it means the automatic flow is not
  // live yet, and that is worth saying out loud after a deploy.
  console.log(`\nprotocol offered: ${body.protocol ?? 1}`
    + (Number(body.protocol) === 2 ? ' (automatic)'
      : ' (receipt — the rendezvous binding is not live)'));

  // Never the state itself. It is short-lived and unused, and printing tokens
  // into a CI log is a habit rather than a one-off.
  console.log(`state: ${String(body.state).slice(0, 12)}… (${String(body.state).length} chars)`);

  if (problems.length) {
    console.error(`\n${problems.length} check(s) failed`);
    process.exit(1);
  }
  console.log('\nall checks passed');
}

main().catch((error) => {
  console.error(`could not reach the deployment: ${error.message}`);
  process.exit(1);
});
