/**
 * The property this file exists to hold:
 *
 *   Possession of the signed GitHub state is not sufficient to walk the
 *   browser leg, choose an installation, or deliver a result to a terminal.
 *
 * It was sufficient, and that was the hole. A state goes to GitHub and comes
 * back in a query string, so it is visible in an address bar, a history, a
 * referrer and anywhere the person pastes it — and holding one was enough to
 * reach `setup` with an installation of one's own and have the result
 * delivered to a terminal that had chosen neither.
 *
 * There are two credentials now. The state says *which flow*; the browser
 * capability says *which browser*. The capability is random, one-time,
 * two-minute, and travels in a URL fragment — which browsers do not put in
 * requests and do not put in `Referer` — so it never appears in a log, a proxy
 * or anything GitHub sees. Spending it buys a signed cookie naming that exact
 * flow, and `setup` requires both.
 *
 * Every test below is one attacker, or the one legitimate browser.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { APP_SLUG } from './app-identity.test-support.mjs';
import {
  BROWSER_COOKIE,
  LAUNCH_LIVES_FOR,
  PROTOCOL_RECEIPT,
  PROTOCOL_RENDEZVOUS,
} from './config.js';
import { digestOf, issueCookie } from './browser.js';
import { arm } from './rendezvous.js';
import { ConnectionFlow } from './rendezvous.js';
import { handle } from './routes.js';

const SECRET = 'a-deployment-secret-for-tests';
const BASE = 'https://comodor.ai/api/integrations/github';

// --------------------------------------------------------------------------- //
// stand-ins
// --------------------------------------------------------------------------- //

function namespace() {
  const kept = new Map();
  const instances = new Map();
  const storage = (name) => {
    if (!kept.has(name)) kept.set(name, new Map());
    const own = kept.get(name);
    return {
      async get(key) { return own.get(key); },
      async put(key, value) { own.set(key, value); },
      async delete(key) { own.delete(key); },
      async list({ prefix = '', limit = Infinity } = {}) {
        const found = new Map();
        for (const [k, v] of own) {
          if (k.startsWith(prefix) && found.size < limit) found.set(k, v);
        }
        return found;
      },
      async deleteAll() { own.clear(); },
      async setAlarm() {},
    };
  };
  return {
    idFromName(name) { return { name: String(name) }; },
    get(id) {
      if (!instances.has(id.name)) {
        instances.set(id.name, new ConnectionFlow({ storage: storage(id.name) }));
      }
      return instances.get(id.name);
    },
  };
}

function env(extra = {}) {
  return {
    GITHUB_APP_WEBHOOK_SECRET: SECRET,
    GITHUB_APP_SLUG: APP_SLUG,
    CONNECTION_FLOW: namespace(),
    ...extra,
  };
}

async function aPublicKey() {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const raw = await crypto.subtle.exportKey('raw', pair.publicKey);
  let binary = '';
  for (const byte of new Uint8Array(raw)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function post(where, body, on, headers = {}) {
  const answer = await handle(new Request(`${BASE}/${where}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(body),
  }), on);
  return { status: answer.status, body: await answer.json(),
           cookie: answer.headers.get('set-cookie') || '' };
}

async function get(where, on, headers = {}) {
  const answer = await handle(new Request(`${BASE}/${where}`, { headers }), on);
  return { status: answer.status, text: await answer.text(),
           headers: answer.headers };
}

/** Start a flow the way the agent does, and read the capability out of it. */
async function begin(on, { protocol = PROTOCOL_RENDEZVOUS } = {}) {
  const { body } = await post('install',
    { public_key: await aPublicKey(), protocol, client: 'comodor-agent' }, on);
  const url = new URL(body.url);
  return {
    ...body,
    capability: new URLSearchParams(url.hash.slice(1)).get('k') || '',
    launch: url,
  };
}

/** Spend a capability, as the launch page's script does. */
function bindWith(on, flow, capability) {
  return post('launch/bind', { flow, capability }, on);
}

/** The cookie value out of a Set-Cookie header. */
function cookieValue(header) {
  return String(header).split(';')[0];
}

// --------------------------------------------------------------------------- //
// 6 / 7 — the legitimate browser
// --------------------------------------------------------------------------- //

