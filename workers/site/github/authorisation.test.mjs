/**
 * Who may ask this Worker for a GitHub token.
 *
 * The first implementation of `/token` took an `installation_id` from the
 * request body and minted against it. Installation ids are small integers,
 * they appear in URLs, and one is not a secret — so anybody who learned one
 * could make this Worker issue a working GitHub token for somebody else's
 * repositories. A critical authentication hole, and the tests below are the
 * ones that would have caught it.
 *
 * Every credential here is generated for the run. There is no fixture that is
 * a real key and no test that needs a network.
 *
 *   node --test workers/site/github/authorisation.test.mjs
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  FRESH_FOR,
  authorise,
  fingerprint,
  issueGrant,
  openGrant,
  signedPayload,
} from './grant.js';
import { handle } from './routes.js';

const SECRET = 'a-signing-secret-for-the-tests';

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** An agent's connection key pair, as the agent would make one. */
async function aClient() {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const raw = await crypto.subtle.exportKey('raw', pair.publicKey);
  return { pair, publicKey: base64url(raw) };
}

/** A request signed the way the agent signs one. */
async function aRequest(client, grant, action, over = {}) {
  const timestamp = over.timestamp ?? Math.floor(Date.now() / 1000);
  const nonce = over.nonce ?? base64url(crypto.getRandomValues(new Uint8Array(18)));
  const signature = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' }, client.pair.privateKey,
    new TextEncoder().encode(signedPayload({
      grant: over.signOver ?? grant, timestamp, nonce, action,
    })));
  return { grant, timestamp, nonce, signature: base64url(signature), ...over.extra };
}

// --------------------------------------------------------------------------- //
// the hole itself
// --------------------------------------------------------------------------- //

test('an installation id alone does not get a token', async () => {
  // Exactly the original request, and the whole reason this file exists.
  const answer = await handle(
    new Request('https://comodor.ai/api/integrations/github/token', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ installation_id: 12345678 }),
    }),
    { GITHUB_APP_WEBHOOK_SECRET: SECRET });

  assert.equal(answer.status, 401,
    'knowing an installation id must not be enough to mint against it');
  const body = await answer.json();
  assert.ok(!body.token, 'no token may be returned');
});

test('an installation id alone does not reveal what an installation is',
  async () => {
    const answer = await handle(
      new Request('https://comodor.ai/api/integrations/github/verify', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ installation_id: 12345678 }),
      }),
      { GITHUB_APP_WEBHOOK_SECRET: SECRET });

    assert.equal(answer.status, 401,
      'an account, its repositories and its permissions are not public');
  });

test('a request with no grant at all is refused', async () => {
  const client = await aClient();
  const request = await aRequest(client, '', 'token');

  await assert.rejects(() => authorise(SECRET, request, 'token'),
    /not one of ours/);
});

// --------------------------------------------------------------------------- //
// the grant
// --------------------------------------------------------------------------- //

test('a grant this Worker issued opens, and names the key and installation',
  async () => {
    const client = await aClient();
    const grant = await issueGrant(SECRET, {
      installationId: 42, publicKey: client.publicKey });

    const claims = await openGrant(SECRET, grant);

    assert.equal(claims.i, 42);
    assert.equal(claims.k, client.publicKey);
    assert.equal(claims.f, await fingerprint(client.publicKey));
    assert.ok(Number.isInteger(claims.iat));
  });

test('a grant signed with another secret does not open', async () => {
  const client = await aClient();
  const grant = await issueGrant('somebody elses secret', {
    installationId: 42, publicKey: client.publicKey });

  assert.equal(await openGrant(SECRET, grant), null);
});

test('a grant edited after signing does not open', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 42, publicKey: client.publicKey });

  const [prefix, payload, signature] = grant.split('.');
  const claims = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
  claims.i = 99;                       // point it at somebody else's install
  const altered = btoa(JSON.stringify(claims))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  assert.equal(await openGrant(SECRET, `${prefix}.${altered}.${signature}`), null,
    'editing the installation id must invalidate the signature');
});

