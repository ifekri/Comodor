/**
 * Asking again, every time, whether the holder is still allowed.
 *
 * Entitlement used to be checked once, when the grant was issued. The grant
 * has no expiry, so that made it permanent authority:
 *
 *     Monday    an owner of `comodor-ai` connects. Grant issued.
 *     Tuesday   they are demoted to member, or removed from the organisation.
 *     Wednesday their grant and their private key are unchanged, so `/token`
 *               still mints a full installation token for every repository
 *               `comodor-ai` has the app on.
 *
 * Nothing was forged. The authority simply outlived the thing it was granted
 * under, which is what a credential with no revocation path always does.
 *
 * The fix is to stop treating the grant as an answer and treat it as a
 * question. It names the person it was issued to — `actor_id` and
 * `actor_login` — and this module asks GitHub, at every mint, whether that
 * person is still entitled to the installation. An expiry would have been the
 * lazier version of this and a worse one: it only fixes the delay, not the
 * fact that nobody is asking.
 *
 * **The order is the security property.** For an organisation:
 *
 *   1. resolve the installation as the app — what account is it on now;
 *   2. mint a token carrying **`members: read` and nothing else**;
 *   3. read `GET /orgs/{org}/memberships/{actor_login}` with that token;
 *   4. require `state: active`, `role: admin`, and the membership's own
 *      `user.id` to equal the grant's `actor_id`;
 *   5. only now, mint the full installation token.
 *
 * Step 2 is not decoration. Using the full token to decide whether the full
 * token is allowed would mean the credential existed before the decision, and
 * a bug anywhere after that point would be a bug that had already handed it
 * over. The restricted token can read one membership and do nothing else.
 *
 * Step 4 compares ids rather than logins. A login can be changed, and freed
 * logins can be claimed by somebody else; `ul` is how the membership is looked
 * up, `ui` is what the answer has to match. If the person renamed themselves,
 * the lookup 404s and the connection is refused — correct, if inconvenient,
 * and the fix is one `comodor github connect`.
 *
 * **Everything fails closed.** A missing permission, a 404, a rename, a
 * mismatch, a network error, an account type this does not recognise: all
 * refusals. There is deliberately no path that falls back to what the grant
 * said at issue time, because that is precisely the stale answer being
 * replaced.
 *
 * **What this cannot do.** An installation token already minted stays valid
 * for up to an hour; GitHub offers no revocation for one and this Worker
 * stores nothing that could track them. So the window is an hour of a token
 * that was legitimate when issued. What is closed is the refresh: a grant
 * cannot obtain another one.
 */

import { mintToken, readInstallation } from './api.js';

const API = 'https://api.github.com';

const HEADERS = {
  accept: 'application/vnd.github+json',
  'x-github-api-version': '2022-11-28',
  'user-agent': 'comodor-github-app',
};

/** The only permission the checking token may carry. */
export const CHECKING_PERMISSIONS = { members: 'read' };

function refuse(why, status = 403) {
  const error = new Error(why);
  error.status = status;
  return error;
}

/**
 * The installation as it is now, refused if it is not what the grant describes.
 *
 * An installation id is stable, but what it points at is not guaranteed to be
 * the thing it pointed at when the grant was written. Comparing the account id
 * and type means a grant is about one account rather than about a number.
 */
async function resolve(env, claims) {
  let installation;
  try {
    installation = await readInstallation(env, claims.i);
  } catch (error) {
    // A 404 here is the app having been uninstalled, which is the ordinary way
    // a connection ends. Everything else is GitHub being unreachable. Both are
    // refusals; neither should say more than it knows.
    throw refuse('that installation is no longer available',
      error.status === 404 ? 404 : 502);
  }

  const account = installation.account || {};
  if (Number(account.id) !== Number(claims.ai)
      || String(account.type) !== String(claims.at)) {
    throw refuse('that installation is not the one this connection was made '
      + 'for. Run `comodor github connect` again.');
  }
  return installation;
}

/**
 * Whether the person the grant names may still have the whole installation.
 *
 * Returns the installation. Throws a refusal, with a message safe to return,
 * for every other outcome.
 */
export async function stillEntitled(env, claims) {
  const installation = await resolve(env, claims);
  const account = installation.account || {};

  if (claims.at === 'User') {
    // A personal installation belongs to exactly one account, and the person
    // the grant names must be that account. No call is needed: both numbers
    // are already here, one from GitHub a moment ago and one signed.
    if (Number(claims.ui) !== Number(account.id)) {
      throw refuse('this connection was made by somebody who is not the owner '
        + 'of that account');
    }
    return installation;
  }

  if (claims.at !== 'Organization') {
    throw refuse('this connection is on an account type whose ownership '
      + 'cannot be confirmed');
  }

  const org = String(account.login || '');
  if (!org) throw refuse('that organisation has no name');

  // Narrow, and minted only for this. See the module docstring: the full token
  // must not exist until after the answer.
  let checking;
  try {
    checking = await mintToken(env, claims.i,
      { permissions: CHECKING_PERMISSIONS });
  } catch (error) {
    if (error.status === 422) {
      // GitHub refuses a permission the installation does not hold.
      throw refuse('this deployment cannot read organisation membership, so '
        + 'it cannot confirm you may still use this connection. The app needs '
        + 'the "Members" organisation permission at read.');
    }
    throw refuse('that membership could not be confirmed', 502);
  }

  let membership;
  try {
    const answer = await fetch(
      `${API}/orgs/${encodeURIComponent(org)}`
      + `/memberships/${encodeURIComponent(claims.ul)}`,
      { headers: { ...HEADERS, authorization: `Bearer ${checking.token}` } });

    if (answer.status === 403) {
      throw refuse('this deployment cannot read organisation membership, so '
        + 'it cannot confirm you may still use this connection. The app needs '
        + 'the "Members" organisation permission at read.');
    }
    if (answer.status === 404) {
      // Not a member any more, or renamed. Either way this connection cannot
      // be checked, and an unverifiable connection is a refused one.
      //
      // The organisation is not named, here or below. Everything in this
      // function runs for somebody who has just failed an ownership check, and
      // a refusal that names the organisation would tell whoever holds a
      // stolen key file which organisation it was for.
      throw refuse('that account is no longer a member of the organisation '
        + 'this connection is for. Run `comodor github connect` again.');
    }
    if (!answer.ok) throw refuse('that membership could not be confirmed', 502);

    membership = JSON.parse(await answer.text());
  } catch (error) {
    if (error.status) throw error;
    throw refuse('that membership could not be confirmed', 502);
  }

  const state = String((membership || {}).state || '');
  const role = String((membership || {}).role || '');
  const who = Number(((membership || {}).user || {}).id);

  // The id, not the login. A login can be changed and a freed one claimed by
  // somebody else, so the name is only how the question was asked.
  if (!who || who !== Number(claims.ui)) {
    throw refuse('that account is not the one this connection was made by. '
      + 'Run `comodor github connect` again.');
  }
  if (state !== 'active') {
    throw refuse('that membership of the organisation this connection is for '
      + 'is not active');
  }
  if (role !== 'admin') {
    throw refuse('this connection covers every repository the app can reach '
      + 'in that organisation, so it needs an owner of it. That account is a '
      + 'member, which is not the same thing.');
  }

  return installation;
}
