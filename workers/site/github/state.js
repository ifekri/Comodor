/**
 * The `state` that ties an installation back to the agent that asked for it.
 *
 * GitHub sends `installation_id` to the setup URL as a query parameter, which
 * anybody can type. Without something proving the flow was started by the
 * machine now claiming it, anyone who guessed an installation id could bind
 * somebody else's repositories to their own agent. `state` is that proof.
 *
 * **Signed rather than stored.** A random string in a KV namespace would be
 * the usual shape, and it would mean a KV namespace existing solely for
 * fifteen-minute values — infrastructure for this integration alone, which the
 * brief rules out. So the state carries its own contents and an HMAC over
 * them: the Worker can verify one it issued without having written anything
 * down.
 *
 *   comodor.<base64url payload>.<base64url hmac>
 *
 * That buys statelessness and costs one property, which is worth naming
 * plainly rather than glossing: **this is not server-side one-time.** Marking
 * a token used requires somewhere to write the mark, and there is nowhere.
 * Describing it as one-time would be a claim the architecture cannot keep.
 *
 * What it is: short-lived, unforgeable and unmodifiable.
 *
 * * a state cannot be invented — it carries an HMAC under a secret only this
 *   Worker has;
 * * a state cannot be edited — the signature covers the payload, including
 *   the client's public key;
 * * a state expires in fifteen minutes.
 *
 * **The nonce is not a secret, and nothing may rest on it being one.** The
 * payload is base64 of JSON — encoded, not encrypted — so anybody holding a
 * state can read the nonce straight out of it, and a state travels in a URL
 * where referrers, history and shoulders all see it. An earlier version of
 * this comment described it as something only the agent that started the flow
 * holds. That was wrong, and it mattered: it made the nonce sound like a
 * credential.
 *
 * What the nonce is for is telling one attempt from another. An agent
 * compares it so a receipt pasted from somebody else's flow is refused rather
 * than connected — a correctness check against confusion, not a defence
 * against an attacker, who could read the right nonce anyway.
 *
 * The security of the flow does not depend on this file. A state grants
 * nothing on its own: it names an installation nobody has proved they own,
 * and the grant is issued at the OAuth callback only after GitHub confirms,
 * as the signed-in user, that the installation is theirs. Reuse of a state
 * inside its window therefore buys an attacker a fresh trip through that
 * check, which they fail.
 *
 * Fifteen minutes, because that is the outside of how long choosing
 * repositories takes, and because an unused state is a window during which a
 * leaked one would still work.
 */

/** How long a state is good for. */
export const LIVES_FOR = 900;

const PREFIX = 'comodor';

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64url(text) {
  const padded = text.replace(/-/g, '+').replace(/_/g, '/')
    + '='.repeat((4 - (text.length % 4)) % 4);
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

/**
 * Compare two strings without leaking where they differ.
 *
 * `a === b` on a secret returns as soon as a byte differs, and the time that
 * takes is a measurement of how many leading bytes were right. A signature
 * can be forged a byte at a time from enough of those measurements.
 */
export function sameSecret(left, right) {
  const a = new TextEncoder().encode(String(left || ''));
  const b = new TextEncoder().encode(String(right || ''));
  // Length is not secret — it is visible in the encoding — but the comparison
  // still runs over a fixed span so a wrong length costs the same as a wrong
  // byte.
  let difference = a.length ^ b.length;
  const span = Math.max(a.length, b.length);
  for (let index = 0; index < span; index += 1) {
    difference |= (a[index] || 0) ^ (b[index] || 0);
  }
  return difference === 0;
}

/**
 * A fresh state.
 *
 * The nonce is what the agent keeps and matches. It is random and it is
 * inside the signed payload, so it cannot be changed - but it is readable by
 * anybody holding the state, and nothing here treats it as a secret.
 */
export async function issue(secret, { now = Date.now(), client = '',
                                      publicKey = '' } = {}) {
  const nonce = base64url(crypto.getRandomValues(new Uint8Array(24)));
  const payload = {
    n: nonce,
    // Seconds, to keep the token short.
    e: Math.floor(now / 1000) + LIVES_FOR,
    c: String(client || '').slice(0, 40),
    // The agent's public key for this connection. Carried here so it reaches
    // `setup` unaltered with nothing stored — the signature over this payload
    // is what makes that safe — and it is the key the grant will name.
    k: String(publicKey || ''),
  };
  const encoded = base64url(new TextEncoder().encode(JSON.stringify(payload)));
  const signature = base64url(await hmac(secret, encoded));
  return { state: `${PREFIX}.${encoded}.${signature}`, nonce, payload };
}

/**
 * What a state says, if it is one this Worker issued and has not expired.
 *
 * Returns null for anything else — malformed, wrong signature, or too old —
 * rather than throwing, because every one of those is the same answer to the
 * caller and distinguishing them in a response tells a prober which.
 */
export async function open(secret, state, { now = Date.now() } = {}) {
  const parts = String(state || '').split('.');
  if (parts.length !== 3 || parts[0] !== PREFIX) return null;

  const [, encoded, signature] = parts;
  const expected = base64url(await hmac(secret, encoded));
  if (!sameSecret(signature, expected)) return null;

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
