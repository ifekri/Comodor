/**
 * What the app is called in production, written down once.
 *
 * The runtime reads the slug from `env.GITHUB_APP_SLUG`, and that is right:
 * it is deployment configuration, and a staging deployment points at a
 * different app. What is *not* configuration is what the production
 * deployment must be configured with, and that expectation belongs in exactly
 * one place instead of being restated in every fixture.
 *
 * It was restated in every fixture, and they all said `comodor`. There is no
 * app at `github.com/apps/comodor` — it returns 404 — so the suite was green
 * against a value that had never worked. The route handler defaulted to the
 * same wrong string when the variable was unset, which is how a 404 link
 * shipped with tests passing.
 *
 * Changing the app's name is therefore one edit here, and the contract test
 * that pins the install URL fails until every fixture agrees with it.
 */

/** The production GitHub App's URL name: `github.com/apps/comodor-agent`. */
export const APP_SLUG = 'comodor-agent';

/** The origin the app's setup, callback and webhook URLs are registered under. */
export const APP_ORIGIN = 'https://comodor.ai';
