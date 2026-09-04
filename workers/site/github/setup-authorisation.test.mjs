/**
 * Who is allowed to be *given* a grant.
 *
 * `authorisation.test.mjs` covers who may use one. This covers the step
 * before it, which had a hole of its own: `setup` took `installation_id` from
 * a query string, confirmed with the app JWT that such an installation
 * existed, and issued its grant to whatever public key was in the state.
 *
 * Both of those checks pass for an attacker. The app JWT can see every
 * installation of the app, so asking it "is this real" answers yes about
 * strangers, and the state is one the attacker legitimately obtained by
 * starting their own flow. The relationship between the installation and the
 * person at the browser was never established:
 *
 *     /install with the attacker's key           → a valid state
 *     /setup?installation_id=VICTIM&state=THEIRS → the victim's grant
 *     /token signed with the attacker's key      → the victim's repositories
 *
 * The fix is a GitHub user authorisation, and the tests below are the proof
 * that it actually gates anything: the whole point of a check is that
 * something fails it.
 *
 *   node --test workers/site/github/setup-authorisation.test.mjs
 */

import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

import { handle } from './routes.js';
import { openGrant } from './grant.js';
import { challengeFor, COOKIE, issueState, openState } from './oauth.js';
import { issue } from './state.js';

const SECRET = 'a-webhook-secret-for-the-tests';
const BASE = 'https://comodor.ai/api/integrations/github';

/** What a configured deployment looks like, with no real credential in it. */
const ENV = {
  GITHUB_APP_WEBHOOK_SECRET: SECRET,
  GITHUB_APP_CLIENT_ID: 'Iv1.notarealclientid',
  GITHUB_APP_CLIENT_SECRET: 'not-a-real-client-secret',
  GITHUB_APP_SLUG: 'comodor',
};

/**
 * A client public key, generated for this run.
 *
 * Real rather than a plausible-looking string: `issueGrant` hashes the raw
 * bytes, so a fixture that is merely the right length fails inside the code
 * under test for a reason that has nothing to do with what is being tested.
 * Nothing here needs the private half - the attacker in these tests never has
 * to sign anything, because they never get far enough to be asked.
 */
const ATTACKER_KEY = await (async () => {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const raw = await crypto.subtle.exportKey('raw', pair.publicKey);
  return btoa(String.fromCharCode(...new Uint8Array(raw)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
})();

const VICTIM_INSTALLATION = 424242;

// --------------------------------------------------------------------------- //
// standing in for GitHub
// --------------------------------------------------------------------------- //

const realFetch = globalThis.fetch;

/** Every request the stub saw, so a test can assert what was *not* sent. */
let seen = [];

/**
 * Replace `fetch` for one test.
 *
 * `handlers` maps a substring of the URL to a function returning
 * `{status, body}`. Anything unmatched is a hard failure rather than a
 * default: a test that silently reached an unmocked endpoint would be
 * asserting about a network error, not about this code.
 */
function stubFetch(handlers) {
  seen = [];
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url);
    seen.push({ url: target, options });
    for (const [fragment, reply] of Object.entries(handlers)) {
      if (target.includes(fragment)) {
        const { status = 200, body = {} } = await reply(target, options);
        return new Response(JSON.stringify(body), {
          status, headers: { 'content-type': 'application/json' },
        });
      }
    }
    throw new Error(`the test did not expect a request to ${target}`);
  };
}

afterEach(() => { globalThis.fetch = realFetch; });

/** The installation list GitHub returns for a user who owns nothing else. */
function ownedBy(...ids) {
  return {
    total_count: ids.length,
    installations: ids.map((id) => ({
      id,
      account: { id: 9, login: 'ifekri', type: 'User' },
      repository_selection: 'selected',
      permissions: { contents: 'write' },
    })),
  };
}

async function getRequest(url, headers = {}) {
  return handle(new Request(url, { method: 'GET', headers }), ENV);
}

