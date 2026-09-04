/**
 * Signing an app JWT, with what the runtime already has.
 *
 * A GitHub App proves it is itself by presenting a JWT signed RS256 with its
 * private key. Workers ship the Web Crypto API, which does RS256 and PKCS#8,
 * so this needs no library — and a library here would be a dependency in the
 * one place where a supply-chain problem reads the private key.
 *
 * The key never leaves this Worker. It is a Cloudflare secret, imported into a
 * non-extractable CryptoKey once and cached for the isolate's life: importing
 * per request is measurable work for a value that cannot change between them.
 *
 * The JWT is short-lived by GitHub's rule — it refuses anything claiming more
 * than ten minutes — and by ours: it exists for one exchange, immediately, and
 * a longer window is only a longer time for a leaked one to be useful.
 */

/** Seconds a JWT is good for. GitHub's ceiling is 600. */
const LIVES_FOR = 540;

/**
 * Seconds to backdate `iat`.
 *
 * GitHub rejects a JWT whose `iat` is in the future by its clock, and the two
 * clocks are not the same clock. Sixty seconds is what GitHub's own
 * documentation suggests, and the cost of it is sixty seconds less validity on
 * a token that lives for nine minutes.
 */
const CLOCK_DRIFT = 60;

/** One imported key per isolate, keyed by the PEM it came from. */
let cached = null;

function base64url(bytes) {
  let binary = '';
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function utf8(text) {
  return new TextEncoder().encode(text);
}

/**
 * A PKCS#8 PEM as the bytes `importKey` wants.
 *
 * GitHub hands out PKCS#1 (`BEGIN RSA PRIVATE KEY`) from the app settings
 * page, and Web Crypto reads only PKCS#8 (`BEGIN PRIVATE KEY`). Converting
 * between them means writing ASN.1, so this refuses the wrong one with the
 * `openssl` line that fixes it rather than failing on a parse error nobody can
 * act on.
 */
export function readPrivateKey(pem) {
  const text = String(pem || '').trim();
  if (!text) throw new Error('no private key configured');

  if (text.includes('BEGIN RSA PRIVATE KEY')) {
    throw new Error(
      'the private key is PKCS#1, which Web Crypto cannot read. Convert it: '
      + 'openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt -in key.pem '
      + '-out key-pkcs8.pem');
  }
  if (!text.includes('BEGIN PRIVATE KEY')) {
    throw new Error('the private key is not a PEM private key');
  }

  const body = text
    .replace(/-----BEGIN PRIVATE KEY-----/, '')
    .replace(/-----END PRIVATE KEY-----/, '')
    .replace(/\s+/g, '');

  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

async function keyFor(pem) {
  if (cached && cached.pem === pem) return cached.key;
  const key = await crypto.subtle.importKey(
    'pkcs8',
    readPrivateKey(pem),
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,                    // not extractable: it cannot be read back out
    ['sign'],
  );
  cached = { pem, key };
  return key;
}

/**
 * A signed app JWT.
 *
 * `appId` is the numeric id from the app's settings — not the client id, which
 * looks similar and is rejected with an unhelpful 401.
 */
export async function appJwt(appId, privateKeyPem, now = Date.now()) {
  const id = String(appId || '').trim();
  if (!id) throw new Error('no app id configured');

  const seconds = Math.floor(now / 1000);
  const header = { alg: 'RS256', typ: 'JWT' };
  const claims = {
    iat: seconds - CLOCK_DRIFT,
    exp: seconds + LIVES_FOR,
    iss: id,
  };

  const signing = `${base64url(utf8(JSON.stringify(header)))}.`
    + `${base64url(utf8(JSON.stringify(claims)))}`;

  const signature = await crypto.subtle.sign(
    'RSASSA-PKCS1-v1_5',
    await keyFor(privateKeyPem),
    utf8(signing),
  );

  return `${signing}.${base64url(signature)}`;
}

/** For tests: forget the imported key so the next call re-imports. */
export function forgetKey() {
  cached = null;
}
