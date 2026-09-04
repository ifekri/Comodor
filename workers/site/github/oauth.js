/**
 * Proving that the person at the browser is the person whose installation it is.
 *
 * `setup` used to issue the grant directly. It read `installation_id` from the
 * query string, asked GitHub as the app whether such an installation existed,
 * and — since it did — signed a grant binding it to the public key inside the
 * state. Both halves were checked. The relationship between them was not:
 *
 *     attacker → /install with the attacker's own key   → a valid state
 *     attacker → /setup?installation_id=VICTIM&state=ATTACKER_STATE
 *     Worker   → the app JWT confirms the victim's installation exists
 *     Worker   → issues the victim's grant, naming the attacker's key
 *     attacker → signs /token with the key they hold
 *
 * Every signature in that trace is genuine. The app JWT answers "is this a
 * real installation", which is not the question. GitHub says so directly: the
 * setup URL can be called with any `installation_id`, and to trust one you
 * must authenticate the *user* and confirm the installation is theirs.
 *
 * So `setup` no longer issues anything. It starts a short OAuth authorisation
 * with the same GitHub App, and the grant is issued at `callback`, after:
 *
 *   1. the OAuth state opens under our secret and has not expired;
 *   2. the browser presents the verifier for the challenge in that state;
 *   3. GitHub exchanges the code for a user access token, server side;
 *   4. `GET /user/installations` lists what *that user* can reach;
 *   5. the installation the flow is for is in that list.
 *
 * Only then. The user token is used for step 4 and dropped: it is never
 * persisted, never logged, never in a response, and never reaches the agent.
 * Ordinary work continues to use installation access tokens alone — OAuth
 * exists here to bootstrap one connection and appears nowhere in a turn.
 *
 * **No new storage.** The OAuth state carries its own contents and its own
 * HMAC, exactly as the install state does. The one value that cannot live in
 * the state is the PKCE verifier — putting it next to its own challenge would
 * make the challenge decorative — so it goes in a short-lived cookie, which is
 * storage in the browser rather than a namespace to provision.
 *
 * **What PKCE buys here, stated precisely.** GitHub does not currently verify
 * `code_challenge`; it is sent because GitHub's own guidance asks for it and
 * because that may change. The property it actually provides today is enforced
 * on this side: the callback must come from the browser that started the flow,
 * because only that browser has the cookie whose SHA-256 matches the challenge
 * inside the signed state. A state observed in transit, replayed from
 * somewhere else, has no verifier to present.
 */

const AUTHORISE = 'https://github.com/login/oauth/authorize';
const EXCHANGE = 'https://github.com/login/oauth/access_token';
const API = 'https://api.github.com';

/** How long a browser has to finish authorising. */
export const LIVES_FOR = 600;

/** The cookie holding the PKCE verifier. */
export const COOKIE = 'comodor_gh_v';

/** How many pages of installations to walk before giving up. */
const MOST_PAGES = 10;