/** Walk `install` → `setup` and return where the browser was sent. */
async function throughSetup(installationId, publicKey = ATTACKER_KEY) {
  const started = await issue(SECRET, { publicKey });
  const answer = await getRequest(
    `${BASE}/setup?installation_id=${installationId}`
    + `&state=${encodeURIComponent(started.state)}`);
  return { answer, nonce: started.nonce };
}

/** A callback URL for a state this test built directly. */
async function aCallback({ installationId = VICTIM_INSTALLATION,
                           publicKey = ATTACKER_KEY, nonce = 'the-nonce',
                           verifier = 'a-verifier-of-a-reasonable-length',
                           challenge, code = 'a-code', now = Date.now(),
                           cookie } = {}) {
  const state = await issueState(SECRET, {
    installationId, publicKey, nonce,
    challenge: challenge || await challengeFor(verifier),
    now,
  });
  const headers = {};
  const sending = cookie === undefined ? verifier : cookie;
  if (sending !== null) headers.cookie = `${COOKIE}=${sending}`;
  return getRequest(
    `${BASE}/callback?code=${encodeURIComponent(code)}`
    + `&state=${encodeURIComponent(state)}`, headers);
}

/** The receipt out of a finished page, or null. */
function receiptIn(html) {
  const found = html.match(/<code[^>]*>([\w-]+\.[0-9a-f]+)<\/code>/);
  return found ? found[1] : null;
}

// --------------------------------------------------------------------------- //
// the attack itself
// --------------------------------------------------------------------------- //

test('a spoofed installation id gets no grant from setup', async () => {
  // The original exploit, run end to end. The attacker holds a state they
  // legitimately obtained and walks to setup with somebody else's id.
  stubFetch({});          // nothing may be called: not even the app JWT

  const { answer } = await throughSetup(VICTIM_INSTALLATION);
  const body = await answer.clone().text();

  assert.equal(answer.status, 302, 'setup must hand off, not conclude');
  assert.equal(receiptIn(body), null, 'no receipt may come out of setup');
  assert.ok(!body.includes('g1.'), 'no grant may appear in the page');
  assert.equal(seen.length, 0,
    'setup must not ask GitHub anything about an id nobody has proved is theirs');
});

test('setup redirects into a user authorisation, carrying nothing secret',
  async () => {
    stubFetch({});
    const { answer } = await throughSetup(VICTIM_INSTALLATION);

    const location = new URL(answer.headers.get('location'));
    assert.equal(location.origin + location.pathname,
      'https://github.com/login/oauth/authorize');
    assert.equal(location.searchParams.get('client_id'), ENV.GITHUB_APP_CLIENT_ID);
    assert.equal(location.searchParams.get('code_challenge_method'), 'S256');
    assert.ok(location.searchParams.get('code_challenge'));

    // The verifier is the one value that must not be in the URL: it would be
    // in a referrer, a proxy log and the address bar.
    assert.ok(!answer.headers.get('location').includes(
      answer.headers.get('set-cookie').split('=')[1].split(';')[0]));

    // And the client secret is never in anything a browser sees.
    assert.ok(!answer.headers.get('location')
      .includes(ENV.GITHUB_APP_CLIENT_SECRET));
  });

test('the state setup issues names the installation and the key, signed',
  async () => {
    stubFetch({});
    const { answer } = await throughSetup(VICTIM_INSTALLATION);

    const location = new URL(answer.headers.get('location'));
    const claims = await openState(SECRET, location.searchParams.get('state'));

    assert.equal(claims.i, VICTIM_INSTALLATION);
    assert.equal(claims.k, ATTACKER_KEY);
    // Not usable as an install state, and vice versa: one secret, two token
    // kinds, kept apart by their prefixes.
    assert.equal(await openState(SECRET, (await issue(SECRET,
      { publicKey: ATTACKER_KEY })).state), null);
  });

