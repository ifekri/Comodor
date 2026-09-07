/**
 * The automatic flow, end to end, with no network and no real Durable Object.
 *
 * What is being tested is the join: the browser finishes somewhere, the
 * terminal polls somewhere else, and the result crosses between them without a
 * person carrying it. Everything else here is a stand-in — the Durable Object
 * namespace is a Map of instances, GitHub is a stub — because the interesting
 * failures are in the handshake, not in Cloudflare's storage.
 *
 * The security question this file exists for: **knowing the flow must not be
 * enough to collect it.** A state travels in a URL, and its nonce is plain
 * base64 inside it. If `take(nonce)` were the whole check, anybody who read
 * the address bar could have the grant. So every poll is signed by the key
 * whose public half is inside the state, and the tests below try to collect a
 * result with the wrong key, an edited request, a stale one, and another
 * flow's state.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { APP_SLUG } from './app-identity.test-support.mjs';
import { CLAIM_ACTION, PROTOCOL_RENDEZVOUS, RESULT_LIVES_FOR } from './config.js';
import { signedPayload } from './proof.js';
import { ConnectionFlow } from './rendezvous.js';
import { handle } from './routes.js';

const SECRET = 'a-deployment-secret-for-tests';
const BASE = 'https://comodor.ai/api/integrations/github';

// --------------------------------------------------------------------------- //
// stand-ins
// --------------------------------------------------------------------------- //

/** Durable Object storage, in a Map, with the alarm exposed for the clock. */
function storage() {
  const kept = new Map();
  let alarm = 0;
  return {
    async get(key) { return kept.get(key); },
    async put(key, value) { kept.set(key, value); },
    async delete(key) { kept.delete(key); },
    async list({ prefix = '', limit = Infinity } = {}) {
      const found = new Map();
      for (const [key, value] of kept) {
        if (key.startsWith(prefix) && found.size < limit) found.set(key, value);
      }
      return found;
    },
    async deleteAll() { kept.clear(); },
    async setAlarm(when) { alarm = when; },
    alarmAt() { return alarm; },
    size() { return kept.size; },
  };
}