test('the browser the terminal opened walks the flow and reaches GitHub',
     async () => {
  const on = env();
  const flow = await begin(on);

  assert.ok(flow.capability, 'the launch link carried no capability');
  assert.equal(flow.launch.pathname, `${new URL(BASE).pathname}/launch`);

  const bound = await bindWith(on, flow.nonce, flow.capability);

  assert.equal(bound.status, 200);
  const next = new URL(bound.body.url);
  assert.equal(next.host, 'github.com');
  assert.equal(next.pathname, `/apps/${APP_SLUG}/installations/new`);
  assert.equal(next.searchParams.get('state'), flow.state);
  assert.ok(bound.cookie.includes(`${BROWSER_COOKIE}=`));
});

test('and setup accepts it, once it has both', async () => {
  const on = env();
  const flow = await begin(on);
  const bound = await bindWith(on, flow.nonce, flow.capability);

  const answer = await get(
    `setup?installation_id=42&state=${encodeURIComponent(flow.state)}`,
    on, { cookie: cookieValue(bound.cookie) });

  // What is being tested is the door, not what is behind it. This env has no
  // OAuth credentials, so the next step says "Not configured" — which is the
  // proof that the binding check passed, because a refused browser never gets
  // that far.
  assert.ok(!/no longer valid/.test(answer.text),
    `setup refused a legitimate browser: ${answer.text.slice(0, 160)}`);
  assert.ok(!/already been used/.test(answer.text));
});

test('with OAuth configured, a bound browser is redirected to GitHub', async () => {
  const on = env({
    GITHUB_APP_CLIENT_ID: 'Iv1.testclientid',
    GITHUB_APP_CLIENT_SECRET: 'a-client-secret',
  });
  const flow = await begin(on);
  const bound = await bindWith(on, flow.nonce, flow.capability);

  const answer = await handle(new Request(
    `${BASE}/setup?installation_id=42&state=${encodeURIComponent(flow.state)}`,
    { headers: { cookie: cookieValue(bound.cookie) } }), on);

  assert.equal(answer.status, 302);
  assert.match(answer.headers.get('location') || '', /^https:\/\/github\.com\/login\/oauth/);
});

// --------------------------------------------------------------------------- //
// 1 / 5 / 8 — the state on its own
// --------------------------------------------------------------------------- //

test('a valid state with no browser binding is refused', async () => {
  const on = env();
  const flow = await begin(on);

  const answer = await get(
    `setup?installation_id=42&state=${encodeURIComponent(flow.state)}`, on);

  assert.equal(answer.status, 200);
  assert.match(answer.text, /no longer valid/);
});

test('a state copied after the redirect to GitHub cannot start a second leg',
     async () => {
  // The shape of the real attack: the state is visible in the address bar the
  // moment GitHub is reached, and the capability is spent by then.
  const on = env();
  const flow = await begin(on);
  await bindWith(on, flow.nonce, flow.capability);

  // The attacker has the state and no cookie.
  const answer = await get(
    `setup?installation_id=999&state=${encodeURIComponent(flow.state)}`, on);

  assert.match(answer.text, /no longer valid/);
});

test('an attacker cannot substitute their own installation using only the state',
     async () => {
  const on = env();
  const victim = await begin(on);
  await bindWith(on, victim.nonce, victim.capability);

  // Attacker walks the victim's state with an installation of their own.
  const attempt = await get(
    `setup?installation_id=1234567&state=${encodeURIComponent(victim.state)}`, on);
  assert.match(attempt.text, /no longer valid/);

  // And nothing was delivered to the victim's terminal.
  const { peek } = await import('./rendezvous.js');
  assert.equal((await peek(on, victim.nonce)).status, 'pending');
});

// --------------------------------------------------------------------------- //
// 2 / 3 / 4 — the capability itself
// --------------------------------------------------------------------------- //

test('a wrong capability is refused', async () => {
  const on = env();
  const flow = await begin(on);

  const bound = await bindWith(on, flow.nonce, 'not-the-capability');

  assert.equal(bound.status, 403);
  assert.ok(!bound.cookie, 'a refusal must not set a cookie');
});

test('a wrong guess does not burn the real capability', async () => {
  // Otherwise anybody who knew a flow could deny it by guessing once.
  const on = env();
  const flow = await begin(on);

  await bindWith(on, flow.nonce, 'not-the-capability');
  const bound = await bindWith(on, flow.nonce, flow.capability);

  assert.equal(bound.status, 200);
});

test('a capability from another flow is refused', async () => {
  const on = env();
  const mine = await begin(on);
  const theirs = await begin(on);

  const bound = await bindWith(on, mine.nonce, theirs.capability);

  assert.equal(bound.status, 403);
});