test("an installation belonging to somebody else is refused at the callback",
  async () => {
    // The heart of it. The attacker has authorised as themselves — a real
    // GitHub user, a real token — and asks for an installation that is not in
    // their list.
    stubFetch({
      'login/oauth/access_token': () => ({ body: { access_token: 'gho_theirs' } }),
      '/user/installations': () => ({ body: ownedBy(999999) }),
    });

    const answer = await aCallback({ installationId: VICTIM_INSTALLATION });
    const body = await answer.text();

    assert.ok(body.includes('not yours'));
    assert.equal(receiptIn(body), null);
    assert.ok(!body.includes('g1.'), 'no grant for an installation not theirs');
  });

test('the installation the user does own is granted', async () => {
  stubFetch({
    'login/oauth/access_token': () => ({ body: { access_token: 'gho_theirs' } }),
    '/user/installations': () => ({ body: ownedBy(VICTIM_INSTALLATION) }),
  });

  const answer = await aCallback({ installationId: VICTIM_INSTALLATION });
  const body = await answer.text();
  const receipt = receiptIn(body);

  assert.ok(receipt, 'a verified user should reach a receipt');

  const payload = JSON.parse(atob(receipt.split('.')[0]
    .replace(/-/g, '+').replace(/_/g, '/')));
  assert.equal(payload.status, 'connected');
  assert.equal(payload.installation.installation_id, VICTIM_INSTALLATION);

  const claims = await openGrant(SECRET, payload.grant);
  assert.equal(claims.i, VICTIM_INSTALLATION);
  assert.equal(claims.k, ATTACKER_KEY,
    'the grant names the key from the state it was started with');
});

test('a user with many installations is paged through, not truncated',
  async () => {
    // 100 on the first page means there may be more. Stopping there would
    // refuse a legitimate connection for somebody in a lot of organisations.
    const first = ownedBy(...Array.from({ length: 100 }, (_, at) => 1000 + at));
    stubFetch({
      'login/oauth/access_token': () => ({ body: { access_token: 'gho_x' } }),
      '/user/installations': (url) => ({
        body: url.includes('page=2') ? ownedBy(VICTIM_INSTALLATION) : first,
      }),
    });

    const answer = await aCallback({ installationId: VICTIM_INSTALLATION });

    assert.ok(receiptIn(await answer.text()));
  });

// --------------------------------------------------------------------------- //
// the rest of the boundary
// --------------------------------------------------------------------------- //

test('an invalid OAuth code is refused', async () => {
  // GitHub answers 200 with an `error` field rather than a 4xx, which is the
  // trap: reading the status alone turns a bad code into an empty token.
  stubFetch({
    'login/oauth/access_token': () => ({
      body: { error: 'bad_verification_code',
              error_description: 'The code passed is incorrect or expired.' },
    }),
  });

  const answer = await aCallback({ code: 'a-stolen-or-stale-code' });
  const body = await answer.text();

  assert.ok(body.includes('could not be confirmed'));
  assert.equal(receiptIn(body), null);
  assert.ok(!body.includes('g1.'));
});

test('a forged state is refused', async () => {
  stubFetch({});
  const forged = `u1.${btoa(JSON.stringify({
    v: 1, i: VICTIM_INSTALLATION, k: ATTACKER_KEY, n: 'n',
    c: 'whatever', e: Math.floor(Date.now() / 1000) + 600,
  })).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}.deadbeef`;

  const answer = await getRequest(
    `${BASE}/callback?code=a-code&state=${encodeURIComponent(forged)}`,
    { cookie: `${COOKIE}=a-verifier` });

  assert.ok((await answer.text()).includes('expired'));
  assert.equal(seen.length, 0, 'no code may be exchanged for a state we did not sign');
});

test('an expired state is refused', async () => {
  stubFetch({});
  const answer = await aCallback({ now: Date.now() - 601_000 });

  assert.ok((await answer.text()).includes('expired'));
  assert.equal(seen.length, 0);
});