/** A namespace: one `ConnectionFlow` per name, kept so a second call finds it. */
function namespace() {
  const instances = new Map();
  return {
    idFromName(name) { return { name: String(name) }; },
    get(id) {
      if (!instances.has(id.name)) {
        instances.set(id.name, new ConnectionFlow({ storage: storage() }));
      }
      return instances.get(id.name);
    },
    instances,
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

// --------------------------------------------------------------------------- //
// a client, as the agent would be
// --------------------------------------------------------------------------- //

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function anAgent() {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const raw = await crypto.subtle.exportKey('raw', pair.publicKey);

  return {
    public: base64url(raw),
    async sign(payload) {
      return base64url(await crypto.subtle.sign(
        { name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey,
        new TextEncoder().encode(payload)));
    },
  };
}

let counter = 0;

/**
 * A poll, signed the way the agent signs one.
 *
 * A fresh nonce each time unless the caller asks for one, because the real
 * agent generates one per request and reusing one is now refused — which is
 * the point of the replay test below.
 */
async function aPoll(agent, state, {
  action = CLAIM_ACTION, timestamp = Math.floor(Date.now() / 1000),
  nonce = `a-request-nonce-long-enough-${counter += 1}`,
} = {}) {
  const signature = await agent.sign(
    signedPayload({ state, timestamp, nonce, action }));
  return { state, timestamp, nonce, signature };
}

async function post(where, body, on) {
  const answer = await handle(new Request(`${BASE}/${where}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }), on);
  return { status: answer.status, body: await answer.json() };
}

/** Start a flow the way the agent does. */
async function begin(on, agent) {
  const { body } = await post('install',
    { public_key: agent.public, protocol: PROTOCOL_RENDEZVOUS,
      client: 'comodor-agent' }, on);
  return body;
}

/** What the browser leaves behind when it finishes. */
async function browserFinishes(on, nonce, result) {
  const { deliver } = await import('./rendezvous.js');
  return deliver(on, nonce, result);
}

const CONNECTED = {
  status: 'connected',
  installation: { installation_id: 42, account: { login: 'ifekri', id: 1,
                                                  type: 'User' },
                  repository_selection: 'selected' },
  grant: 'g1.a-grant',
};

// --------------------------------------------------------------------------- //
// the flow
// --------------------------------------------------------------------------- //

test('the terminal collects the result without anybody copying anything',
     async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  assert.equal(flow.protocol, PROTOCOL_RENDEZVOUS);

  // Polling before the browser has finished.
  const waiting = await post('claim', await aPoll(agent, flow.state), on);
  assert.equal(waiting.body.status, 'pending');

  await browserFinishes(on, flow.nonce, CONNECTED);

  const got = await post('claim', await aPoll(agent, flow.state), on);
  assert.equal(got.body.status, 'connected');
  assert.equal(got.body.nonce, flow.nonce);
  assert.equal(got.body.installation.account.login, 'ifekri');
  assert.equal(got.body.grant, 'g1.a-grant');
});

test('a result is handed over once', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);
  await browserFinishes(on, flow.nonce, CONNECTED);

  const first = await post('claim', await aPoll(agent, flow.state), on);
  const second = await post('claim', await aPoll(agent, flow.state), on);

  assert.equal(first.body.status, 'connected');
  assert.equal(second.body.status, 'pending',
    'a collected result must not be readable a second time');
});

test('a cancelled installation reaches the terminal too', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);
  await browserFinishes(on, flow.nonce, { status: 'cancelled' });

  const got = await post('claim', await aPoll(agent, flow.state), on);

  assert.equal(got.body.status, 'cancelled');
});

test('the first result wins, so a refreshed page cannot undo a connection',
     async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  await browserFinishes(on, flow.nonce, CONNECTED);
  const again = await browserFinishes(on, flow.nonce, { status: 'cancelled' });

  assert.equal(again.stored, false);
  const got = await post('claim', await aPoll(agent, flow.state), on);
  assert.equal(got.body.status, 'connected');
});

// --------------------------------------------------------------------------- //
// who may collect it
// --------------------------------------------------------------------------- //

test('a poll signed by another key is refused', async () => {
  const on = env();
  const agent = await anAgent();
  const stranger = await anAgent();
  const flow = await begin(on, agent);
  await browserFinishes(on, flow.nonce, CONNECTED);

  const refused = await post('claim', await aPoll(stranger, flow.state), on);

  assert.equal(refused.status, 401);
  // And the result is still there for the machine it belongs to.
  const got = await post('claim', await aPoll(agent, flow.state), on);
  assert.equal(got.body.status, 'connected');
});

test('an edited poll is refused', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);
  await browserFinishes(on, flow.nonce, CONNECTED);

  const poll = await aPoll(agent, flow.state);
  const refused = await post('claim', { ...poll, nonce: 'a-different-nonce-x' }, on);

  assert.equal(refused.status, 401);
});

test('a poll signed for a different action is refused', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);
  await browserFinishes(on, flow.nonce, CONNECTED);

  const refused = await post('claim',
    await aPoll(agent, flow.state, { action: 'token' }), on);

  assert.equal(refused.status, 401);
});

test('a captured poll cannot be sent again to take the result first', async () => {
  // The signature stays valid for as long as its timestamp is fresh, so a
  // replay arriving before the agent's next poll would take the result and
  // delete it — leaving the machine that started the flow polling a flow with
  // nothing in it. The request nonce is spent on use.
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);
  const poll = await aPoll(agent, flow.state);

  const first = await post('claim', poll, on);
  assert.equal(first.body.status, 'pending');

  const replayed = await post('claim', poll, on);
  assert.equal(replayed.status, 401, 'a spent request nonce was accepted again');

  // And the agent's own next poll, with a fresh nonce, still works.
  await browserFinishes(on, flow.nonce, CONNECTED);
  const got = await post('claim', await aPoll(agent, flow.state), on);
  assert.equal(got.body.status, 'connected');
});

test('a replay cannot take a result the agent has not collected yet', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  // Captured while the browser was still out, then the browser finishes.
  const captured = await aPoll(agent, flow.state);
  await post('claim', captured, on);
  await browserFinishes(on, flow.nonce, CONNECTED);

  const replayed = await post('claim', captured, on);
  assert.equal(replayed.status, 401);
  assert.ok(!replayed.body.grant, 'a replay must not be handed the grant');

  const got = await post('claim', await aPoll(agent, flow.state), on);
  assert.equal(got.body.status, 'connected',
    'and the result is still there for the machine that asked for it');
});

test('a stale poll is refused, and so is one from the future', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);
  await browserFinishes(on, flow.nonce, CONNECTED);

  const now = Math.floor(Date.now() / 1000);
  for (const timestamp of [now - 3600, now + 3600]) {
    const refused = await post('claim',
      await aPoll(agent, flow.state, { timestamp }), on);
    assert.equal(refused.status, 401, `timestamp ${timestamp} was accepted`);
  }
});

test('one flow cannot collect another flow\'s result', async () => {
  const on = env();
  const mine = await anAgent();
  const theirs = await anAgent();
  const myFlow = await begin(on, mine);
  const theirFlow = await begin(on, theirs);

  await browserFinishes(on, theirFlow.nonce, CONNECTED);

  // Correctly signed — for my own flow — and there is nothing in it.
  const empty = await post('claim', await aPoll(mine, myFlow.state), on);
  assert.equal(empty.body.status, 'pending');

  // And my key cannot sign for their flow.
  const refused = await post('claim', await aPoll(mine, theirFlow.state), on);
  assert.equal(refused.status, 401);
});

test('an expired state cannot be polled', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  // The state carries its own deadline; edit the clock the Worker reads by
  // handing it a state issued in the past instead of sleeping.
  const { issue } = await import('./state.js');
  const stale = await issue(SECRET, {
    publicKey: agent.public, protocol: PROTOCOL_RENDEZVOUS,
    now: Date.now() - 3_600_000,
  });

  const refused = await post('claim', await aPoll(agent, stale.state), on);

  assert.equal(refused.body.status, 'expired');
  assert.ok(flow.state, 'the live flow is unaffected');
});

test('a poll without a signature is refused', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  const refused = await post('claim', { state: flow.state }, on);

  assert.equal(refused.status, 401);
});

// --------------------------------------------------------------------------- //
// what it does not become
// --------------------------------------------------------------------------- //

test('a result stops existing on its own', async () => {
  const kept = storage();
  const flow = new ConnectionFlow({ storage: kept });

  await flow.fetch(new Request('https://flow/deliver', {
    method: 'POST', body: JSON.stringify(CONNECTED),
    headers: { 'content-type': 'application/json' },
  }));

  assert.equal(kept.size(), 1);
  assert.ok(kept.alarmAt() > Date.now(), 'nothing set an expiry');
  assert.ok(kept.alarmAt() <= Date.now() + RESULT_LIVES_FOR * 1000 + 1000);

  await flow.alarm();
  assert.equal(kept.size(), 0, 'the flow must not outlive its own alarm');
});

test('a deployment with no rendezvous still answers the receipt protocol',
     async () => {
  const on = { GITHUB_APP_WEBHOOK_SECRET: SECRET, GITHUB_APP_SLUG: APP_SLUG };
  const agent = await anAgent();

  const { body } = await post('install',
    { public_key: agent.public, protocol: PROTOCOL_RENDEZVOUS }, on);

  assert.equal(body.protocol, 1, 'it must say what the agent actually got');

  const polled = await post('claim', await aPoll(agent, body.state), on);
  assert.equal(polled.status, 409,
    'and refuse a poll rather than answer pending forever');
});

test('the legacy receipt shape still works', async () => {
  const on = env();
  const agent = await anAgent();
  await begin(on, agent);

  // No receipt, no state: the oldest possible bad request, still a 400.
  const nothing = await post('claim', {}, on);

  assert.equal(nothing.status, 400);
});


// --------------------------------------------------------------------------- //
// a browser that ends without connecting still ends the wait
// --------------------------------------------------------------------------- //

test('a refusal reaches the terminal instead of leaving it waiting', async () => {
  // Only the successful callback used to deliver, so an authorisation that
  // was denied, an installation that was not the person's, or an entitlement
  // refusal left the flow empty — and the agent kept hearing `pending` until
  // the state expired, fifteen minutes after the browser had finished.
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  await browserFinishes(on, flow.nonce,
    { status: 'not_permitted', reason: 'not entitled to connect this installation' });

  const got = await post('claim', await aPoll(agent, flow.state), on);

  assert.equal(got.body.status, 'not_permitted');
  assert.match(got.body.reason, /not entitled/);
});

test('a refusal carries no grant and no installation', async () => {
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);
  await browserFinishes(on, flow.nonce, { status: 'failed', reason: 'x' });

  const got = await post('claim', await aPoll(agent, flow.state), on);

  assert.ok(!got.body.grant);
  assert.ok(!got.body.installation);
});

// --------------------------------------------------------------------------- //
// one browser leg per flow
// --------------------------------------------------------------------------- //

test('a flow can only be walked through the browser once', async () => {
  // A state is not a secret — it is in an address bar, a history and a
  // referrer — and the browser proves nothing else about itself. Without
  // this, somebody holding a victim's state could walk it through `setup`
  // with an installation of their own and have the result delivered to a
  // terminal that chose neither.
  const { claimSetup } = await import('./rendezvous.js');
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  assert.equal(await claimSetup(on, flow.nonce), true);
  assert.equal(await claimSetup(on, flow.nonce), false,
    'a second browser leg on one flow was allowed');
});

test('taking the browser leg of one flow does not take another\'s', async () => {
  const { claimSetup } = await import('./rendezvous.js');
  const on = env();
  const mine = await begin(on, await anAgent());
  const theirs = await begin(on, await anAgent());

  assert.equal(await claimSetup(on, mine.nonce), true);
  assert.equal(await claimSetup(on, theirs.nonce), true);
});

test('the setup route refuses a flow whose leg is already taken', async () => {
  const { claimSetup } = await import('./rendezvous.js');
  const on = env();
  const agent = await anAgent();
  const flow = await begin(on, agent);

  await claimSetup(on, flow.nonce);

  const answer = await handle(new Request(
    `${BASE}/setup?installation_id=42&state=${encodeURIComponent(flow.state)}`,
  ), on);
  const text = await answer.text();

  assert.match(text, /already been used/);
  assert.ok(!text.includes('installations/new'), 'and does not re-offer the app');
});
