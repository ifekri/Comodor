/**
 * Receiving what GitHub has to say, and doing almost nothing with it.
 *
 * A webhook is an unauthenticated POST from the internet that claims to be
 * GitHub. Three things follow, and the order matters:
 *
 * **Verify before parsing.** The signature covers the raw bytes. Parsing
 * first means a malformed body reaches a JSON parser before anything has
 * established the sender is GitHub at all.
 *
 * **Constant-time comparison.** `===` on a signature returns at the first
 * differing byte, and how long that takes is a measurement of how many
 * leading bytes were right — enough of those and a signature is forged a byte
 * at a time.
 *
 * **A webhook never runs an agent.** This is the part that would be easy to
 * get wrong and expensive to have wrong: an issue comment is written by
 * whoever can comment, which on a public repository is anybody. Dispatching
 * agent work from one turns "type a sentence in a comment box" into "run a
 * command on somebody's machine". So this normalises the event, decides
 * whether it is even interesting, and returns — and the agent, when it polls,
 * decides what to do about it with a person's mode and permissions in force.
 *
 * Duplicate protection is by delivery id, held in memory. GitHub retries, and
 * a retry is the same delivery arriving again. In-memory means per isolate,
 * which catches the common case — a retry seconds later, on a warm isolate —
 * and misses the uncommon one, which is why nothing here is allowed to have
 * an effect that would matter if it happened twice.
 */

import { sameSecret } from './state.js';

/** Events this app subscribes to. Anything else is accepted and ignored. */
export const EVENTS = new Set([
  'installation',
  'installation_repositories',
  'push',
  'pull_request',
  'pull_request_review',
  'pull_request_review_comment',
  'issues',
  'issue_comment',
  'check_run',
  'check_suite',
  'workflow_run',
  'ping',
]);

/** How many delivery ids to remember. Bounded, or a long-lived isolate grows. */
const REMEMBER = 500;

const seen = new Set();

function remember(deliveryId) {
  if (seen.has(deliveryId)) return false;
  seen.add(deliveryId);
  if (seen.size > REMEMBER) {
    // Oldest first: a Set iterates in insertion order.
    const oldest = seen.values().next().value;
    seen.delete(oldest);
  }
  return true;
}

/** For tests, and for an isolate that wants a clean slate. */
export function forgetDeliveries() {
  seen.clear();
}

function hex(bytes) {
  return [...new Uint8Array(bytes)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Whether this body really came from GitHub.
 *
 * `X-Hub-Signature-256` is `sha256=` followed by an HMAC of the raw body under
 * the webhook secret. The older `X-Hub-Signature` is SHA-1 and is not accepted:
 * GitHub still sends it, and treating it as a fallback would let a caller
 * choose the weaker one.
 */
export async function signatureIsGood(secret, rawBody, header) {
  const given = String(header || '');
  if (!given.startsWith('sha256=')) return false;
  if (!secret) return false;

  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const signed = await crypto.subtle.sign('HMAC', key,
    new TextEncoder().encode(rawBody));

  return sameSecret(given.slice(7), hex(signed));
}

/**
 * One event, reduced to what anything downstream would want.
 *
 * Deliberately small. The full payload is tens of kilobytes of things nobody
 * reads, and every field kept is a field something might come to depend on.
 */
export function normalise(event, payload) {
  const repository = payload.repository || {};
  const installation = payload.installation || {};

  const common = {
    event,
    action: String(payload.action || ''),
    installation_id: Number(installation.id || 0),
    repository: String(repository.full_name || ''),
    default_branch: String(repository.default_branch || ''),
  };

  if (event === 'issue_comment' || event === 'issues') {
    const issue = payload.issue || {};
    return {
      ...common,
      number: Number(issue.number || 0),
      // The text is carried, never interpreted. Whoever wrote it is not
      // trusted, and the agent labels it as data when it reads it.
      title: String(issue.title || '').slice(0, 300),
      author: String((payload.sender || {}).login || ''),
    };
  }

  if (event.startsWith('pull_request')) {
    const pull = payload.pull_request || {};
    return {
      ...common,
      number: Number(pull.number || 0),
      title: String(pull.title || '').slice(0, 300),
      head: String((pull.head || {}).ref || ''),
      base: String((pull.base || {}).ref || ''),
      author: String((payload.sender || {}).login || ''),
    };
  }

  if (event === 'check_run' || event === 'check_suite' || event === 'workflow_run') {
    const run = payload.check_run || payload.check_suite || payload.workflow_run || {};
    return {
      ...common,
      status: String(run.status || ''),
      conclusion: String(run.conclusion || ''),
      branch: String(run.head_branch || ''),
    };
  }

  if (event === 'push') {
    return {
      ...common,
      ref: String(payload.ref || ''),
      commits: Array.isArray(payload.commits) ? payload.commits.length : 0,
    };
  }

  return common;
}

/**
 * Handle one delivery. Always returns a Response.
 *
 * Answers 204 for everything it accepts, including events it does nothing
 * with: GitHub disables a webhook that keeps failing, and an event this app
 * has no use for is not a failure.
 */
export async function receive(request, env) {
  const signature = request.headers.get('x-hub-signature-256');
  const event = String(request.headers.get('x-github-event') || '');
  const delivery = String(request.headers.get('x-github-delivery') || '');

  // Read once, as text. The signature is over these exact bytes, and
  // `request.json()` would consume the body before it could be checked.
  const raw = await request.text();

  if (!await signatureIsGood(env.GITHUB_APP_WEBHOOK_SECRET, raw, signature)) {
    // No detail. "Wrong signature" and "no secret configured" are the same
    // answer to a caller, and telling them apart tells a prober which.
    return new Response('no', { status: 401 });
  }

  if (!delivery) return new Response('no delivery id', { status: 400 });
  if (!EVENTS.has(event)) return new Response(null, { status: 204 });

  if (!remember(delivery)) {
    // A retry of something already handled. 200 rather than an error: GitHub
    // is retrying because it thinks the first attempt failed, and saying "no"
    // makes it keep trying.
    return new Response(null, { status: 204 });
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return new Response('not JSON', { status: 400 });
  }

  const summary = normalise(event, payload);

  // Logged, and what is logged is the summary — never the payload, which
  // carries names, titles and comment bodies belonging to whoever wrote them.
  console.log('github webhook', JSON.stringify({
    event: summary.event,
    action: summary.action,
    repository: summary.repository,
    installation_id: summary.installation_id,
    delivery,
  }));

  // Nothing is dispatched. See the note at the top of this file: an agent
  // started from a comment is an agent started by whoever can comment.
  return new Response(null, { status: 204 });
}