test('a state signed with a different secret is refused', async () => {
  stubFetch({});
  const state = await issueState('a-different-deployment-secret', {
    installationId: VICTIM_INSTALLATION, publicKey: ATTACKER_KEY,
    nonce: 'n', challenge: await challengeFor('v'),
  });

  const answer = await getRequest(
    `${BASE}/callback?code=a-code&state=${encodeURIComponent(state)}`,
    { cookie: `${COOKIE}=v` });

  assert.ok((await answer.text()).includes('expired'));
  assert.equal(seen.length, 0);
});

test('an edited state is refused', async () => {
  // The one edit worth making: point a valid state at a different
  // installation. The signature covers the payload, so it cannot be done.
  stubFetch({});
  const state = await issueState(SECRET, {
    installationId: 111, publicKey: ATTACKER_KEY, nonce: 'n',
    challenge: await challengeFor('v'),
  });
  const [prefix, payload, signature] = state.split('.');
  const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
  decoded.i = VICTIM_INSTALLATION;
  const edited = btoa(JSON.stringify(decoded))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  const answer = await getRequest(
    `${BASE}/callback?code=a-code`
    + `&state=${encodeURIComponent(`${prefix}.${edited}.${signature}`)}`,
    { cookie: `${COOKIE}=v` });

  assert.ok((await answer.text()).includes('expired'));
  assert.equal(seen.length, 0);
});

test('a PKCE mismatch is refused', async () => {
  // A state fed to somebody else's browser. The state is genuine; the cookie
  // that goes with it is not there.
  stubFetch({});
  const answer = await aCallback({
    verifier: 'the-verifier-the-flow-was-started-with',
    cookie: 'a-verifier-from-some-other-flow',
  });

  assert.ok((await answer.text()).includes('same browser'));
  assert.equal(seen.length, 0, 'a code must not be exchanged without the verifier');
});

test('a missing cookie is refused', async () => {
  stubFetch({});
  const answer = await aCallback({ cookie: null });

  assert.ok((await answer.text()).includes('same browser'));
  assert.equal(seen.length, 0);
});

test('the verifier is sent to GitHub, not just checked here', async () => {
  // Checking it locally proves the browser is the same one. Sending it is
  // what would let GitHub bind the code too, if and when GitHub verifies it.
  let sent = null;
  stubFetch({
    'login/oauth/access_token': (url, options) => {
      sent = JSON.parse(options.body);
      return { body: { access_token: 'gho_x' } };
    },
    '/user/installations': () => ({ body: ownedBy(VICTIM_INSTALLATION) }),
  });

  await aCallback({ verifier: 'a-known-verifier-value-for-this-test' });

  assert.equal(sent.code_verifier, 'a-known-verifier-value-for-this-test');
  assert.equal(sent.client_secret, ENV.GITHUB_APP_CLIENT_SECRET);
});

test('a callback with no code is refused', async () => {
  stubFetch({});
  const state = await issueState(SECRET, {
    installationId: VICTIM_INSTALLATION, publicKey: ATTACKER_KEY, nonce: 'n',
    challenge: await challengeFor('v'),
  });

  const answer = await getRequest(
    `${BASE}/callback?state=${encodeURIComponent(state)}`,
    { cookie: `${COOKIE}=v` });

  assert.ok((await answer.text()).includes('not completed'));
  assert.equal(seen.length, 0);
});

// --------------------------------------------------------------------------- //
// what must never leak
// --------------------------------------------------------------------------- //

