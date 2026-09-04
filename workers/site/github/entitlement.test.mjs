/**
 * Whether the holder is *still* allowed, asked at every mint.
 *
 * The two files beside this one cover who may use a grant and who may be given
 * one. Both ask their question once. A grant has no expiry, so asking once
 * meant the answer never changed:
 *
 *     Monday    an owner of `comodor-ai` connects
 *     Tuesday   they are demoted to member, or removed
 *     Wednesday their grant and key are untouched, so `/token` still mints a
 *               full installation token for every repository in the org
 *
 * Nothing is forged in that trace. The authority simply outlived what it was
 * granted under. What follows is the proof that it no longer does.
 *
 * The most important test here is the last one, and it is about *order*: the
 * full installation token must not be created before the check that decides
 * whether it may exist. A token that has been minted has been handed over,
 * whatever the code does with it next.
 *
 *   node --test workers/site/github/entitlement.test.mjs
 */

import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

import { handle } from './routes.js';
import { CHECKING_PERMISSIONS, RUNTIME_PERMISSIONS } from './entitlement.js';
import { issueGrant } from './grant.js';

const SECRET = 'a-webhook-secret-for-the-tests';
const BASE = 'https://comodor.ai/api/integrations/github';

const ENV = {
  GITHUB_APP_WEBHOOK_SECRET: SECRET,
  GITHUB_APP_ID: '12345',
  GITHUB_APP_CLIENT_ID: 'Iv1.notarealclientid',
  GITHUB_APP_CLIENT_SECRET: 'not-a-real-client-secret',
  GITHUB_APP_SLUG: 'comodor',
  // Filled in by the first test that needs one; `jwt.js` is stubbed out below
  // in every test here, because what is under test is the order of calls, not
  // RSA (which `github.test.mjs` covers against a real generated key).
  GITHUB_APP_PRIVATE_KEY: 'stubbed',
};

const ORG = { id: 4242, type: 'Organization', login: 'comodor-ai' };
const PERSON = { id: 9, type: 'User', login: 'ifekri' };
const ACTOR = { id: 9, login: 'ifekri' };
const INSTALLATION = 7;

// --------------------------------------------------------------------------- //
// a real client key, so a real signature can be made
// --------------------------------------------------------------------------- //

const CLIENT = await (async () => {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const raw = await crypto.subtle.exportKey('raw', pair.publicKey);
  return {
    private: pair.privateKey,
    public: btoa(String.fromCharCode(...new Uint8Array(raw)))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''),
  };
})();

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** A signed request body, exactly as an agent builds one. */
async function signedBody(grant, action, { timestamp = Math.floor(Date.now() / 1000),
                                           nonce = 'a-nonce-of-sufficient-length' } = {}) {
  const payload = ['comodor-github-v1', action, grant,
                   String(timestamp), nonce].join('\n');
  const signature = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' }, CLIENT.private,
    new TextEncoder().encode(payload));
  return { grant, timestamp, nonce, signature: base64url(signature) };
}

/** A grant, as the callback would have issued it. */
function aGrant({ account = ORG, actor = ACTOR,
                  installationId = INSTALLATION } = {}) {
  return issueGrant(SECRET, {
    installationId,
    account: { id: account.id, type: account.type },
    actor,
    publicKey: CLIENT.public,
  });
}

// --------------------------------------------------------------------------- //
// standing in for GitHub
// --------------------------------------------------------------------------- //

const realFetch = globalThis.fetch;

/** Every request, in order. The order is the point of several tests below. */
let calls = [];

/** Requests to the access-token endpoint, with the permissions each asked for. */
function mints() {
  return calls
    .filter((one) => one.url.includes('/access_tokens'))
    .map((one) => (one.options.body ? JSON.parse(one.options.body) : {}));
}

/**
 * Whether a mint request is the checking one.
 *
 * By what it asks for, not by whether it asks for anything. Both mints are
 * narrowed now - a mint with no `permissions` at all would be the bug these
 * tests exist to catch, so "has permissions" cannot be the thing that tells
 * them apart.
 */
function isChecking(asked) {
  return Boolean(asked.permissions && asked.permissions.members);
}