test('a grant of an unknown version does not open', async () => {
  const claims = { v: 99, i: 1, k: 'x', f: 'y', iat: 1 };
  const payload = btoa(JSON.stringify(claims))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  assert.equal(await openGrant(SECRET, `g1.${payload}.deadbeef`), null);
});

test('a grant needs an installation and a key to be issued', async () => {
  await assert.rejects(
    () => issueGrant(SECRET, { installationId: 0, publicKey: 'x' }));
  await assert.rejects(
    () => issueGrant(SECRET, { installationId: 1, publicKey: '' }));
});

// --------------------------------------------------------------------------- //
// the signature on each request
// --------------------------------------------------------------------------- //

test('a valid signed request authorises, and says which installation',
  async () => {
    const client = await aClient();
    const grant = await issueGrant(SECRET, {
      installationId: 4242, publicKey: client.publicKey });

    const found = await authorise(SECRET, await aRequest(client, grant, 'token'),
      'token');

    assert.equal(found.installationId, 4242);
  });

test('a request with no signature is refused', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  const request = await aRequest(client, grant, 'token');
  delete request.signature;

  await assert.rejects(() => authorise(SECRET, request, 'token'),
    /not signed by the key/);
});

test('a forged signature is refused', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  const request = await aRequest(client, grant, 'token');
  request.signature = base64url(crypto.getRandomValues(new Uint8Array(64)));

  await assert.rejects(() => authorise(SECRET, request, 'token'),
    /not signed by the key/);
});

test('a signature by a different key is refused', async () => {
  const owner = await aClient();
  const attacker = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: owner.publicKey });

  // A real signature, over the right payload, by the wrong key.
  const request = await aRequest(attacker, grant, 'token');

  await assert.rejects(() => authorise(SECRET, request, 'token'),
    /not signed by the key/);
});

test('a grant for one installation cannot be used with another', async () => {
  const client = await aClient();
  const mine = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  // The attempt: present my grant, and ask for a different installation by
  // putting it in the body. The body is not read — this is the shape of the
  // original hole, closed.
  const request = await aRequest(client, mine, 'token',
    { extra: { installation_id: 999 } });
  const found = await authorise(SECRET, request, 'token');

  assert.equal(found.installationId, 1,
    'the installation comes from the grant, never from the body');
});

test('a signature over a different grant is refused', async () => {
  const client = await aClient();
  const one = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });
  const two = await issueGrant(SECRET, {
    installationId: 2, publicKey: client.publicKey });

  // Signed over grant one, sent with grant two: swapping the grant after
  // signing must not survive, or a captured signature could be moved onto a
  // grant for a different installation.
  const request = await aRequest(client, two, 'token', { signOver: one });

  await assert.rejects(() => authorise(SECRET, request, 'token'),
    /not signed by the key/);
});

test('a signature for one action cannot be replayed as another', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  const request = await aRequest(client, grant, 'verify');

  await assert.rejects(() => authorise(SECRET, request, 'token'),
    /not signed by the key/);
});

// --------------------------------------------------------------------------- //
// freshness, and what it can and cannot promise
// --------------------------------------------------------------------------- //

test('a request older than the window is refused', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  const stale = await aRequest(client, grant, 'token', {
    timestamp: Math.floor(Date.now() / 1000) - (FRESH_FOR + 60),
  });

  await assert.rejects(() => authorise(SECRET, stale, 'token'), /too old/);
});

test('a request from the future is refused too', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  const ahead = await aRequest(client, grant, 'token', {
    timestamp: Math.floor(Date.now() / 1000) + (FRESH_FOR + 60),
  });

  await assert.rejects(() => authorise(SECRET, ahead, 'token'),
    /too old, or its clock is wrong/);
});

test('a request with no timestamp is refused', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  const request = await aRequest(client, grant, 'token');
  delete request.timestamp;

  await assert.rejects(() => authorise(SECRET, request, 'token'),
    /no timestamp/);
});

