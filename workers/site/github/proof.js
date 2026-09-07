/**
 * Proving that the terminal collecting a result is the one that asked for it.
 *
 * The receipt protocol did not need this. A receipt is a bearer token the
 * person carries by hand, and holding it is the proof. Once the Worker holds
 * the result instead, something has to decide who may take it — and the
 * obvious answer is wrong.
 *
 * **Knowing the flow is not enough.** A state travels in a URL. It is in the
 * browser's address bar, its history, the referrer GitHub sends, and over the
 * shoulder of anyone in the room; and the nonce is plain base64 inside it, not
 * a secret. So `take(nonce)` on its own would hand a grant to anybody who read
 * the URL, which is the same hole `/token` had when it trusted an installation
 * id from the request body.
 *
 * **What is actually secret** is the private half of the key pair the agent
 * generated before the flow started. Its public half is inside the signed
 * state, arrives at the callback unaltered, and is the key the grant names. A
 * poll signed by that key proves the caller is the machine the grant is *for*
 * — which is exactly the question, and it needs nothing stored to answer.
 *
 * The signature covers the flow, an action, a timestamp and a per-request
 * nonce, joined by a character none of them can contain. That is the same
 * discipline `grant.js` uses for `/token` and `/verify`, deliberately: two
 * signing schemes in one integration is one more thing to get subtly wrong.
 *
 * **Replay.** A captured poll can be resent inside `PROOF_WINDOW`. That is
 * bounded rather than eliminated, and the bound is what makes it uninteresting:
 * the result is taken once and deleted, so a replay that arrives after the
 * real caller gets `pending` and nothing else. Preventing replay outright
 * would mean remembering every nonce seen, which is a store, for a window in
 * which the replay wins nothing.
 */

import { CLAIM_ACTION, PROOF_WINDOW } from './config.js';

/** The version tag on what is signed. Distinct from the grant's on purpose. */
const SCHEME = 'comodor-github-flow-v1';

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

/**
 * What a signed poll covers.
 *
 * The state itself, not just its nonce. Signing the nonce alone would let a
 * signature made for one flow be presented with a different state that happens
 * to carry the same nonce — which a state cannot be edited to do, but the
 * signature should not be relying on that.
 */
export function signedPayload({ state, timestamp, nonce, action }) {
  return [SCHEME, String(action), String(state),
          String(timestamp), String(nonce)].join('\n');
}

function refuse(message) {
  const error = new Error(message);
  error.status = 401;
  throw error;
}

/**
 * Check a signed poll against the public key inside its own state.
 *
 * `claims` is what `state.open` returned — already proved to be a state this
 * Worker issued, and not expired. This adds the second half: that the caller
 * holds the private key that state names.
 *
 * Throws with a message safe to return.
 */
export async function verifyProof(claims, body, {
  action = CLAIM_ACTION, now = Date.now(),
} = {}) {
  const timestamp = Number(body.timestamp);
  if (!Number.isFinite(timestamp)) {
    refuse('the request carries no timestamp');
  }

  const drift = Math.abs(Math.floor(now / 1000) - timestamp);
  if (drift > PROOF_WINDOW) {
    // Both directions. A timestamp in the future is as much a sign of
    // something wrong as an old one, and accepting them would let a captured
    // request be replayed for as long as its clock claimed.
    refuse('that request is too old, or its clock is wrong');
  }

  const nonce = String(body.nonce || '');
  if (nonce.length < 16) {
    refuse('the request carries no nonce');
  }

  if (!claims || typeof claims.k !== 'string' || !claims.k) {
    // A state issued before public keys were required, or one for a flow that
    // never had a key. Nothing to check a signature against.
    refuse('that flow has no client key to check against');
  }

  let publicKey;
  try {
    publicKey = await crypto.subtle.importKey(
      'raw', fromBase64url(claims.k),
      { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify'],
    );
  } catch {
    refuse('that flow carries a key that cannot be read');
  }

  let good = false;
  try {
    good = await crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' }, publicKey,
      fromBase64url(body.signature || ''),
      new TextEncoder().encode(signedPayload({
        state: body.state, timestamp, nonce, action,
      })),
    );
  } catch {
    good = false;
  }

  if (!good) {
    refuse('that request is not signed by the key that started this flow');
  }

  return { nonce: claims.n, publicKey: claims.k };
}
