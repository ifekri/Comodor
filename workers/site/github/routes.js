/**
 * The GitHub App's endpoints, inside the Worker that already exists.
 *
 *   POST /api/integrations/github/install     start a flow, get a URL
 *   GET  /api/integrations/github/setup       where GitHub sends the browser
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
 * So the join is a signed receipt. `setup` verifies the installation against
 * GitHub, signs what GitHub said together with the nonce from the state, and
 * puts that receipt in the page it returns. The person's browser sends it back
 * to `claim`, which checks the signature and hands the agent the installation.
 * Nothing is stored, and nothing can be claimed by a caller who did not start
 * the flow: the nonce is inside the signature, and only the agent that began
 * has it.
 *
 * The cost is one moment of user interface — the page has a button — and the
 * gain is no new infrastructure and no state to expire, leak or clean up.
 *
 * **What is never returned.** The private key, any JWT, the webhook secret,
 * and the client secret. An installation token is returned, to the agent, over
 * TLS, at the moment it asks — that is the one credential that crosses this
 * boundary and it lasts an hour.
 */

import { mintToken, readInstallation } from './api.js';
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

function page(title, body) {
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
                              'cache-control': 'no-store' } });
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
  if (leaf === 'token') return token(env, body);
  if (leaf === 'verify') return verify(env, body);
  if (leaf === 'disconnect') return json({ status: 'forgotten' });

  return json({ error: 'no such endpoint' }, 404);
}

// --------------------------------------------------------------------------- //

async function start(env, secret, body) {
  const made = await issue(secret, { client: String(body.client || '') });
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
 * The `installation_id` in this URL is a number in a query string. It becomes
 * trustworthy on the line that asks GitHub what it is, and not before.
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

  let installation;
  try {
    installation = await readInstallation(env, installationId);
  } catch (error) {
    return page('That could not be confirmed',
      `<p>${String(error.message || error).slice(0, 200)}</p>`);
  }

  const receipt = await sign(secret, {
    n: opened.n,
    status: 'connected',
    installation,
    // Bounded independently of the state: the installation is verified now,
    // and the receipt should not outlive the terminal that is waiting.
    e: Math.floor(Date.now() / 1000) + 900,
  });

  return page(
    `Connected to ${escapeHtml(installation.account.login)}`,
    `<p>Paste this line into the terminal that is waiting:</p>`
    + cameBack(receipt));
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
      ? { status: 'connected', nonce: found.n, installation: found.installation }
      : { status: found.status || 'cancelled', nonce: found.n });
  }

  return json({ error: 'no receipt' }, 400);
}

async function token(env, body) {
  try {
    const made = await mintToken(env, body.installation_id);
    // Only the token and its expiry. The JWT that fetched it does not exist
    // outside `api.js`, and nothing else here has anything to add.
    return json({ token: made.token, expires_at: made.expires_at });
  } catch (error) {
    return json({ error: String(error.message || error).slice(0, 200) },
      error.status === 404 ? 404 : 502);
  }
}

async function verify(env, body) {
  try {
    return json({ status: 'ok',
                  installation: await readInstallation(env, body.installation_id) });
  } catch (error) {
    if (error.status === 404) return json({ status: 'gone' });
    return json({ error: String(error.message || error).slice(0, 200) }, 502);
  }
}