test('a cookie for one flow does not open another', async () => {
  const on = env();
  const mine = await begin(on);
  const theirs = await begin(on);
  const bound = await bindWith(on, theirs.nonce, theirs.capability);

  const answer = await get(
    `setup?installation_id=42&state=${encodeURIComponent(mine.state)}`,
    on, { cookie: cookieValue(bound.cookie) });

  assert.match(answer.text, /no longer valid/);
});

test('a spent capability cannot be spent again', async () => {
  const on = env();
  const flow = await begin(on);

  const first = await bindWith(on, flow.nonce, flow.capability);
  const second = await bindWith(on, flow.nonce, flow.capability);

  assert.equal(first.status, 200);
  assert.equal(second.status, 403);
  assert.ok(!second.cookie);
});

// --------------------------------------------------------------------------- //
// 4, again — one-time is only half of it
// --------------------------------------------------------------------------- //

test('a capability nobody spent in time stops working', async () => {
  // The other half of "one-time and short-lived". Without this the two-minute
  // window is a number in a comment: a link that sat unopened in a chat log
  // would still be a live capability. Armed in the past rather than waited
  // for, so the test is instant and deterministic.
  const on = env();
  const flow = await begin(on);

  await arm(on, flow.nonce, await digestOf(flow.capability), flow.state,
    { now: Date.now() - (LAUNCH_LIVES_FOR + 1) * 1000 });

  const bound = await bindWith(on, flow.nonce, flow.capability);

  assert.equal(bound.status, 403);
  assert.ok(!bound.cookie, 'an expired capability must not buy a cookie');
  assert.match(bound.body.error, /no longer valid/);
});

test('a cookie that has outlived its flow is refused', async () => {
  // The cookie carries its own expiry inside the signature, so a browser
  // holding one from an abandoned flow cannot present it later. Signed with
  // the real secret — this is expiry being enforced, not a bad signature
  // being caught.
  const on = env();
  const flow = await begin(on);
  await bindWith(on, flow.nonce, flow.capability);

  const stale = cookieValue(await issueCookie(SECRET, flow.nonce, {
    now: Date.now() - (LAUNCH_LIVES_FOR + 900 + 1) * 1000,
  }));

  const answer = await get(
    `setup?installation_id=42&state=${encodeURIComponent(flow.state)}`,
    on, { cookie: stale });

  assert.match(answer.text, /no longer valid/);
});

test('the cookie a legitimate browser gets outlives the walk to GitHub',
     async () => {
  // The opposite failure, and the one a shorter cookie would cause: choosing
  // an account and repositories takes minutes, and a cookie that expired
  // during it would refuse the person who did everything right. It is scoped
  // to the state's own lifetime, not the launch window's.
  const on = env();
  const flow = await begin(on);
  const bound = await bindWith(on, flow.nonce, flow.capability);

  const seconds = Number(/Max-Age=(\d+)/.exec(bound.cookie)?.[1]);

  assert.ok(seconds > LAUNCH_LIVES_FOR,
    `cookie lives ${seconds}s, which is not longer than the launch window`);
  assert.ok(seconds >= 900, 'and must cover the state it is paired with');
});

test('a forged cookie is refused', async () => {
  const on = env();
  const flow = await begin(on);

  const forged = `b1.${btoa(JSON.stringify({
    n: flow.nonce, e: Math.floor(Date.now() / 1000) + 600,
  })).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}.deadbeef`;

  const answer = await get(
    `setup?installation_id=42&state=${encodeURIComponent(flow.state)}`,
    on, { cookie: `${BROWSER_COOKIE}=${forged}` });

  assert.match(answer.text, /no longer valid/);
});

// --------------------------------------------------------------------------- //
// 9 — refreshing does not substitute or overwrite
// --------------------------------------------------------------------------- //

test('a second trip through setup on one flow is refused', async () => {
  const on = env();
  const flow = await begin(on);
  const bound = await bindWith(on, flow.nonce, flow.capability);
  const cookie = cookieValue(bound.cookie);

  await get(`setup?installation_id=42&state=${encodeURIComponent(flow.state)}`,
    on, { cookie });
  const again = await get(
    `setup?installation_id=42&state=${encodeURIComponent(flow.state)}`,
    on, { cookie });

  assert.match(again.text, /already been used/);
});

