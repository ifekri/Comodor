/**
 * The integration's fixed identity, in one place.
 *
 * This file exists because of a specific failure. The app's URL name was
 * written as `env.GITHUB_APP_SLUG || 'comodor'`, the variable was not set on
 * the deployment, and the fallback produced
 * `https://github.com/apps/comodor/installations/new` — a URL that is
 * perfectly well-formed, returns 404, and had been shipping to every person
 * who ran `comodor github connect`. The real app is `comodor-agent`.
 *
 * Two things went wrong and both are fixed here.
 *
 * **A default that is a guess.** `|| 'comodor'` looks like a safe fallback and
 * is the opposite: it converts a missing configuration — which is loud, and
 * fixable in a minute — into a wrong answer that looks right. Configuration
 * this integration cannot work without now fails closed. A 503 saying the
 * deployment is not configured is a better answer than a link to nothing.
 *
 * **A value in more than one place.** The slug was in the route handler and,
 * differently, in three test fixtures, so the tests agreed with each other and
 * with nothing that runs. Anything below that has one meaning has one
 * definition, and the tests import it rather than restating it.
 *
 * What is deliberately *not* here: values that merely share a spelling. The
 * agent sends `client: "comodor-agent"` as a label so a half-finished flow can
 * be attributed to a machine, and that string is the same as the app slug
 * today by coincidence. They answer different questions — "which GitHub App is
 * this" and "what started this flow" — and either could change without the
 * other. Merging them to remove a duplicate string would create a coupling
 * nobody asked for.
 */

/** Everything under here belongs to this integration. */
export const BASE_PATH = '/api/integrations/github';

/**
 * The connection protocol the agent and the Worker are speaking.
 *
 * 1. The agent is handed a signed receipt in the browser and the person copies
 *    it into the terminal. Every released Comodor speaks this, so the Worker
 *    keeps answering it.
 * 2. The Worker holds the result briefly and the agent collects it itself, by
 *    signing a request with the key the grant already names. No copying.
 *
 * Sent by the agent as `protocol` on `install`, and remembered inside the
 * signed state so `callback` knows which page to render without being told
 * again by a query parameter anybody could edit.
 */
export const PROTOCOL_RECEIPT = 1;
export const PROTOCOL_RENDEZVOUS = 2;
export const PROTOCOLS = [PROTOCOL_RECEIPT, PROTOCOL_RENDEZVOUS];

/**
 * How long a finished result waits for the agent to collect it.
 *
 * Shorter than the state that produced it. The state has to survive somebody
 * choosing repositories, which is slow; this only has to survive the round
 * trip from the browser finishing to the terminal's next poll, which is
 * seconds. A result nobody collected is a terminal that was closed, and it
 * should not outlive the session it belonged to.
 */
export const RESULT_LIVES_FOR = 600;

/**
 * How far out of date a signed poll may be.
 *
 * The agent signs each poll with a timestamp, and a signature older than this
 * is refused. Sixty seconds is generous for clock skew between a laptop and
 * Cloudflare's edge and short enough that a captured request is not a
 * long-lived key.
 */
export const PROOF_WINDOW = 60;

/** What a signed poll is allowed to ask for. */
export const CLAIM_ACTION = 'claim';

class ConfigurationError extends Error {
  constructor(message) {
    super(message);
    this.status = 503;
  }
}

/**
 * The app's URL name — the `comodor-agent` in `github.com/apps/comodor-agent`.
 *
 * Required, with no fallback. See the module docstring: the fallback is what
 * turned an unset variable into a link to a 404.
 */
export function appSlug(env) {
  const slug = String((env && env.GITHUB_APP_SLUG) || '').trim();
  if (!slug) {
    throw new ConfigurationError(
      'GITHUB_APP_SLUG is not set on this deployment');
  }
  // A slug is what GitHub allows in a URL segment. Checked because the failure
  // this file exists to prevent was a well-formed URL to the wrong place, and
  // a slug with a slash in it would be a differently-shaped version of that.
  if (!/^[A-Za-z0-9][A-Za-z0-9-]*$/.test(slug)) {
    throw new ConfigurationError('GITHUB_APP_SLUG is not a valid app name');
  }
  return slug;
}

/** Where a browser goes to install the app. Derived, never configured twice. */
export function installUrl(env, state) {
  return `https://github.com/apps/${appSlug(env)}/installations/new`
    + `?state=${encodeURIComponent(state)}`;
}

/** Which protocol the agent asked for, or the one every old client speaks. */
export function protocolFrom(value) {
  const asked = Number(value);
  return PROTOCOLS.includes(asked) ? asked : PROTOCOL_RECEIPT;
}

export { ConfigurationError };