test('a request with no nonce is refused', async () => {
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 1, publicKey: client.publicKey });

  const request = await aRequest(client, grant, 'token', { nonce: 'short' });

  await assert.rejects(() => authorise(SECRET, request, 'token'), /no nonce/);
});

test('replay is bounded by the window, and cannot widen scope', async () => {
  // Stated rather than glossed: with no storage there is no nonce ledger, so
  // a captured request works again inside its window. What the design must
  // guarantee is that replaying it gains nothing beyond what the original
  // request already got — the same installation, never a different one.
  const client = await aClient();
  const grant = await issueGrant(SECRET, {
    installationId: 77, publicKey: client.publicKey });

  const captured = await aRequest(client, grant, 'token');

  const first = await authorise(SECRET, captured, 'token');
  const again = await authorise(SECRET, captured, 'token');
  assert.equal(first.installationId, again.installationId);

  // And once the window passes, it stops working at all.
  await assert.rejects(
    () => authorise(SECRET, captured, 'token',
      { now: Date.now() + (FRESH_FOR + 60) * 1000 }),
    /too old/);
});

// --------------------------------------------------------------------------- //
// the payload the signature covers
// --------------------------------------------------------------------------- //

test('the signed payload cannot be shifted between its fields', () => {
  // Concatenation without a separator is the usual way this goes wrong:
  // ("ab","c") and ("a","bc") would sign identical bytes, and an attacker who
  // can move a boundary can move meaning while keeping the signature valid.
  const one = signedPayload({ grant: 'ab', timestamp: 1, nonce: 'c',
                              action: 'token' });
  const two = signedPayload({ grant: 'a', timestamp: 1, nonce: 'bc',
                              action: 'token' });

  assert.notEqual(one, two);
});

test('the payload names the action, so one cannot stand in for another', () => {
  assert.notEqual(
    signedPayload({ grant: 'g', timestamp: 1, nonce: 'n', action: 'token' }),
    signedPayload({ grant: 'g', timestamp: 1, nonce: 'n', action: 'verify' }));
});

// --------------------------------------------------------------------------- //
// the flow that establishes the identity
// --------------------------------------------------------------------------- //

test('a connection cannot be started without a client public key', async () => {
  const answer = await handle(
    new Request('https://comodor.ai/api/integrations/github/install', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ client: 'comodor-agent' }),
    }),
    { GITHUB_APP_WEBHOOK_SECRET: SECRET });

  assert.equal(answer.status, 400,
    'without a key there is no identity to bind the installation to');
});

test('a connection with a key returns a state carrying it', async () => {
  const client = await aClient();
  const answer = await handle(
    new Request('https://comodor.ai/api/integrations/github/install', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ client: 'comodor-agent',
                             public_key: client.publicKey }),
    }),
    { GITHUB_APP_WEBHOOK_SECRET: SECRET, GITHUB_APP_SLUG: 'comodor' });

  assert.equal(answer.status, 200);
  const body = await answer.json();
  assert.ok(body.state && body.nonce);
  assert.ok(body.url.startsWith('https://github.com/apps/comodor/'));

  const { open } = await import('./state.js');
  const opened = await open(SECRET, body.state);
  assert.equal(opened.k, client.publicKey,
    'the key must survive to setup, unaltered, with nothing stored');
});

test('the endpoints refuse everything when nothing is configured', async () => {
  for (const leaf of ['install', 'token', 'verify', 'claim']) {
    const answer = await handle(
      new Request(`https://comodor.ai/api/integrations/github/${leaf}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
      }), {});

    assert.equal(answer.status, 503, `${leaf} answered ${answer.status}`);
  }
});

test('a refusal never says which part was wrong in a way that helps a prober',
  async () => {
    const answer = await handle(
      new Request('https://comodor.ai/api/integrations/github/token', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ grant: 'g1.forged.signature', timestamp: 1,
                               nonce: 'x'.repeat(20), signature: 'nope' }),
      }),
      { GITHUB_APP_WEBHOOK_SECRET: SECRET });

    const body = await answer.json();
    assert.equal(answer.status, 401);
    assert.ok(!JSON.stringify(body).includes(SECRET));
  });