const HEADERS = {
  accept: 'application/vnd.github+json',
  'x-github-api-version': '2022-11-28',
  'user-agent': 'comodor-github-app',
};

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64url(text) {
  const padded = String(text).replace(/-/g, '+').replace(/_/g, '/')
    + '='.repeat((4 - (String(text).length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

/** Compare without revealing where two values first differ. */
export function sameBytes(left, right) {
  const a = new TextEncoder().encode(String(left || ''));
  const b = new TextEncoder().encode(String(right || ''));
  let difference = a.length ^ b.length;
  const span = Math.max(a.length, b.length);
  for (let index = 0; index < span; index += 1) {
    difference |= (a[index] || 0) ^ (b[index] || 0);
  }
  return difference === 0;
}

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', key,
    new TextEncoder().encode(message));
  return [...new Uint8Array(signature)]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** The S256 challenge for a verifier. */
export async function challengeFor(verifier) {
  const digest = await crypto.subtle.digest(
    'SHA-256', new TextEncoder().encode(String(verifier)));
  return base64url(digest);
}

// --------------------------------------------------------------------------- //
// configuration
// --------------------------------------------------------------------------- //

/**
 * The OAuth credentials, or a refusal naming what is missing.
 *
 * These were deliberately unset before, because installation is not OAuth and
 * nothing needed a GitHub *user* identity. Confirming that an installation
 * belongs to the person claiming it is exactly that need, so they are required
 * now. They are Cloudflare secrets and are never returned, logged, or put in a
 * page.
 */
export function oauthCredentials(env) {
  const clientId = String(env.GITHUB_APP_CLIENT_ID || '');
  const clientSecret = String(env.GITHUB_APP_CLIENT_SECRET || '');
  if (!clientId || !clientSecret) {
    const error = new Error(
      'the GitHub integration is not configured for user verification');
    error.status = 503;
    throw error;
  }
  return { clientId, clientSecret };
}

// --------------------------------------------------------------------------- //
// the state that survives the round trip
// --------------------------------------------------------------------------- //

/**
 * Everything the callback needs, signed so the browser cannot edit it.
 *
 * `u1.` rather than the install state's `comodor.` prefix, and the two are not
 * interchangeable: an install state presented at the callback opens as
 * nothing, and an OAuth state presented at setup likewise. Sharing a secret
 * between two token kinds without separating them is how one becomes the
 * other.
 */
export async function issueState(secret, { installationId, publicKey, nonce,
                                           challenge, now = Date.now() }) {
  const id = Number(installationId);
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('a user check needs an installation id');
  }
  if (!publicKey) throw new Error('a user check needs a client public key');
  if (!challenge) throw new Error('a user check needs a challenge');

  const claims = {
    v: 1,
    i: id,
    k: String(publicKey),
    n: String(nonce || ''),
    c: String(challenge),
    e: Math.floor(now / 1000) + LIVES_FOR,
  };
  const encoded = base64url(new TextEncoder().encode(JSON.stringify(claims)));
  return `u1.${encoded}.${await hmacHex(secret, encoded)}`;
}

/** What an OAuth state says, or null for anything wrong. */
export async function openState(secret, state, { now = Date.now() } = {}) {
  const parts = String(state || '').split('.');
  if (parts.length !== 3 || parts[0] !== 'u1') return null;

  const [, encoded, signature] = parts;
  if (!sameBytes(signature, await hmacHex(secret, encoded))) return null;

  let claims;
  try {
    claims = JSON.parse(new TextDecoder().decode(fromBase64url(encoded)));
  } catch {
    return null;
  }
  if (!claims || typeof claims !== 'object') return null;
  if (claims.v !== 1) return null;
  if (!Number.isInteger(claims.i) || claims.i <= 0) return null;
  if (typeof claims.k !== 'string' || !claims.k) return null;
  if (typeof claims.c !== 'string' || !claims.c) return null;
  if (typeof claims.e !== 'number' || claims.e * 1000 <= now) return null;

  return claims;
}

// --------------------------------------------------------------------------- //
// the cookie holding the verifier
// --------------------------------------------------------------------------- //

/**
 * The cookie the verifier travels in.
 *
 * `HttpOnly` so script on any page cannot read it. `Secure` so it never
 * crosses plain HTTP. `Path` scoped to this integration, so it is not attached
 * to every request for the marketing site. Ten minutes, matching the state.
 *
 * `SameSite=Lax` rather than `Strict`, and that is forced rather than chosen:
 * the callback arrives as a top-level navigation *from github.com*, and
 * `Strict` would withhold the cookie on exactly that hop, breaking every
 * connection. `Lax` sends it on a top-level GET, which is what this is. The
 * cookie is not a credential on its own — it is one half of a pair whose other
 * half is inside a state signed by this Worker.
 */
export function cookieFor(verifier) {
  return `${COOKIE}=${verifier}; Max-Age=${LIVES_FOR}; `
    + `Path=/api/integrations/github; HttpOnly; Secure; SameSite=Lax`;
}

/** The header that removes it. Sent whether the callback succeeded or not. */
export function clearCookie() {
  return `${COOKIE}=; Max-Age=0; Path=/api/integrations/github; `
    + `HttpOnly; Secure; SameSite=Lax`;
}

/** The verifier a request carries, or ''. */
export function verifierFrom(request) {
  const header = request.headers.get('cookie') || '';
  for (const piece of header.split(';')) {
    const at = piece.indexOf('=');
    if (at < 0) continue;
    if (piece.slice(0, at).trim() === COOKIE) {
      return piece.slice(at + 1).trim();
    }
  }
  return '';
}

// --------------------------------------------------------------------------- //
// starting it
// --------------------------------------------------------------------------- //

/**
 * Where to send the browser, and the cookie to send with it.
 *
 * The verifier is 32 random bytes. It never appears in the URL, so it is not
 * in a referrer header, a proxy log, or the address bar.
 */
export async function begin(env, secret, { installationId, publicKey, nonce,
                                           redirectUri, now = Date.now() }) {
  const { clientId } = oauthCredentials(env);

  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = await challengeFor(verifier);
  const state = await issueState(secret, {
    installationId, publicKey, nonce, challenge, now,
  });

  const url = new URL(AUTHORISE);
  url.searchParams.set('client_id', clientId);
  url.searchParams.set('redirect_uri', redirectUri);
  url.searchParams.set('state', state);
  url.searchParams.set('code_challenge', challenge);
  url.searchParams.set('code_challenge_method', 'S256');

  return { url: url.toString(), cookie: cookieFor(verifier), state };
}

// --------------------------------------------------------------------------- //
// finishing it
// --------------------------------------------------------------------------- //

/**
 * The code, exchanged for a user access token. Server side, always.
 *
 * The client secret is in this request and nowhere else. GitHub answers 200
 * with an `error` field for a bad code rather than a 4xx, so the body is
 * checked rather than the status — treating that as success is how an invalid
 * code turns into an empty token and a confusing failure later.
 *
 * The returned token is a credential. It is returned to one caller, used for
 * one request, and never given a name outside this module's caller.
 */
export async function exchangeCode(env, { code, verifier, redirectUri }) {
  const { clientId, clientSecret } = oauthCredentials(env);

  let answer;
  try {
    answer = await fetch(EXCHANGE, {
      method: 'POST',
      headers: { accept: 'application/json',
                 'content-type': 'application/json',
                 'user-agent': 'comodor-github-app' },
      body: JSON.stringify({
        client_id: clientId,
        client_secret: clientSecret,
        code: String(code || ''),
        redirect_uri: redirectUri,
        code_verifier: String(verifier || ''),
      }),
    });
  } catch (error) {
    const problem = new Error(`GitHub could not be reached: ${error}`);
    problem.status = 502;
    throw problem;
  }

  let parsed = {};
  try {
    parsed = JSON.parse(await answer.text());
  } catch {
    parsed = {};
  }

  const token = String(parsed.access_token || '');
  if (!answer.ok || parsed.error || !token) {
    // GitHub's own error name, which describes the code and not the secret.
    // `error_description` is not used: it is prose, and prose from an upstream
    // is the kind of thing that ends up reflected into a page.
    const named = String(parsed.error || `status ${answer.status}`);
    const problem = new Error(`that authorisation could not be completed (${named})`);
    problem.status = 401;
    throw problem;
  }
  return token;
}

/**
 * Whether this user can reach this installation.
 *
 * `GET /user/installations` is the question asked as the *user*, which is the
 * whole point: the app JWT can see every installation of the app, so asking it
 * anything about ownership answers "yes" for strangers.
 *
 * Returns the installation as GitHub described it to that user, or null.
 * Returning the object rather than a boolean means the receipt is built from
 * what the authenticated user can see, so there is no second call that could
 * describe something they were never shown.
 */
export async function installationForUser(token, installationId) {
  const wanted = Number(installationId);
  if (!Number.isInteger(wanted) || wanted <= 0) return null;

  for (let page = 1; page <= MOST_PAGES; page += 1) {
    let answer;
    try {
      answer = await fetch(
        `${API}/user/installations?per_page=100&page=${page}`,
        { headers: { ...HEADERS, authorization: `Bearer ${token}` } });
    } catch (error) {
      const problem = new Error(`GitHub could not be reached: ${error}`);
      problem.status = 502;
      throw problem;
    }

    if (!answer.ok) {
      const problem = new Error(`GitHub answered ${answer.status}`);
      problem.status = answer.status === 401 ? 401 : 502;
      throw problem;
    }

    let parsed = {};
    try {
      parsed = JSON.parse(await answer.text());
    } catch {
      parsed = {};
    }

    const found = Array.isArray(parsed.installations) ? parsed.installations : [];
    for (const one of found) {
      if (Number(one.id) === wanted) return normalise(one, wanted);
    }
    if (found.length < 100) return null;
  }
  return null;
}

/** One installation, in the shape the agent is given. */
function normalise(found, id) {
  const account = found.account || {};
  return {
    installation_id: id,
    account: {
      id: Number(account.id || 0),
      login: String(account.login || ''),
      type: String(account.type || ''),
    },
    repository_selection: String(found.repository_selection || ''),
    permissions: found.permissions && typeof found.permissions === 'object'
      ? found.permissions : {},
    suspended: Boolean(found.suspended_at),
  };
}
