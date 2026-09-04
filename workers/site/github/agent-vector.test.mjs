/**
 * The two halves, checked against each other.
 *
 * Everything else in this directory tests the Worker against itself: a grant
 * this file issued, a signature this file made. That proves the Worker is
 * self-consistent and proves nothing about whether the *agent* can talk to it.
 * The agent signs in Python, with curve arithmetic written out because the
 * project ships one dependency — a completely separate implementation, and the
 * place where a mismatch would be invisible until the first real request.
 *
 * So the fixtures below were produced by the agent, at
 * `src/comodor/github/identity.py`, and are pasted here verbatim. They are
 * fixed rather than generated because the agent's signing is deterministic
 * (RFC 6979): the same key and the same message always give the same bytes, so
 * a vector is possible and a drift on either side breaks this test rather than
 * production.
 *
 * To regenerate, if the signed layout is ever deliberately changed:
 *
 *   python -c "from comodor.github import identity; ..."   (see the test below
 *   for the exact message; the agent's own test file pins the same vector)
 */

import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import { authorise, fingerprint, issueGrant, openGrant, signedPayload } from './grant.js';

/** The secret the fixtures were made under. Not a real one. */
const SECRET = 'a-test-secret';

/** The agent's public key for this connection, as `install` would send it. */
const PUBLIC_KEY = 'BGD-1LolWp0xyWHrdMY1bWjASbiSO2H6bOZpYi5g8p'
  + '-2eQP-EAi4vJmkGunpVii8ZPLxsgwtfp9Rd6PClNRGIpk';

/** The account the installation sits on, and who connected it. */
const ACCOUNT = { id: 4242, type: 'Organization' };
const ACTOR = { id: 9, login: 'ifekri' };

/** The grant this Worker issues for it, at a fixed moment. */
const GRANT = 'g2.eyJ2IjoyLCJpIjo3LCJhaSI6NDI0MiwiYXQiOiJPcmdhbml6YXRpb24iLC'
  + 'J1aSI6OSwidWwiOiJpZmVrcmkiLCJrIjoiQkdELTFMb2xXcDB4eVdIcmRNWTFiV2pBU2JpU0'
  + '8ySDZiT1pwWWk1ZzhwLTJlUVAtRUFpNHZKbWtHdW5wVmlpOFpQTHhzZ3d0ZnA5UmQ2UENsTl'
  + 'JHSXBrIiwiZiI6InNZdUd6aE9KNUczb2VxU2xFeHpvUEJGZy1qUEFoNnNWdUdOWFRUSFlfen'
  + 'ciLCJpYXQiOjE3MDAwMDAwMDB9.8f70aefea5aad3bedc753f64b2cb13fc4814800d3daeaa'
  + '42a42dc3990c55efa2';

const TIMESTAMP = 1700000000;
const NONCE = 'a-nonce-of-sufficient-length';

/** What the agent signed over exactly those values. */
const SIGNATURE = 'e0PiMrkDpPn7TLQQtG3jQXTbcouAHn1GtIAXzSmaS2kMFva1P3A3'
  + 'MLAwn59fc9vMsD0amlSwx3B1JcmH05Umwg';

/** The instant the fixtures are fresh at. */
const WHEN = TIMESTAMP * 1000;

test('this Worker issues exactly the grant the agent was given', async () => {
  // If this drifts, every deployed agent's stored grant stops opening. It is
  // the one value in the system that outlives a single request.
  const made = await issueGrant(SECRET, {
    installationId: 7, account: ACCOUNT, actor: ACTOR,
    publicKey: PUBLIC_KEY, now: WHEN,
  });

  assert.equal(made, GRANT);
});

test('a request signed by the agent is authorised', async () => {
  // The whole point. A signature made by hand-written Python curve arithmetic,
  // verified by the runtime's own ECDSA, over a payload both sides built
  // independently from the same rule.
  const who = await authorise(SECRET, {
    grant: GRANT, timestamp: TIMESTAMP, nonce: NONCE, signature: SIGNATURE,
  }, 'token', { now: WHEN });

  assert.equal(who.installationId, 7);
  assert.equal(who.fingerprint, await fingerprint(PUBLIC_KEY));
});

test('both sides build the same bytes to sign', async () => {
  // Spelled out rather than imported, so a change to `signedPayload` that the
  // agent does not also make is caught here.
  const expected = [
    'comodor-github-v1', 'token', GRANT, String(TIMESTAMP), NONCE,
  ].join('\n');

  assert.equal(signedPayload({
    grant: GRANT, timestamp: TIMESTAMP, nonce: NONCE, action: 'token',
  }), expected);
});

test('the grant the agent stores names the key the agent holds', async () => {
  const claims = await openGrant(SECRET, GRANT);

  assert.equal(claims.k, PUBLIC_KEY);
  assert.equal(claims.i, 7);
  assert.equal(claims.f, await fingerprint(PUBLIC_KEY));
  // The fields the entitlement check reads. If these ever stop travelling,
  // a grant becomes uncheckable and therefore permanent.
  assert.equal(claims.ai, ACCOUNT.id);
  assert.equal(claims.at, ACCOUNT.type);
  assert.equal(claims.ui, ACTOR.id);
  assert.equal(claims.ul, ACTOR.login);
});

test('that same agent signature is refused at the other endpoint', async () => {
  // A real signature, a real grant, the wrong action. If the action were not
  // in the signed bytes, a signature captured from the harmless endpoint would
  // be a signature for the one that mints credentials.
  await assert.rejects(
    authorise(SECRET, {
      grant: GRANT, timestamp: TIMESTAMP, nonce: NONCE, signature: SIGNATURE,
    }, 'verify', { now: WHEN }),
    (error) => error.status === 401,
  );
});

test('that same agent signature stops working once it is stale', async () => {
  await assert.rejects(
    authorise(SECRET, {
      grant: GRANT, timestamp: TIMESTAMP, nonce: NONCE, signature: SIGNATURE,
    }, 'token', { now: WHEN + 121_000 }),
    (error) => error.status === 401,
  );
});

test('an agent signature does not carry over to another secret', async () => {
  // The grant is signed with the Worker's secret. A different deployment must
  // not accept a grant issued by this one.
  await assert.rejects(
    authorise('a-different-secret', {
      grant: GRANT, timestamp: TIMESTAMP, nonce: NONCE, signature: SIGNATURE,
    }, 'token', { now: WHEN }),
    (error) => error.status === 401,
  );
});

test('an installation id in the body changes nothing', async () => {
  // The original hole, with a real signature attached. The id is read out of
  // the grant, so adding one to the body is a field that goes nowhere.
  const who = await authorise(SECRET, {
    grant: GRANT, timestamp: TIMESTAMP, nonce: NONCE, signature: SIGNATURE,
    installation_id: 99999,
  }, 'token', { now: WHEN });

  assert.equal(who.installationId, 7);
});
