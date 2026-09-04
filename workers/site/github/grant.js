/**
 * Proving that the caller asking for a token is the machine that installed.
 *
 * The first version of `/token` took an `installation_id` and minted against
 * it. That is a critical hole: installation ids are small integers, they
 * appear in URLs, and anyone who learned one could make this Worker issue a
 * working GitHub token for somebody else's repositories.
 *
 * The fix is an identity per connection, established during the flow that is
 * already happening, and carried by a signature the Worker can check without
 * storing anything.
 *
 *   comodor github connect
 *     agent generates an ECDSA P-256 key pair, for this connection only
 *     the public key's fingerprint travels in the install state
 *          ↓
 *     Worker verifies the installation against GitHub
 *     Worker issues a GRANT: {installation_id, client fingerprint, iat, v}
 *     signed with the Worker's secret
 *          ↓
 *   every later /token or /verify carries
 *     the grant, a timestamp, a nonce, and a signature over all of it
 *     made with the private key that never leaves the agent
 *
 * So two checks here, in order, and both must pass:
 *
 *   1. the grant is one this Worker issued and has not been edited
 *   2. the request is signed by the key the grant names
 *
 * `installation_id` is then read *out of the grant*. It is never taken from
 * the request body, which is what made the original hole possible.
 *
 * **And a third check, which is not here.** Passing both of these says the
 * holder is who the grant says. It does not say they are still allowed to be:
 * an organisation owner who connected yesterday and was demoted this morning
 * would still hold a valid grant and a valid key. So the grant names the
 * person it was issued to, and `entitlement.js` asks GitHub whether that
 * person is still entitled before any usable token is minted. See there.
 *
 * **Replay, honestly.** With no storage there is no nonce ledger, so a
 * captured request can be replayed inside its freshness window. Three things
 * bound what that is worth: the window is 120 seconds, the reply is an
 * installation token the replayer could equally have obtained by asking with
 * the same captured request, and everything travels under TLS where capturing
 * it in the first place means the channel is already lost. What replay cannot
 * do is widen scope: the grant fixes the installation, so a replayed request
 * mints for the same installation it always would have.
 */

/** How far out of date a signed request may be. */
export const FRESH_FOR = 120;

/**
 * What the grant format is.
 *
 * Bumped to 2 when the grant started naming the person it was issued to. A
 * version 1 grant cannot be upgraded in place — it does not say who asked
 * for it, and there is nowhere to look that up — so it is refused and the
 * connection is made again. That is one command for the few people who
 * connected before this, against a credential that outlives the authority it
 * was granted under.
 */
export const GRANT_VERSION = 2;

/** The prefix a grant of this version carries. */
export const GRANT_PREFIX = 'g2';

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

/**
 * The fingerprint of a public key: SHA-256 over its raw bytes.
 *
 * The fingerprint rather than the key itself travels in the install state,
 * because a state ends up in a URL and a P-256 public key is 88 base64
 * characters. The grant carries the whole key — it has to, since the Worker
 * verifies signatures with it — and the fingerprint is what ties the grant
 * back to the flow that asked for it.
 */
export async function fingerprint(publicKeyBase64url) {
  const digest = await crypto.subtle.digest(
    'SHA-256', fromBase64url(publicKeyBase64url));
  return base64url(digest);
}

/**
 * Issue a grant. Called once, at the end of a verified installation flow.
 *
 * Signed with the same secret everything else here uses, and carrying the
 * client's public key so later requests can be checked against it without
 * anything having been written down.
 */
export async function issueGrant(secret, { installationId, account, actor,
                                           publicKey, now = Date.now() }) {
  const id = Number(installationId);
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('a grant needs an installation id');
  }
  if (!publicKey) throw new Error('a grant needs a client public key');

  const accountId = Number((account || {}).id);
  const accountType = String((account || {}).type || '');
  if (!Number.isInteger(accountId) || accountId <= 0 || !accountType) {
    throw new Error('a grant needs the account it is installed on');
  }

  const actorId = Number((actor || {}).id);
  const actorLogin = String((actor || {}).login || '');
  if (!Number.isInteger(actorId) || actorId <= 0 || !actorLogin) {
    throw new Error('a grant needs the person it was issued to');
  }

  const claims = {
    v: GRANT_VERSION,
    i: id,
    // What the installation sits on. Carried so a later check can notice that
    // the installation is no longer the account the grant was issued about,
    // rather than trusting an id whose meaning may have moved.
    ai: accountId,
    at: accountType,
    // Who asked for it. This is the field the whole version bump exists for:
    // without it there is no one to re-check, and a grant becomes permanent
    // authority for whoever holds the key.
    ui: actorId,
    // The login is for looking the membership up. The id is what the answer is
    // compared against, because a login can be changed and reused.
    ul: actorLogin,
    k: String(publicKey),
    f: await fingerprint(publicKey),
    iat: Math.floor(now / 1000),
  };
  const encoded = base64url(new TextEncoder().encode(JSON.stringify(claims)));
  return `${GRANT_PREFIX}.${encoded}.${await hmacHex(secret, encoded)}`;
}

