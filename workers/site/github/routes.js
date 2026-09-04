/**
 * The GitHub App's endpoints, inside the Worker that already exists.
 *
 *   POST /api/integrations/github/install     start a flow, get a URL
 *   GET  /api/integrations/github/setup       where GitHub sends the browser
 *   GET  /api/integrations/github/callback    where the user check comes back
 *   POST /api/integrations/github/claim       the agent collects the result
 *   POST /api/integrations/github/token       an installation access token
 *   POST /api/integrations/github/verify      what an installation is now
 *   POST /api/integrations/github/disconnect  forget it
 *   POST /api/integrations/github/webhook     what GitHub has to say
 *
 * **How setup hands its answer to an agent with nothing in between.**
 *
 * The browser lands on `setup`. The agent is somewhere else entirely, polling
 * `claim`. Normally a row in a database joins them, and there is no database
 * here — by instruction, and because one namespace existing for fifteen-minute
 * values is infrastructure for this integration alone.
 *
 * So the join is a signed receipt. `callback` signs what GitHub said together
 * with the nonce from the state and puts that receipt in the page it returns.
 * The person copies it back, and `claim` checks the signature and hands the
 * agent the installation.
 *
 * **What the state actually guarantees.** It is short-lived and signed: it
 * cannot be forged, cannot be edited, and expires in fifteen minutes. Two
 * things it is *not*, both worth saying plainly because assuming either would
 * be wrong:
 *
 * * It is **not server-side one-time.** Marking a token used needs somewhere
 *   to write the mark, and there is nowhere.
 * * Its **nonce is not a secret.** The payload is base64, not encrypted, so
 *   anybody holding a state can read the nonce out of it. The nonce exists so
 *   an agent can tell its own receipt from another attempt's — it is a
 *   correlation id, and nothing here is allowed to rest on it being unknown.
 *
 * What does the security work is below, and none of it involves the nonce.
 *
 * **Who may ask for a token.** Not whoever knows an installation id. Every
 * connection carries a key pair the agent generates, and the grant names that
 * key and that installation. `/token` and `/verify` take the installation id
 * *out of the grant* and require a signature from the key it names. See
 * `grant.js`.
 *
 * **Who may be given a grant.** Not whoever can reach `setup` with an
 * installation id. That was a real hole and it is why `callback` exists: the
 * setup URL takes `installation_id` from a query string, and confirming with
 * the app JWT that such an installation exists says nothing about whose it is.
 * An attacker could start their own flow, walk to `setup` with somebody else's
 * installation id, and be handed that installation's grant bound to their own
 * key.
 *
 * So `setup` issues nothing. It starts a GitHub user authorisation, and the
 * grant is issued at `callback` only after `GET /user/installations` — asked
 * with a user token, not the app JWT — lists the installation in question. See
 * `oauth.js`.
 *
 * **What is never returned.** The private key, any JWT, the webhook secret,
 * and the client secret. An installation token is returned, to an
 * authenticated agent, over TLS, at the moment it asks — that is the one
 * credential that crosses this boundary and it lasts an hour.
 */

import { mintToken, readInstallation } from './api.js';
import { stillEntitled } from './entitlement.js';
import { authorise, issueGrant } from './grant.js';
import {
  begin as beginUserCheck,
  challengeFor,
  clearCookie,
  exchangeCode,
  installationForUser,
  mayReceiveGrant,
  openState,
  sameBytes,
  verifierFrom,
} from './oauth.js';
import { issue, open, sameSecret } from './state.js';
import { receive } from './webhook.js';

const BASE = '/api/integrations/github';

/** Where a browser goes to install the app. Derived, never configured twice. */
function installUrl(env, state) {
  const slug = String(env.GITHUB_APP_SLUG || 'comodor');
  return `https://github.com/apps/${slug}/installations/new`
    + `?state=${encodeURIComponent(state)}`;
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      // Nothing here is cacheable and some of it is a credential.
      'cache-control': 'no-store',
    },
  });
}

