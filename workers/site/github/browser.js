/**
 * Proving that this browser is the one the terminal opened.
 *
 * The signed state cannot do this job, and it was a mistake to let it try. A
 * state travels to GitHub, comes back in a query string, and sits in an
 * address bar, a history and a referrer — it is a correlation token that
 * everyone downstream sees. Anything a *holder* of the state can do, a person
 * who read the address bar over a shoulder can do as well; and what they could
 * do was walk the browser leg with an installation of their own and have the
 * result delivered to a terminal that chose neither.
 *
 * So there are two credentials now, with two different jobs:
 *
 * * the **state** ties GitHub's answer back to a flow, and is not secret;
 * * the **launch capability** says which browser may start that flow, and is.
 *
 * The capability is random, one-time and short-lived, and it is deliberately
 * *not* inside the state. It is carried in the URL fragment, which browsers do
 * not put in requests and do not put in `Referer` — so it reaches the launch
 * page without reaching a log, a proxy, or GitHub.
 *
 *   comodor.ai/api/integrations/github/launch?f=<flow>#k=<capability>
 *
 * The launch page reads the fragment, spends the capability, is given a cookie
 * naming that exact flow, and only then is redirected to GitHub. From that
 * point the fragment is gone from the address bar and the capability is spent:
 * a second attempt with the same link fails, and a state copied out of the
 * GitHub URL afterwards has no cookie to go with it.
 *
 * **What the cookie is.** Not a random string looked up in a store, because
 * `setup` would then need a read to check it. It is the same shape as
 * everything else here: a payload naming the flow, signed under the deployment
 * secret. Unforgeable, unmodifiable, and checkable without asking anybody.
 *
 * **The terminal's proof is untouched.** That is the client's private key and
 * has nothing to do with this; the two are independent, and both are required.
 */

import { BROWSER_COOKIE, LAUNCH_LIVES_FOR } from './config.js';

const PREFIX = 'b1';

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64url(text) {
  const padded = String(text || '').replace(/-/g, '+').replace(/_/g, '/')
    + '='.repeat((4 - (String(text || '').length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function hmac(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  return crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
}

/** Compare without leaking where two values differ. */
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

/** A fresh browser capability. Thirty-two random bytes, and nothing derived. */
export function mintCapability() {
  return base64url(crypto.getRandomValues(new Uint8Array(32)));
}

/**
 * What is stored for it.
 *
 * The hash, never the capability. The Worker only ever has to answer "is this
 * the one", and a store holding the answer itself is a store whose contents
 * are the credential.
 */
export async function digestOf(capability) {
  const hashed = await crypto.subtle.digest(
    'SHA-256', new TextEncoder().encode(String(capability || '')));
  return base64url(hashed);
}

/**
 * The cookie that says this browser started this flow.
 *
 * `SameSite=Lax` and not `Strict`: GitHub sends the browser back to `setup` as
 * a top-level navigation from another site, and `Strict` would withhold the
 * cookie on exactly that request — the flow would fail for everyone. `Lax`
 * sends it on a top-level GET, which is what that redirect is, and withholds
 * it from the cross-site subresource requests that matter.
 *
 * `HttpOnly` because no script needs to read it, `Secure` because it only
 * exists over TLS, and `Path` scoped to the integration so it is not attached
 * to a request for the marketing site.
 */
export async function issueCookie(secret, nonce, { now = Date.now() } = {}) {
  const payload = { n: String(nonce), e: Math.floor(now / 1000) + LAUNCH_LIVES_FOR
    + 900 };
  const encoded = base64url(new TextEncoder().encode(JSON.stringify(payload)));
  const token = `${PREFIX}.${encoded}.${base64url(await hmac(secret, encoded))}`;
  return `${BROWSER_COOKIE}=${token}; Max-Age=${LAUNCH_LIVES_FOR + 900}; `
    + 'Path=/api/integrations/github; HttpOnly; Secure; SameSite=Lax';
}

/** Clear it. Sent with every page that ends a flow. */
export function clearCookie() {
  return `${BROWSER_COOKIE}=; Max-Age=0; Path=/api/integrations/github; `
    + 'HttpOnly; Secure; SameSite=Lax';
}

/** The cookie this request carries, if it carries one. */
export function cookieFrom(request) {
  const header = request.headers.get('cookie') || '';
  for (const piece of header.split(';')) {
    const [name, ...rest] = piece.trim().split('=');
    if (name === BROWSER_COOKIE) return rest.join('=');
  }
  return '';
}

/**
 * Which flow a browser cookie names, or null for anything else.
 *
 * Null for malformed, forged, edited and expired alike. `setup` turns all of
 * them into the same answer, because telling them apart tells a prober which
 * guess was closer.
 */
export async function openCookie(secret, token, { now = Date.now() } = {}) {
  const parts = String(token || '').split('.');
  if (parts.length !== 3 || parts[0] !== PREFIX) return null;

  const [, encoded, signature] = parts;
  if (!sameBytes(signature, base64url(await hmac(secret, encoded)))) return null;

  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(fromBase64url(encoded)));
  } catch {
    return null;
  }
  if (!payload || typeof payload !== 'object') return null;
  if (typeof payload.e !== 'number' || payload.e * 1000 <= now) return null;
  if (typeof payload.n !== 'string' || !payload.n) return null;
  return payload;
}
