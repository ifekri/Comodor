import { PLAIN_TEXT, readScript } from '@/lib/scripts';

/**
 * The same script, at a name every host agrees is text.
 *
 * This is what "prefer to read before you run?" links to. `.txt` displays in a
 * browser on a Node server and on a static host alike, which `/install.sh`
 * only manages on the former.
 */
export const dynamic = 'force-static';

export async function GET() {
  return new Response(await readScript('install.sh'), { headers: PLAIN_TEXT });
}
