/**
 * comodor.ai — the static site, and the GitHub App's endpoints.
 *
 * This Worker exists to serve eighty-five exported files and, until now, had
 * no script at all: `wrangler.jsonc` explains why at length, and the reason
 * still holds. Requests to static assets are free and unlimited; a script in
 * front of every one of them puts a marketing page behind a request ceiling.
 *
 * So this script does not go in front of every request. `run_worker_first` in
 * `wrangler.jsonc` names one path prefix — `/api/integrations/github/*` — and
 * everything else reaches the asset server without this code running at all.
 * A visitor reading the page still costs nothing.
 *
 * What lives behind that prefix is the half of a GitHub App that cannot live
 * in the agent: the app's private key. It signs a JWT to prove the app is
 * itself, exchanges that for an installation token, and hands the token — and
 * only the token — to the agent that asked. The key is a Cloudflare secret and
 * never leaves this isolate.
 */

import { handle, isGitHubRoute } from './github/routes.js';

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (isGitHubRoute(url.pathname)) {
      try {
        return await handle(request, env);
      } catch (error) {
        // Never the exception's own text. It can carry a JWT, a token, or a
        // fragment of the private key, and this is the last place before a
        // response body. What goes to the log is the shape; what goes to the
        // caller is that something failed.
        console.error('github route failed', String(error && error.name));
        return new Response(
          JSON.stringify({ error: 'that could not be completed' }),
          { status: 500,
            headers: { 'content-type': 'application/json; charset=utf-8',
                       'cache-control': 'no-store' } });
      }
    }

    // Everything else is a static file. `run_worker_first` should mean this is
    // never reached, and it is here so that a misconfiguration serves the site
    // rather than a blank page.
    void ctx;
    return env.ASSETS.fetch(request);
  },
};
