import { readFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * Serve the PowerShell installer as plain text.
 *
 * It used to live in `public/`, which looked simpler and was wrong: the host's
 * front web server delivers static files itself, so Next's header rules never
 * ran and the script arrived as `application/x-sh` — a content type browsers
 * download rather than display, contradicting the page's invitation to read it
 * before running it. A route handler goes through Node, so the headers are ours.
 */
export const dynamic = 'force-static';

export async function GET() {
  const script = await readFile(
    path.join(process.cwd(), 'lib', 'scripts', 'install.ps1'),
    'utf8',
  );

  return new Response(script, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      // Short, because a fix to the installer should reach people the same day.
      'Cache-Control': 'public, max-age=300, must-revalidate',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}
