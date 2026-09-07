/**
 * The one contract that shipped broken, pinned so it cannot ship broken again.
 *
 * `POST /install` returns the URL a person's browser is sent to. For weeks it
 * returned `https://github.com/apps/comodor/installations/new`, which is
 * well-formed, is not the app — `github.com/apps/comodor` is a 404 — and was
 * produced by `env.GITHUB_APP_SLUG || 'comodor'` on a deployment where the
 * variable was never set. Every test was green, because every fixture said
 * `comodor` too.
 *
 * So this file does not check that the URL *looks* like an install link. It
 * checks the four things that make it the right one — scheme, host, path and
 * the state the Worker itself issued — against the production identity written
 * down in `app-identity.test-support.mjs`. A test that only asserted
 * `includes('/installations/new')` would have passed throughout the outage.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { APP_SLUG } from './app-identity.test-support.mjs';
import { PROTOCOL_RECEIPT, PROTOCOL_RENDEZVOUS } from './config.js';
import { handle } from './routes.js';

const SECRET = 'a-deployment-secret-for-tests';
const BASE = 'https://comodor.ai/api/integrations/github';

/** A real P-256 public key, raw and base64url, as the endpoint requires. */
async function aPublicKey() {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const raw = await crypto.subtle.exportKey('raw', pair.publicKey);
  let binary = '';
  for (const byte of new Uint8Array(raw)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function install(env, body) {
  const answer = await handle(new Request(`${BASE}/install`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }), env);
  return { status: answer.status, body: await answer.json() };
}

const configured = {
  GITHUB_APP_WEBHOOK_SECRET: SECRET,
  GITHUB_APP_SLUG: APP_SLUG,
};

test('the install URL names the production app, exactly', async () => {
  const publicKey = await aPublicKey();
  const { status, body } = await install(configured, { public_key: publicKey });

  assert.equal(status, 200);

  const url = new URL(body.url);
  assert.equal(url.protocol, 'https:');
  assert.equal(url.host, 'github.com');
  assert.equal(url.pathname, `/apps/${APP_SLUG}/installations/new`);

  // The state in the URL is the one the Worker issued, not a second one.
  // GitHub echoes this back to `setup`, and a mismatch would mean the browser
  // arriving with a state the terminal is not waiting on.
  assert.equal(url.searchParams.get('state'), body.state);
  assert.ok(body.state, 'a flow with no state cannot be tied to a terminal');
  assert.ok(body.nonce, 'the agent needs a correlation id');
  assert.ok(body.expires_in > 0, 'a deadline the client can wait against');
});

test('the app slug it uses is not the one that shipped broken', async () => {
  const publicKey = await aPublicKey();
  const { body } = await install(configured, { public_key: publicKey });

  assert.ok(!body.url.includes('/apps/comodor/'),
    'github.com/apps/comodor is a 404; that is the URL this test exists for');
});

test('a deployment with no app name refuses rather than guessing', async () => {
  const publicKey = await aPublicKey();
  const { status, body } = await install(
    { GITHUB_APP_WEBHOOK_SECRET: SECRET }, { public_key: publicKey });

  // 503 and no URL. A fallback here is what produced the broken link: it turns
  // a missing variable, which is loud and fixed in a minute, into a wrong
  // answer that looks right and is discovered by a person following it.
  assert.equal(status, 503);
  assert.ok(!body.url, 'a misconfigured deployment must not hand out a link');
});

test('an app name that is not a URL segment is refused', async () => {
  const publicKey = await aPublicKey();
  const { status } = await install(
    { ...configured, GITHUB_APP_SLUG: 'comodor/agent' },
    { public_key: publicKey });

  assert.equal(status, 503);
});

test('a flow still needs a client key', async () => {
  const { status } = await install(configured, {});

  assert.equal(status, 400);
});

test('an old client gets the receipt protocol without asking', async () => {
  const publicKey = await aPublicKey();
  const { body } = await install(configured, { public_key: publicKey });

  assert.equal(body.protocol, PROTOCOL_RECEIPT);
});

test('a new client on a deployment that can hold results gets the automatic one',
     async () => {
  const publicKey = await aPublicKey();
  const { body } = await install(
    { ...configured, CONNECTION_FLOW: {} },
    { public_key: publicKey, protocol: PROTOCOL_RENDEZVOUS });

  assert.equal(body.protocol, PROTOCOL_RENDEZVOUS);
});

test('a new client on a deployment that cannot is told so, and still works',
     async () => {
  const publicKey = await aPublicKey();
  const { body } = await install(configured,
    { public_key: publicKey, protocol: PROTOCOL_RENDEZVOUS });

  // Answered with what it actually got, so it can fall back rather than poll
  // an endpoint that will never have anything for it.
  assert.equal(body.protocol, PROTOCOL_RECEIPT);
  assert.ok(body.url, 'and the flow still starts');
});

test('an unknown protocol is read as the oldest one', async () => {
  const publicKey = await aPublicKey();
  const { body } = await install(configured,
    { public_key: publicKey, protocol: 99 });

  assert.equal(body.protocol, PROTOCOL_RECEIPT);
});