function page(title, body, extra = {}) {
  return new Response(
    `<!doctype html><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width,initial-scale=1">`
    + `<title>${title} · Comodor</title>`
    + `<style>`
    + `body{background:#0d0b0a;color:#e8e0d8;font:16px/1.6 ui-sans-serif,system-ui,sans-serif;`
    + `margin:0;display:grid;place-items:center;min-height:100vh;padding:24px}`
    + `main{max-width:34rem}h1{font-size:1.4rem;color:#ff9d5c;margin:0 0 .6rem}`
    + `code{background:#1a1512;padding:.15em .4em;border-radius:4px;font-size:.9em}`
    + `p{color:#b8aca2}</style>`
    + `<main><h1>${title}</h1>${body}</main>`,
    { status: 200, headers: { 'content-type': 'text/html; charset=utf-8',
                              'cache-control': 'no-store', ...extra } });
}

/** A receipt: what GitHub confirmed, signed, tied to the flow's nonce. */
async function sign(secret, payload) {
  const encoded = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', key,
    new TextEncoder().encode(encoded));
  const tag = [...new Uint8Array(signature)]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${encoded}.${tag}`;
}

async function unsign(secret, receipt) {
  const parts = String(receipt || '').split('.');
  if (parts.length !== 2) return null;
  const [encoded, tag] = parts;

  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', key,
    new TextEncoder().encode(encoded));
  const expected = [...new Uint8Array(signature)]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');

  if (!sameSecret(tag, expected)) return null;
  try {
    const padded = encoded.replace(/-/g, '+').replace(/_/g, '/')
      + '='.repeat((4 - (encoded.length % 4)) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

/** The secret every signature here uses. One value, one job. */
function signingSecret(env) {
  const secret = String(env.GITHUB_APP_WEBHOOK_SECRET || '');
  if (!secret) throw new Error('the integration is not configured');
  return secret;
}

/** Whether a request is for this integration at all. */
export function isGitHubRoute(pathname) {
  return pathname === BASE || pathname.startsWith(`${BASE}/`);
}

export async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, '');
  const leaf = path.slice(BASE.length).replace(/^\//, '');

  // Configured or not, said once. Every endpoint below needs at least the
  // signing secret, and "not configured" is a clearer answer than a stack of
  // individual failures.
  let secret;
  try {
    secret = signingSecret(env);
  } catch {
    return json({ error: 'the GitHub integration is not configured' }, 503);
  }

  if (leaf === 'webhook') {
    if (request.method !== 'POST') {
      return json({ error: 'POST only' }, 405);
    }
    return receive(request, env);
  }

  if (leaf === 'setup') {
    if (request.method !== 'GET') return json({ error: 'GET only' }, 405);
    return setup(request, env, secret, url);
  }

  if (leaf === 'callback') {
    if (request.method !== 'GET') return json({ error: 'GET only' }, 405);
    return callback(request, env, secret, url);
  }

  if (request.method !== 'POST') {
    return json({ error: 'POST only' }, 405);
  }

  let body = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  if (leaf === 'install') return start(env, secret, body);
  if (leaf === 'claim') return claim(secret, body);
  if (leaf === 'token') return token(env, secret, body);
  if (leaf === 'verify') return verify(env, secret, body);
  // Nothing to forget: there is no server-side record of a connection. The
  // agent deletes its own key and grant, and removing the app on GitHub is
  // what actually revokes access. Answering rather than 404ing so a client
  // calling it is not left thinking something failed.
  if (leaf === 'disconnect') return json({ status: 'forgotten' });

  return json({ error: 'no such endpoint' }, 404);
}

// --------------------------------------------------------------------------- //

/**
 * Whether a string is a P-256 public key this Worker could later verify with.
 *
 * Checked here, at the only door it comes in by, rather than trusted until
 * something downstream tries to use it. A key that is merely the right length
 * used to travel through the whole install flow and fail at the last line, on
 * an `atob` error, with the raw decoder message shown to the person - a bad
 * answer to a question asked twenty minutes earlier.
 */
function usableKey(text) {
  if (!text || text.length < 80 || text.length > 200) return false;
  if (!/^[A-Za-z0-9_-]+$/.test(text)) return false;
  let bytes;
  try {
    const padded = text.replace(/-/g, '+').replace(/_/g, '/')
      + '='.repeat((4 - (text.length % 4)) % 4);
    bytes = atob(padded);
  } catch {
    return false;
  }
  // Uncompressed point: one tag byte and two 32-byte coordinates. Anything
  // else is not something `importKey('raw', ...)` will accept later.
  return bytes.length === 65 && bytes.charCodeAt(0) === 0x04;
}

async function start(env, secret, body) {
  // The agent's public key for this connection, raw P-256, base64url. It goes
  // into the signed state so it arrives at `setup` unaltered without anything
  // being stored: the state's own signature is what protects it.
  //
  // Required. Without it there is no identity to bind the installation to,
  // and `/token` would be back to trusting whatever id it was handed.
  const publicKey = String(body.public_key || '');
  if (!usableKey(publicKey)) {
    return json({ error: 'a connection needs a client public key' }, 400);
  }

  const made = await issue(secret, {
    client: String(body.client || ''),
    publicKey,
  });
  return json({
    state: made.state,
    nonce: made.nonce,
    url: installUrl(env, made.state),
    expires_in: made.payload.e - Math.floor(Date.now() / 1000),
  });
}

/**
 * Where GitHub sends the browser once the app is installed.
 *
 * This used to end the flow. It issued the grant here, having confirmed with
 * the app JWT that the `installation_id` in the query string named a real
 * installation — which is a different question from whether it is the
 * installation of the person standing at this browser. It is not enough, and
 * GitHub's own documentation says so: the setup URL can be called with any id.
 *
 * So nothing is issued here any more. What happens instead is a redirect into
 * a GitHub user authorisation, and `callback` finishes the job.
 *
 * The cancel path still ends here, because there is nothing to authorise: a
 * cancelled installation grants nobody anything, and the receipt says only
 * that the person changed their mind.
 */
async function setup(request, env, secret, url) {
  const installationId = url.searchParams.get('installation_id');
  const action = url.searchParams.get('setup_action') || '';
  const state = url.searchParams.get('state') || '';

  const opened = await open(secret, state);
  if (!opened) {
    return page('That link has expired', '<p>Start again from your terminal '
      + 'with <code>comodor github connect</code>.</p>');
  }

  if (action === 'cancel' || !installationId) {
    const receipt = await sign(secret, { n: opened.n, status: 'cancelled' });
    return page('Cancelled', cameBack(receipt));
  }

  const id = Number(installationId);
  if (!Number.isInteger(id) || id <= 0) {
    return page('That link is not right',
      '<p>Start again from your terminal with '
      + '<code>comodor github connect</code>.</p>');
  }

  // Deliberately no `readInstallation` here. It would tell an unauthenticated
  // caller whether an installation id exists and who owns it, which is a
  // lookup service for other people's accounts. Everything this needs to know
  // comes back at the callback, asked as the user.
  let started;
  try {
    started = await beginUserCheck(env, secret, {
      installationId: id,
      publicKey: opened.k,
      nonce: opened.n,
      redirectUri: callbackUrl(url),
    });
  } catch (error) {
    if (error.status === 503) {
      return page('Not configured',
        '<p>This deployment cannot verify who you are, so it will not hand '
        + 'out a connection. Nothing has been granted.</p>');
    }
    return page('That could not be started',
      `<p>${escapeHtml(String(error.message || error).slice(0, 200))}</p>`);
  }

  // 302 rather than a page with a link: the person has already said yes twice
  // and a third button that says "continue" teaches them to click through
  // whatever a redirect asks for.
  return new Response(null, {
    status: 302,
    headers: {
      location: started.url,
      'set-cookie': started.cookie,
      'cache-control': 'no-store',
    },
  });
}

/** Where GitHub returns after the user authorises. Derived, never guessed. */
function callbackUrl(url) {
  return `${new URL(url).origin}${BASE}/callback`;
}

/**
 * The end of the flow, and the only place a grant is issued.
 *
 * Six checks, in this order, and every one of them must pass:
 *
 *   1. the state opens under our secret, is a state of ours, and is fresh;
 *   2. the browser has the cookie whose SHA-256 is the challenge in that
 *      state — so this callback belongs to the browser that started it;
 *   3. GitHub exchanges the code, server side, for a user access token;
 *   4. that user's own installation list contains the installation this flow
 *      is for;
 *   5. that user is entitled to the whole of it — they are the personal
 *      account it sits on, or an owner of the organisation it sits on;
 *   6. only then, a grant.
 *
 * Four and five are different questions and the gap between them was a
 * privilege escalation. Four asks whether the person can *see* the
 * installation, which an ordinary member with read on one repository can. The
 * grant is for the installation entire, so answering four alone handed that
 * member write on every other repository in it. See `mayReceiveGrant`.
 *
 * The user token exists between 3 and 5. It is not persisted, not logged, not
 * put in the page, and not returned to the agent — the agent never learns that
 * OAuth happened at all, and ordinary work continues to use installation
 * access tokens alone.
 */
async function callback(request, env, secret, url) {
  const clear = { 'set-cookie': clearCookie() };

  const claims = await openState(secret, url.searchParams.get('state') || '');
  if (!claims) {
    // Expired, edited, invented, or an install state presented here. All the
    // same answer: telling them apart tells a prober which guess was closer.
    return page('That link has expired',
      '<p>Start again from your terminal with '
      + '<code>comodor github connect</code>.</p>', clear);
  }

  const verifier = verifierFrom(request);
  if (!verifier || !sameBytes(await challengeFor(verifier), claims.c)) {
    // The cookie is missing or belongs to a different flow. That is a callback
    // arriving at a browser other than the one that started this, which is the
    // shape of a state fed to somebody else.
    return page('That did not come from the right place',
      '<p>This has to finish in the same browser that started it. Run '
      + '<code>comodor github connect</code> again.</p>', clear);
  }

  const code = url.searchParams.get('code') || '';
  if (!code) {
    return page('That authorisation was not completed',
      '<p>Nothing has been granted. Run '
      + '<code>comodor github connect</code> again.</p>', clear);
  }

  let user;
  let entitled;
  try {
    // The token. From here to the end of the entitlement check, and no
    // further: it is not assigned outside this block and nothing below can
    // reach it.
    const token = await exchangeCode(env, {
      code, verifier, redirectUri: callbackUrl(url),
    });
    user = await installationForUser(token, claims.i);
    entitled = user ? await mayReceiveGrant(token, user) : null;
  } catch (error) {
    return page('That could not be confirmed',
      `<p>${escapeHtml(String(error.message || error).slice(0, 200))}</p>`,
      clear);
  }

  if (!user) {
    // The installation exists — it is how we got here — but it is not one this
    // person can reach. The answer says nothing about whose it is instead.
    return page('That installation is not yours',
      '<p>You are signed in to GitHub as somebody who cannot reach the '
      + 'installation this link is for, so nothing has been granted.</p>',
      clear);
  }

  if (!entitled || !entitled.ok) {
    // Reachable, but not theirs to hand over. A grant covers the installation
    // entire, so this is the difference between a member of an organisation
    // and an owner of it.
    return page('That is not yours to connect',
      `<p>${escapeHtml(entitled ? entitled.why : 'That could not be confirmed.')}</p>`,
      clear);
  }

  let grant;
  try {
    grant = await issueGrant(secret, {
      installationId: user.installation_id,
      // What it is installed on, and who is connecting it. Both are checked
      // again at every mint, which is the only reason a grant with no expiry
      // is not permanent authority.
      account: { id: user.account.id, type: user.account.type },
      actor: entitled.actor,
      publicKey: claims.k,
    });
  } catch (error) {
    return page('That could not be completed',
      `<p>${escapeHtml(String(error.message || error).slice(0, 200))}</p>`,
      clear);
  }

  const receipt = await sign(secret, {
    n: claims.n,
    status: 'connected',
    installation: user,
    grant,
    // Bounded independently of the state: the installation is verified now,
    // and the receipt should not outlive the terminal that is waiting.
    e: Math.floor(Date.now() / 1000) + 900,
  });

  return page(
    `Connected to ${escapeHtml(user.account.login)}`,
    `<p>Paste this line into the terminal that is waiting:</p>`
    + cameBack(receipt), clear);
}

/**
 * The receipt, shown to be copied.
 *
 * A page that posted it back automatically would be tidier and would not
 * work: there is nowhere for the Worker to put it, so the terminal would have
 * nothing to poll for. Copying is the join — the person is the channel
 * between the browser that installed the app and the terminal that asked, and
 * they are the one party guaranteed to be at both ends.
 */
function cameBack(receipt) {
  return `<p><code style="word-break:break-all;display:block;padding:.8em">`
    + `${escapeHtml(receipt)}</code></p>`
    + `<p style="font-size:.9em">It is not a password — it says which `
    + `installation was confirmed, signed so it cannot be altered. It expires `
    + `in fifteen minutes.</p>`;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * The agent collecting its result.
 *
 * Two shapes, because the browser and the agent both reach this: the browser
 * posts the receipt it was given, and the agent polls with the state it
 * started. Without shared storage those cannot meet, so the agent's poll
 * answers `pending` until the person pastes the receipt — which the page's
 * own script does for them.
 */
async function claim(secret, body) {
  const receipt = String(body.receipt || '');
  if (receipt) {
    const found = await unsign(secret, receipt);
    if (!found) return json({ error: 'that receipt is not one of ours' }, 400);
    if (found.e && found.e * 1000 <= Date.now()) {
      return json({ error: 'that receipt has expired' }, 400);
    }
    // The nonce travels back so the agent can tell its own receipt from
    // anybody else's. It is not a secret to the holder of the receipt — it is
    // inside the signature — and it is a secret to everyone else, which is
    // exactly the property that makes the check worth doing.
    return json(found.status === 'connected'
      ? { status: 'connected', nonce: found.n,
         installation: found.installation, grant: found.grant }
      : { status: found.status || 'cancelled', nonce: found.n });
  }

  return json({ error: 'no receipt' }, 400);
}

/**
 * An installation access token, for the machine that installed and no other.
 *
 * The installation id comes out of the signed grant. The first version took
 * it from the request body, which meant anybody who learned an installation
 * id — they are small integers and they appear in URLs — could have this
 * Worker mint a working GitHub token for somebody else's repositories.
 */
async function token(env, secret, body) {
  let claims;
  try {
    ({ claims } = await authorise(secret, body, 'token'));
  } catch (error) {
    return json({ error: String(error.message || error).slice(0, 200) },
      error.status || 401);
  }

  // Whether they still may, asked now rather than remembered from whenever the
  // grant was issued. Before the mint, never after: a token that exists has
  // already been handed over, whatever is decided next. See `entitlement.js`.
  try {
    await stillEntitled(env, claims);
  } catch (error) {
    return json({ error: String(error.message || error).slice(0, 200) },
      error.status || 403);
  }

  try {
    const made = await mintToken(env, claims.i);
    // Only the token and its expiry. The JWT that fetched it does not exist
    // outside `api.js`, and nothing else here has anything to add.
    return json({ token: made.token, expires_at: made.expires_at });
  } catch (error) {
    return json({ error: String(error.message || error).slice(0, 200) },
      error.status === 404 ? 404 : 502);
  }
}

/**
 * What an installation is now — for the machine that installed it.
 *
 * Authorised like `/token`, and for the same reason: an installation's
 * account, its repository selection and its permissions are not public, and
 * an endpoint that answered on an id alone would be a way to read them.
 */
async function verify(env, secret, body) {
  let claims;
  try {
    ({ claims } = await authorise(secret, body, 'verify'));
  } catch (error) {
    return json({ error: String(error.message || error).slice(0, 200) },
      error.status || 401);
  }

  // The same check as `token`, and for the same reason. An installation's
  // account, its repository selection and its permission set are things a
  // former owner should stop being able to read the moment they stop being
  // one — an endpoint that only refused to *act* would still be reporting
  // on a private account to somebody who left it.
  try {
    const installation = await stillEntitled(env, claims);
    return json({ status: 'ok', installation });
  } catch (error) {
    // An uninstalled app is not a refusal, it is an answer: the agent forgets
    // the connection on `gone`, which is what should happen.
    if (error.status === 404
        && String(error.message).includes('no longer available')) {
      return json({ status: 'gone' });
    }
    return json({ error: String(error.message || error).slice(0, 200) },
      error.status || 403);
  }
}
