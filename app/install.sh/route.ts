import { PLAIN_TEXT, readScript } from '@/lib/scripts';

/**
 * The shell installer, at the path the page tells people to pipe.
 *
 * A route handler rather than a file in `public/`, because the host's front
 * web server delivers static files itself and Next's header rules never ran —
 * the script arrived as `application/x-sh`, which a browser downloads. On the
 * Node deployment this fixes that. On a static export there is no server at
 * all and the extension wins again, which is why `/install-sh.txt` exists
 * beside it.
 */
export const dynamic = 'force-static';

export async function GET() {
  return new Response(await readScript('install.sh'), { headers: PLAIN_TEXT });
}