/**
 * Open a grant, or null.
 *
 * Null for anything wrong — malformed, wrong signature, wrong version. They
 * are the same answer to a caller, and distinguishing them tells a prober
 * which of their guesses was closer.
 *
 * No expiry, and that is not the same as no revocation. A grant says which key
 * belongs to which person for which installation; whether that person is still
 * entitled to it is asked again at every mint, against GitHub, in
 * `entitlement.js`. An expiry here would only mean a fixed delay before a
 * removed owner stopped working, which is worse than asking.
 */
export async function openGrant(secret, grant) {
  const parts = String(grant || '').split('.');
  if (parts.length !== 3 || parts[0] !== GRANT_PREFIX) return null;

  const [, encoded, signature] = parts;
  if (!sameBytes(signature, await hmacHex(secret, encoded))) return null;

  let claims;
  try {
    claims = JSON.parse(new TextDecoder().decode(fromBase64url(encoded)));
  } catch {
    return null;
  }
  if (!claims || typeof claims !== 'object') return null;
  if (claims.v !== GRANT_VERSION) return null;
  if (!Number.isInteger(claims.i) || claims.i <= 0) return null;
  if (!Number.isInteger(claims.ai) || claims.ai <= 0) return null;
  if (typeof claims.at !== 'string' || !claims.at) return null;
  if (!Number.isInteger(claims.ui) || claims.ui <= 0) return null;
  if (typeof claims.ul !== 'string' || !claims.ul) return null;
  if (typeof claims.k !== 'string' || !claims.k) return null;

  return claims;
}

/** Whether a string is a grant from before the actor was named. */
export function isOldGrant(grant) {
  return String(grant || '').startsWith('g1.');
}

/**
 * What a signed request covers.
 *
 * Every field that could change the outcome is in here, joined by a character
 * none of them can contain. Concatenating without a separator is the usual
 * way this goes wrong: `("ab", "c")` and `("a", "bc")` would sign the same
 * bytes, and an attacker who can shift a boundary can move meaning between
 * fields while keeping the signature valid.
 */
export function signedPayload({ grant, timestamp, nonce, action }) {
  return ['comodor-github-v1', String(action), String(grant),
          String(timestamp), String(nonce)].join('\n');
}

/**
 * Check a signed request, and return the installation it is for.
 *
 * Throws with a message safe to return. The order matters: the grant is
 * checked before the signature, because the grant is what says which key to
 * check the signature *with*.
 */
export async function authorise(secret, body, action, { now = Date.now() } = {}) {
  const claims = await openGrant(secret, body && body.grant);
  if (!claims) {
    // A grant from before the actor was named is told apart from a forgery,
    // and only here. The version of a token format is not a secret — it is
    // the first three characters of something the holder already has — and
    // somebody whose connection has stopped working deserves to know it is
    // their connection rather than their key.
    if (isOldGrant(body && body.grant)) {
      const error = new Error(
        'this connection predates a security fix and cannot be checked '
        + 'against your current access. Run `comodor github connect` again.');
      error.status = 401;
      throw error;
    }
    const error = new Error('that grant is not one of ours');
    error.status = 401;
    throw error;
  }

  const timestamp = Number(body.timestamp);
  if (!Number.isFinite(timestamp)) {
    const error = new Error('the request carries no timestamp');
    error.status = 401;
    throw error;
  }

  const drift = Math.abs(Math.floor(now / 1000) - timestamp);
  if (drift > FRESH_FOR) {
    // Both directions. A future timestamp is as much a sign of something
    // wrong as an old one, and accepting them would let a captured request be
    // replayed for as long as its clock claimed.
    const error = new Error('that request is too old, or its clock is wrong');
    error.status = 401;
    throw error;
  }

  const nonce = String(body.nonce || '');
  if (nonce.length < 16) {
    const error = new Error('the request carries no nonce');
    error.status = 401;
    throw error;
  }

  let publicKey;
  try {
    publicKey = await crypto.subtle.importKey(
      'raw', fromBase64url(claims.k),
      { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'],
    );
  } catch {
    const error = new Error('that grant carries a key that cannot be read');
    error.status = 401;
    throw error;
  }

  let good = false;
  try {
    good = await crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' }, publicKey,
      fromBase64url(body.signature || ''),
      new TextEncoder().encode(signedPayload({
        grant: body.grant, timestamp, nonce, action,
      })),
    );
  } catch {
    good = false;
  }

  if (!good) {
    const error = new Error('that request is not signed by the key in the grant');
    error.status = 401;
    throw error;
  }

  // Read from the grant, never from the body. Taking it from the body is what
  // let anybody who knew an installation id mint a token for it.
  //
  // The whole claim set comes back, not just the id: what happens next has to
  // ask GitHub whether the person named here is still entitled, and it needs
  // the name to ask with.
  return { installationId: claims.i, fingerprint: claims.f, claims };
}
