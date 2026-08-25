/**
 * get.comodor.ai — one address that gives every caller the right installer.
 *
 * The page shows one line per platform and they all point here:
 *
 *   curl -fsSL get.comodor.ai | sh
 *   irm get.comodor.ai | iex
 *
 * So this has to read who is asking and answer differently, which a static
 * host cannot do — a static export gives the same bytes to everyone by
 * definition. It used to be a PHP file on shared hosting; at the edge it is
 * faster and it lives in the repository where the scripts do.
 *
 * The order of the checks is the whole trick. PowerShell's `Invoke-RestMethod`
 * introduces itself as:
 *
 *   Mozilla/5.0 (Windows NT 10.0; Microsoft Windows 10.0.26100; en-US) PowerShell/7.4.6
 *
 * It begins with `Mozilla/5.0`, exactly as a browser does. Test for a browser
 * first and every Windows install is handed an HTML page to run, which fails
 * with a parse error nobody can act on. PowerShell is therefore checked before
 * anything else, and the browser check is last.
 * The scripts are not copied in here. They are fetched from the site, which
 * has one useful consequence: editing `lib/scripts/install.sh` and deploying
 * the site updates what this serves. A copy would drift the first time
 * somebody fixed the installer and forgot this existed.
 */

const SITE = 'https://comodor.ai';

/** How long the edge may hold a script. Long enough to be free on a busy day,
 *  short enough that a fix to the installer is live within the hour. */
const CACHE_FOR = 900;

const SCRIPTS = {
  sh: { path: '/install.sh', type: 'text/plain; charset=utf-8' },
  ps1: { path: '/install.ps1', type: 'text/plain; charset=utf-8' },
};

/**
 * Which installer this caller wants.
 *
 * Returns 'ps1', 'sh', 'browser', or 'nothing' for an address that means
 * nothing here.
 */
export function wantedBy(request) {
  const url = new URL(request.url);
  const agent = request.headers.get('user-agent') || '';

  // Only the addresses that mean something. Everything used to be served the
  // installer with a 200, so `get.comodor.ai/wp-admin.php` — a scanner, or
  // somebody's typo — came back as twenty-seven kilobytes of shell script and
  // a success status. A wrong URL should say so.
  const path = url.pathname.replace(/\/+$/, '') || '/';
  if (path === '/install.ps1') return 'ps1';
  if (path === '/install.sh') return 'sh';
  if (path !== '/') return 'nothing';

  // An explicit ask wins over any guess: `get.comodor.ai/?ps1` is what
  // somebody types when the guess got it wrong, and it has to work.
  const asked = url.searchParams;
  if (asked.has('ps1') || asked.has('windows')) return 'ps1';
  if (asked.has('sh') || asked.has('unix')) return 'sh';

  // PowerShell first. Its user agent starts with `Mozilla/5.0`, so every
  // check below would claim it.
  if (/powershell|windowspowershell|pwsh/i.test(agent)) return 'ps1';

  if (/\bcurl\b|\bwget\b|\bhttpie\b|\bfetch\b|libcurl/i.test(agent)) return 'sh';

  // A real browser navigating, as opposed to a script that borrowed a browser
  // string. `Sec-Fetch-Mode: navigate` is only sent by browsers, and only for
  // a navigation — which is exactly the case we want to send to the page.
  if (request.headers.get('sec-fetch-mode') === 'navigate') return 'browser';
  if (/mozilla|chrome|safari|firefox|edge\//i.test(agent)) return 'browser';

  // Something unrecognised, piping into a shell. A POSIX shell is the safer
  // guess: the caller is far more likely to be a container with a trimmed
  // curl than a browser that forgot to introduce itself, and being wrong here
  // costs a readable error rather than a broken install.
  return 'sh';
}

export default {
  async fetch(request, _env, ctx) {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Only GET.\n', {
        status: 405,
        headers: { 'content-type': 'text/plain; charset=utf-8', allow: 'GET, HEAD' },
      });
    }

    const wants = wantedBy(request);
    if (wants === 'nothing') {
      return new Response(
        'Nothing here. The installer is at the root:\n\n'
        + '  curl -fsSL get.comodor.ai | sh\n'
        + '  irm get.comodor.ai | iex\n',
        { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } });
    }
    if (wants === 'browser') {
      // The query string travels: a shared link carrying a campaign tag should
      // arrive on the page still carrying it.
      return Response.redirect(SITE + '/' + new URL(request.url).search, 302);
    }

    const script = SCRIPTS[wants];
    const from = SITE + script.path;

    let upstream;
    try {
      upstream = await fetch(from, {
        cf: { cacheTtl: CACHE_FOR, cacheEverything: true },
        headers: { 'user-agent': 'comodor-get' },
      });
    } catch (error) {
      return unavailable(String(error));
    }
    if (!upstream.ok) return unavailable(`${from} answered ${upstream.status}`);

    const body = await upstream.text();

    // A truncated installer is worse than none: piped into a shell it runs
    // whatever prefix arrived. Both scripts are north of twenty kilobytes, so
    // anything tiny is a failure being served as a success.
    if (body.length < 1000) return unavailable('the script came back truncated');

    const headers = new Headers({
      'content-type': script.type,
      'cache-control': `public, max-age=${CACHE_FOR}`,
      // Never let a browser sniff this into something it will run or render.
      'x-content-type-options': 'nosniff',
      // So somebody who lands here in a browser and views source knows where
      // the file they are reading actually lives.
      'x-source': from,
      vary: 'user-agent',
    });
    void ctx;
    return new Response(request.method === 'HEAD' ? null : body, { headers });
  },
};

/**
 * When the script cannot be fetched.
 *
 * Two rules. The status is 5xx so `curl -f` exits non-zero rather than piping
 * an error message into `sh`. And the text names a way to install that does
 * not depend on this service being up, because somebody reading this is
 * trying to install something, not to debug our edge.
 */
function unavailable(why) {
  const text =
    '# The installer could not be fetched.\n' +
    `# (${why})\n` +
    '#\n' +
    '# Install it directly instead — this needs nothing from us:\n' +
    '#\n' +
    '#   uv tool install comodor\n' +
    '#   pipx install comodor\n' +
    '#   pip install comodor\n';
  return new Response(text, {
    status: 503,
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': 'no-store',
      'retry-after': '60',
    },
  });
}