/** The mint that hands a token to the agent, if it happened. */
function runtimeMints() {
  return mints().filter((one) => !isChecking(one));
}

function stubGitHub({ installation = ORG, membership, membershipStatus = 200,
                      mintStatus = 200, restrictedMintStatus,
                      whenMinting } = {}) {
  calls = [];
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url);
    calls.push({ url: target, options });

    const reply = (status, body) => new Response(JSON.stringify(body),
      { status, headers: { 'content-type': 'application/json' } });

    if (target.includes('/app/installations/') && target.includes('/access_tokens')) {
      const asked = options.body ? JSON.parse(options.body) : {};
      const checking = Boolean(asked.permissions && asked.permissions.members);
      if (whenMinting) whenMinting(asked);
      const status = checking
        ? (restrictedMintStatus || 200)
        : mintStatus;
      if (status !== 200) return reply(status, { message: 'refused' });
      return reply(200, {
        token: checking ? 'ghs_restricted_for_checking' : 'ghs_the_agents_token',
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
        permissions: asked.permissions || { contents: 'write' },
      });
    }

    if (target.includes('/app/installations/')) {
      if (installation === null) return reply(404, { message: 'Not Found' });
      return reply(200, {
        id: INSTALLATION,
        account: { id: installation.id, login: installation.login,
                   type: installation.type },
        repository_selection: 'selected',
        permissions: { contents: 'write', members: 'read' },
      });
    }

    if (target.includes('/memberships/')) {
      if (membershipStatus !== 200) {
        return reply(membershipStatus, { message: 'no' });
      }
      return reply(200, membership);
    }

    throw new Error(`the test did not expect a request to ${target}`);
  };
}

afterEach(() => { globalThis.fetch = realFetch; });

/** `jwt.js` signs with a real RSA key; these tests are not about that. */
const { appJwt } = await import('./jwt.js');
void appJwt;                     // imported so the stub below is deliberate