test('a second result cannot overwrite the first', async () => {
  const { deliver, peek } = await import('./rendezvous.js');
  const on = env();
  const flow = await begin(on);

  await deliver(on, flow.nonce, { status: 'connected', grant: 'g1.the-real-one' });
  const again = await deliver(on, flow.nonce, { status: 'cancelled' });

  assert.equal(again.stored, false);
  assert.equal((await peek(on, flow.nonce)).status, 'connected');
});

// --------------------------------------------------------------------------- //
// 10 — the older protocol is untouched
// --------------------------------------------------------------------------- //

test('protocol 1 gets GitHub directly, with no launch page and no cookie',
     async () => {
  const on = env();
  const flow = await begin(on, { protocol: PROTOCOL_RECEIPT });

  const url = new URL(flow.url);
  assert.equal(url.host, 'github.com');
  assert.equal(url.hash, '', 'no capability, because none is needed');
  assert.equal(flow.protocol, PROTOCOL_RECEIPT);
});

test('protocol 1 setup needs no browser binding', async () => {
  const on = env();
  const flow = await begin(on, { protocol: PROTOCOL_RECEIPT });

  const answer = await get(
    `setup?installation_id=42&state=${encodeURIComponent(flow.state)}`, on);

  assert.ok(!/no longer valid/.test(answer.text),
    'the receipt protocol must keep working exactly as it did');
});

test('a deployment with no rendezvous still hands out GitHub directly', async () => {
  const on = { GITHUB_APP_WEBHOOK_SECRET: SECRET, GITHUB_APP_SLUG: APP_SLUG };
  const { body } = await post('install',
    { public_key: await aPublicKey(), protocol: PROTOCOL_RENDEZVOUS }, on);

  assert.equal(body.protocol, PROTOCOL_RECEIPT);
  assert.equal(new URL(body.url).host, 'github.com');
});

// --------------------------------------------------------------------------- //
// the page that carries the capability
// --------------------------------------------------------------------------- //

test('the launch page keeps the capability out of everything it can', async () => {
  const on = env();
  const flow = await begin(on);
  const answer = await get(`launch?f=${encodeURIComponent(flow.nonce)}`, on);

  assert.equal(answer.status, 200);
  assert.ok(!answer.text.includes(flow.capability),
    'the page must never contain the capability; it is in the fragment');

  assert.equal(answer.headers.get('referrer-policy'), 'no-referrer');
  assert.equal(answer.headers.get('cache-control'), 'no-store');
  assert.equal(answer.headers.get('x-frame-options'), 'DENY');
  assert.match(answer.headers.get('content-security-policy') || '',
    /frame-ancestors 'none'/);
});

test('the launch page takes the fragment out of the address bar', async () => {
  const on = env();
  const flow = await begin(on);
  const answer = await get(`launch?f=${encodeURIComponent(flow.nonce)}`, on);

  assert.match(answer.text, /history\.replaceState/);
  assert.match(answer.text, /location\.replace/,
    'assign would leave the launch page one back-button away');
  assert.match(answer.text, /<noscript>/,
    'a browser without scripting has to be told why nothing happened');
});

test('the cookie is scoped, hidden and sent on the redirect back', async () => {
  const on = env();
  const flow = await begin(on);
  const bound = await bindWith(on, flow.nonce, flow.capability);

  assert.match(bound.cookie, /HttpOnly/);
  assert.match(bound.cookie, /Secure/);
  assert.match(bound.cookie, /Path=\/api\/integrations\/github/);
  // Lax rather than Strict: GitHub returns the browser to `setup` as a
  // top-level navigation from another site, and Strict would withhold the
  // cookie on exactly that request.
  assert.match(bound.cookie, /SameSite=Lax/);
});

test('binding without a flow or a capability is refused', async () => {
  const on = env();
  await begin(on);

  assert.equal((await post('launch/bind', {}, on)).status, 403);
  assert.equal((await post('launch/bind', { flow: 'x' }, on)).status, 403);
});

test('every refusal from bind says the same thing', async () => {
  // Never-armed, wrong, and already-spent are three different facts; telling
  // them apart tells a prober which guess was closer.
  const on = env();
  const flow = await begin(on);
  await bindWith(on, flow.nonce, flow.capability);

  const said = new Set();
  said.add((await bindWith(on, 'a-flow-that-never-existed', 'x')).body.error);
  said.add((await bindWith(on, flow.nonce, 'wrong')).body.error);
  said.add((await bindWith(on, flow.nonce, flow.capability)).body.error);

  assert.equal(said.size, 1, `three different answers: ${[...said].join(' | ')}`);
});
