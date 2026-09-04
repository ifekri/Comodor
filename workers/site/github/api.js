/**
 * Talking to GitHub as the app.
 *
 * Two exchanges, and they are the whole reason this code is on a server rather
 * than in the agent: both need the private key, and the key is a secret the
 * app owns rather than one each user holds.
 *
 *   app JWT  →  GET  /app/installations/:id      → what an installation is
 *   app JWT  →  POST /app/installations/:id/access_tokens → an hour's token
 *
 * The JWT is made per call. It lives nine minutes and this is one request; the
 * alternative is caching a credential to save a signature that takes under a
 * millisecond.
 */

import { appJwt } from './jwt.js';

const API = 'https://api.github.com';

const HEADERS = {
  accept: 'application/vnd.github+json',
  'x-github-api-version': '2022-11-28',
  'user-agent': 'comodor-github-app',
};

/** One call as the app. Throws an `Error` whose message is safe to return. */
async function asApp(env, method, path, body) {
  const jwt = await appJwt(env.GITHUB_APP_ID, env.GITHUB_APP_PRIVATE_KEY);

  let answer;
  try {
    answer = await fetch(`${API}${path}`, {
      method,
      headers: { ...HEADERS, authorization: `Bearer ${jwt}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new Error(`GitHub could not be reached: ${error}`);
  }

  const text = await answer.text();
  let parsed = null;
  try {
    parsed = text ? JSON.parse(text) : {};
  } catch {
    parsed = {};
  }

  if (!answer.ok) {
    // GitHub's own words, but never the JWT — which is not in a response body,
    // and this is the boundary where that stops being true if it ever is.
    const said = String(parsed.message || '').slice(0, 200);
    const error = new Error(`GitHub answered ${answer.status}${said ? `: ${said}` : ''}`);
    error.status = answer.status;
    throw error;
  }
  return parsed;
}

/**
 * What GitHub says this installation is.
 *
 * The whole point of the setup callback: the `installation_id` arrived in a
 * query string, and until this returns it is a number somebody typed.
 */
export async function readInstallation(env, installationId) {
  const id = Number(installationId);
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('installation_id is not an installation id');
  }
  const found = await asApp(env, 'GET', `/app/installations/${id}`);

  const account = found.account || {};
  return {
    installation_id: id,
    account: {
      id: Number(account.id || 0),
      login: String(account.login || ''),
      // GitHub calls it `type` on the account object.
      type: String(account.type || ''),
    },
    repository_selection: String(found.repository_selection || ''),
    permissions: found.permissions && typeof found.permissions === 'object'
      ? found.permissions : {},
    // Useful to the agent and to nobody else: a suspended installation
    // authenticates and then refuses everything, which is confusing unless
    // the reason travels.
    suspended: Boolean(found.suspended_at),
  };
}

/**
 * An installation access token: one hour, one installation.
 *
 * Not cached here. A Worker isolate is not a place to keep a credential —
 * there may be one isolate or fifty, they are recycled without warning, and a
 * cache that is sometimes there is a cache whose absence is a bug that shows
 * up under load. The agent caches, where the lifetime is a session.
 */
export async function mintToken(env, installationId) {
  const id = Number(installationId);
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('installation_id is not an installation id');
  }
  const made = await asApp(env, 'POST',
    `/app/installations/${id}/access_tokens`, {});

  const token = String(made.token || '');
  if (!token) throw new Error('GitHub returned no token');

  return {
    token,
    // GitHub sends an ISO timestamp; the agent wants seconds since the epoch.
    expires_at: made.expires_at
      ? Math.floor(Date.parse(made.expires_at) / 1000)
      : Math.floor(Date.now() / 1000) + 3300,
    permissions: made.permissions || {},
    repository_selection: String(made.repository_selection || ''),
  };
}