async function post(leaf, body) {
  return handle(new Request(`${BASE}/${leaf}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }), ENV);
}

/** A real RSA key, generated once, so the app JWT can actually be made. */
ENV.GITHUB_APP_PRIVATE_KEY = await (async () => {
  const pair = await crypto.subtle.generateKey(
    { name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
    true, ['sign', 'verify']);
  const pkcs8 = await crypto.subtle.exportKey('pkcs8', pair.privateKey);
  const body = btoa(String.fromCharCode(...new Uint8Array(pkcs8)))
    .match(/.{1,64}/g).join('\n');
  return `-----BEGIN PRIVATE KEY-----\n${body}\n-----END PRIVATE KEY-----\n`;
})();

const OWNER = { state: 'active', role: 'admin', user: { id: 9, login: 'ifekri' } };

// --------------------------------------------------------------------------- //
// the organisation case
// --------------------------------------------------------------------------- //

test('an organisation owner still gets a token', async () => {
  stubGitHub({ membership: OWNER });

  const answer = await post('token', await signedBody(await aGrant(), 'token'));
  const said = await answer.json();

  assert.equal(answer.status, 200);
  assert.equal(said.token, 'ghs_the_agents_token');
});

test('the same grant is refused once the actor is only a member', async () => {
  // The vulnerability, exactly. Same grant, same key, same signature - and
  // yesterday it worked.
  stubGitHub({
    membership: { state: 'active', role: 'member', user: { id: 9 } },
  });

  const answer = await post('token', await signedBody(await aGrant(), 'token'));
  const said = await answer.json();

  assert.equal(answer.status, 403);
  assert.ok(/owner/.test(said.error));
  assert.ok(!said.token);
  assert.equal(runtimeMints().length, 0,
    'no full token may be minted for a demoted owner');
});

test('the same grant is refused once the actor is removed', async () => {
  // GitHub answers 404 for somebody who is not a member at all.
  stubGitHub({ membershipStatus: 404 });

  const answer = await post('token', await signedBody(await aGrant(), 'token'));
  const said = await answer.json();

  assert.equal(answer.status, 403);
  assert.ok(/no longer a member/.test(said.error));
  assert.ok(/comodor github connect/.test(said.error));
  assert.equal(runtimeMints().length, 0);
});

test('an owner whose GitHub user id does not match the grant is refused',
  async () => {
    // The login was reused. `ul` is how the question is asked; `ui` is what
    // the answer has to match, because a freed login can be claimed.
    stubGitHub({
      membership: { state: 'active', role: 'admin',
                    user: { id: 999999, login: 'ifekri' } },
    });

    const answer = await post('token', await signedBody(await aGrant(), 'token'));
    const said = await answer.json();

    assert.equal(answer.status, 403);
    assert.ok(/not the one this connection was made by/.test(said.error));
    assert.equal(runtimeMints().length, 0);
  });

test('a pending membership is refused', async () => {
  stubGitHub({ membership: { state: 'pending', role: 'admin', user: { id: 9 } } });

  const answer = await post('token', await signedBody(await aGrant(), 'token'));

  assert.equal(answer.status, 403);
  assert.equal(runtimeMints().length, 0);
});

test('a missing Members permission is refused, and says so', async () => {
  // Two shapes of the same problem: GitHub refuses the narrowed mint (422)
  // when the installation does not hold the permission at all...
  stubGitHub({ membership: OWNER, restrictedMintStatus: 422 });
  let said = await (await post('token',
    await signedBody(await aGrant(), 'token'))).json();
  assert.ok(/Members/.test(said.error));
  assert.equal(runtimeMints().length, 0);

  // ...and answers 403 on the membership call when it is narrower than needed.
  stubGitHub({ membershipStatus: 403 });
  said = await (await post('token',
    await signedBody(await aGrant(), 'token'))).json();
  assert.ok(/Members/.test(said.error));
  assert.equal(runtimeMints().length, 0);
});

test('a membership API failure is refused, not waved through', async () => {
  stubGitHub({ membershipStatus: 500 });

  const answer = await post('token', await signedBody(await aGrant(), 'token'));

  assert.notEqual(answer.status, 200);
  assert.equal(runtimeMints().length, 0,
    'GitHub being unwell must not become an authorisation');
});

// --------------------------------------------------------------------------- //
// the order, which is the security property
// --------------------------------------------------------------------------- //

test('the full token is not minted before the check passes', async () => {
  // A token that exists has been handed over, whatever is decided afterwards.
  // So on a refusal the full mint must never have happened at all, and on a
  // success it must come last.
  stubGitHub({
    membership: { state: 'active', role: 'member', user: { id: 9 } },
  });
  await post('token', await signedBody(await aGrant(), 'token'));

  assert.deepEqual(mints().map(isChecking), [true],
    'only the checking token may be minted when the check fails');

  stubGitHub({ membership: OWNER });
  await post('token', await signedBody(await aGrant(), 'token'));

  const order = calls.map((one) => one.url);
  const membershipAt = order.findIndex((one) => one.includes('/memberships/'));
  const runtimeMintAt = order.findIndex((one, at) =>
    one.includes('/access_tokens')
    && !isChecking(JSON.parse(calls[at].options.body || '{}')));

  assert.ok(membershipAt >= 0 && runtimeMintAt >= 0);
  assert.ok(membershipAt < runtimeMintAt,
    'the membership must be read before the agent\'s token is created');
});

test('the checking token carries Members read and nothing else', async () => {
  // If it carried more, the credential that decides whether the credential is
  // allowed would already be the credential.
  // Only the checking mint. Both narrow now, so "has permissions" would
  // capture whichever ran last rather than the one this test is about.
  let asked = null;
  stubGitHub({ membership: OWNER,
               whenMinting: (body) => {
                 if (body.permissions && body.permissions.members) asked = body;
               } });

  await post('token', await signedBody(await aGrant(), 'token'));

  assert.deepEqual(asked.permissions, { members: 'read' });
  assert.deepEqual(asked.permissions, CHECKING_PERMISSIONS);
  assert.equal(Object.keys(asked.permissions).length, 1);
  assert.equal(asked.repository_ids, undefined);
});

test('the checking token is never returned to the caller', async () => {
  stubGitHub({ membership: OWNER });

  const said = await (await post('token',
    await signedBody(await aGrant(), 'token'))).json();

  assert.equal(said.token, 'ghs_the_agents_token');
  assert.ok(!JSON.stringify(said).includes('ghs_restricted_for_checking'));
});

// --------------------------------------------------------------------------- //
// the personal case
// --------------------------------------------------------------------------- //

test('a personal installation works for the account that owns it', async () => {
  stubGitHub({ installation: PERSON });

  const grant = await aGrant({ account: PERSON, actor: { id: 9, login: 'ifekri' } });
  const answer = await post('token', await signedBody(grant, 'token'));

  assert.equal(answer.status, 200);
  assert.equal((await answer.json()).token, 'ghs_the_agents_token');
  assert.equal(calls.filter((one) => one.url.includes('/memberships/')).length, 0,
    'a personal account needs no membership call: both ids are already known');
});

test('a personal installation whose account id does not match is refused',
  async () => {
    // The installation moved, or the grant was about a different account. The
    // id in the grant is compared against what GitHub says now.
    stubGitHub({ installation: { id: 999, type: 'User', login: 'somebody' } });

    const grant = await aGrant({ account: PERSON, actor: { id: 9, login: 'ifekri' } });
    const answer = await post('token', await signedBody(grant, 'token'));

    assert.equal(answer.status, 403);
    assert.ok(/connect/.test((await answer.json()).error));
    assert.equal(mints().length, 0);
  });

test('a personal installation whose actor is not the account is refused',
  async () => {
    stubGitHub({ installation: PERSON });

    const grant = await aGrant({ account: PERSON,
                                 actor: { id: 4242, login: 'somebody-else' } });
    const answer = await post('token', await signedBody(grant, 'token'));

    assert.equal(answer.status, 403);
    assert.ok(/not the owner/.test((await answer.json()).error));
    assert.equal(mints().length, 0);
  });

test('an installation that changed account type is refused', async () => {
  // The grant says User, GitHub now says Organization. Rather than picking a
  // rule, this refuses and asks for a reconnection.
  stubGitHub({ installation: ORG });

  const grant = await aGrant({ account: PERSON, actor: { id: 9, login: 'ifekri' } });
  const answer = await post('token', await signedBody(grant, 'token'));

  assert.equal(answer.status, 403);
  assert.equal(mints().length, 0);
});

// --------------------------------------------------------------------------- //
// the old format
// --------------------------------------------------------------------------- //

test('a version 1 grant is refused and asks for a reconnection', async () => {
  // It cannot be upgraded in place: it does not say who asked for it, and
  // there is nowhere to look that up. So it is refused by name, because the
  // person should learn it is their connection and not their key.
  stubGitHub({ membership: OWNER });

  const old = `g1.${btoa(JSON.stringify({
    v: 1, i: INSTALLATION, k: CLIENT.public, f: 'x', iat: 1,
  })).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}.abc123`;

  const answer = await post('token', await signedBody(old, 'token'));
  const said = await answer.json();

  assert.equal(answer.status, 401);
  assert.ok(/comodor github connect/.test(said.error));
  assert.equal(calls.length, 0, 'nothing may be asked of GitHub for an old grant');
});

// --------------------------------------------------------------------------- //
// verify is not a way around any of it
// --------------------------------------------------------------------------- //

test('verify refuses a demoted owner too', async () => {
  // An endpoint that refused to act but still described the installation would
  // report a private organisation's account, repository selection and
  // permission set to somebody who had left it.
  stubGitHub({
    membership: { state: 'active', role: 'member', user: { id: 9 } },
  });

  const answer = await post('verify', await signedBody(await aGrant(), 'verify'));
  const said = await answer.json();

  assert.equal(answer.status, 403);
  assert.equal(said.installation, undefined);
  assert.ok(!JSON.stringify(said).includes('comodor-ai'));
});

test('verify still answers gone when the app was uninstalled', async () => {
  // A removed installation is not a refusal, it is the answer: the agent
  // forgets the connection on `gone`, which is what should happen.
  stubGitHub({ installation: null });

  const answer = await post('verify', await signedBody(await aGrant(), 'verify'));

  assert.equal((await answer.json()).status, 'gone');
});

test('verify works for an owner, and says what the installation is now',
  async () => {
    stubGitHub({ membership: OWNER });

    const said = await (await post('verify',
      await signedBody(await aGrant(), 'verify'))).json();

    assert.equal(said.status, 'ok');
    assert.equal(said.installation.account.login, 'comodor-ai');
  });

// --------------------------------------------------------------------------- //
// what the agent's token is allowed to be
// --------------------------------------------------------------------------- //

test('the runtime token never carries members', async () => {
  // `members: read` was added to the app so this Worker could check
  // entitlement. Minting without a permission list returns everything the app
  // holds, which would put that permission in a credential handed to a user's
  // machine - a server-side check leaking into the thing it checks.
  stubGitHub({ membership: OWNER });

  await post('token', await signedBody(await aGrant(), 'token'));
  const [asked] = runtimeMints();

  assert.ok(asked, 'a token should have been minted for the agent');
  assert.ok(asked.permissions, 'the runtime mint must name its permissions');
  assert.equal(asked.permissions.members, undefined);
  assert.ok(!Object.keys(asked.permissions).includes('members'));
});

test('the runtime token asks for exactly the operational permissions',
  async () => {
    // Spelled out rather than compared to the constant alone, so widening the
    // constant does not quietly widen the token every agent receives.
    stubGitHub({ membership: OWNER });

    await post('token', await signedBody(await aGrant(), 'token'));
    const [asked] = runtimeMints();

    assert.deepEqual(asked.permissions, {
      contents: 'write',
      pull_requests: 'write',
      issues: 'write',
      checks: 'read',
      actions: 'read',
    });
    assert.deepEqual(asked.permissions, RUNTIME_PERMISSIONS);
    assert.equal(asked.repository_ids, undefined,
      'the installation already decides which repositories');
  });

test('no token is ever minted with the app default permissions', async () => {
  // The bug in one assertion: a mint request with no `permissions` field gets
  // whatever the app holds. Neither mint may ever look like that.
  stubGitHub({ membership: OWNER });
  await post('token', await signedBody(await aGrant(), 'token'));

  for (const asked of mints()) {
    assert.ok(asked.permissions,
      'every mint must narrow; an unnarrowed one returns the app\'s full set');
  }
  assert.deepEqual(mints().map(isChecking), [true, false],
    'the checking token first, the agent\'s token second');
});

test('the two permission sets are disjoint', async () => {
  // If they ever overlap, the reason for having two of them has gone.
  for (const name of Object.keys(CHECKING_PERMISSIONS)) {
    assert.equal(RUNTIME_PERMISSIONS[name], undefined,
      `${name} is the Worker's, and must not be in the agent's token`);
  }
});

test('a personal installation narrows its token too', async () => {
  // The personal path skips the membership call entirely, so it is a separate
  // route to the mint and a separate chance to forget.
  stubGitHub({ installation: PERSON });

  const grant = await aGrant({ account: PERSON, actor: { id: 9, login: 'ifekri' } });
  await post('token', await signedBody(grant, 'token'));
  const [asked] = runtimeMints();

  assert.deepEqual(asked.permissions, RUNTIME_PERMISSIONS);
  assert.equal(asked.permissions.members, undefined);
});

test('a refused request mints nothing for the agent at all', async () => {
  // Not "mints a narrow one" - nothing. Checked across every refusal shape,
  // because each one is a different early return.
  const refusals = [
    { membership: { state: 'active', role: 'member', user: { id: 9 } } },
    { membershipStatus: 404 },
    { membershipStatus: 403 },
    { membershipStatus: 500 },
    { membership: { state: 'pending', role: 'admin', user: { id: 9 } } },
    { membership: { state: 'active', role: 'admin', user: { id: 1 } } },
    { membership: OWNER, restrictedMintStatus: 422 },
  ];

  for (const how of refusals) {
    stubGitHub(how);
    const answer = await post('token', await signedBody(await aGrant(), 'token'));

    assert.notEqual(answer.status, 200, JSON.stringify(how));
    assert.equal(runtimeMints().length, 0, JSON.stringify(how));
  }
});