test('the user access token never reaches the page or the agent', async () => {
  const token = 'gho_a_user_access_token_that_must_not_travel';
  stubFetch({
    'login/oauth/access_token': () => ({ body: { access_token: token } }),
    '/user/installations': () => ({ body: ownedBy(VICTIM_INSTALLATION) }),
  });

  const answer = await aCallback({ installationId: VICTIM_INSTALLATION });
  const body = await answer.text();

  assert.ok(!body.includes(token), 'not in the page');
  assert.ok(!body.includes('gho_'), 'not even a prefix of one');

  // And not in the receipt, which is the thing that actually travels to the
  // agent. The receipt is signed but not encrypted, so anything in it is
  // readable by whoever holds it.
  const receipt = receiptIn(body);
  const payload = atob(receipt.split('.')[0]
    .replace(/-/g, '+').replace(/_/g, '/'));
  assert.ok(!payload.includes(token));
  assert.ok(!payload.includes('gho_'));
  assert.ok(!payload.includes(ENV.GITHUB_APP_CLIENT_SECRET));
});

test('the client secret never reaches a browser', async () => {
  stubFetch({
    'login/oauth/access_token': () => ({ body: { access_token: 'gho_x' } }),
    '/user/installations': () => ({ body: ownedBy(VICTIM_INSTALLATION) }),
  });

  const answer = await aCallback({});
  const body = await answer.text();

  assert.ok(!body.includes(ENV.GITHUB_APP_CLIENT_SECRET));
  assert.ok(!body.includes(SECRET));
});

test('the verifier cookie is cleared however the callback ends', async () => {
  // Both paths: the refusal and the success. A verifier left in the browser
  // outlives the flow it belonged to.
  stubFetch({});
  const refused = await aCallback({ cookie: null });
  assert.ok(refused.headers.get('set-cookie').includes('Max-Age=0'));

  stubFetch({
    'login/oauth/access_token': () => ({ body: { access_token: 'gho_x' } }),
    '/user/installations': () => ({ body: ownedBy(VICTIM_INSTALLATION) }),
  });
  const allowed = await aCallback({});
  assert.ok(allowed.headers.get('set-cookie').includes('Max-Age=0'));
});

test('the cookie carrying the verifier is not reachable by script', async () => {
  stubFetch({});
  const { answer } = await throughSetup(VICTIM_INSTALLATION);
  const cookie = answer.headers.get('set-cookie');

  assert.ok(cookie.includes('HttpOnly'));
  assert.ok(cookie.includes('Secure'));
  // Lax, not Strict: the callback arrives as a navigation from github.com,
  // and Strict would withhold the cookie on exactly that hop.
  assert.ok(cookie.includes('SameSite=Lax'));
  assert.ok(cookie.includes('Path=/api/integrations/github'));
});

// --------------------------------------------------------------------------- //
// configuration
// --------------------------------------------------------------------------- //

test('without OAuth credentials, no connection is handed out', async () => {
  // A deployment that cannot check who somebody is must refuse rather than
  // fall back to the behaviour this whole file exists to remove.
  stubFetch({});
  const started = await issue(SECRET, { publicKey: ATTACKER_KEY });
  const answer = await handle(
    new Request(`${BASE}/setup?installation_id=${VICTIM_INSTALLATION}`
      + `&state=${encodeURIComponent(started.state)}`),
    { GITHUB_APP_WEBHOOK_SECRET: SECRET });

  const body = await answer.text();
  assert.ok(body.includes('cannot verify who you are'));
  assert.equal(receiptIn(body), null);
  assert.ok(!body.includes('g1.'));
});

test('a cancelled installation still ends without a grant', async () => {
  stubFetch({});
  const started = await issue(SECRET, { publicKey: ATTACKER_KEY });
  const answer = await getRequest(
    `${BASE}/setup?setup_action=cancel`
    + `&state=${encodeURIComponent(started.state)}`);

  const body = await answer.text();
  const receipt = receiptIn(body);
  assert.ok(receipt, 'the terminal still needs to be told');

  const payload = JSON.parse(atob(receipt.split('.')[0]
    .replace(/-/g, '+').replace(/_/g, '/')));
  assert.equal(payload.status, 'cancelled');
  assert.equal(payload.grant, undefined);
});
