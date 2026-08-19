import { readFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * Serve the shell installer as plain text, with Unix line endings.
 *
 * It used to live in `public/`, which looked simpler and was wrong: the host's
 * front web server delivers static files itself, so Next's header rules never
 * ran and the script arrived as `application/x-sh` — a content type browsers
 * download rather than display, contradicting the page's invitation to read it
 * before running it. A route handler goes through Node, so the headers are ours.
 *
 * The newline normalisation is not decoration. This file is edited on Windows,
 * where an ordinary text write turns every line ending into CRLF; `sh` then
 * reads the carriage return as part of the last token and dies on line 21 with
 * "set: Illegal option -", before printing anything. That shipped once.
 * Repairing the file fixed that afternoon — doing it here means the next editor
 * cannot bring it back.
 */
export const dynamic = 'force-static';

export async function GET() {
  const script = await readFile(
    path.join(process.cwd(), 'lib', 'scripts', 'install.sh'),
    'utf8',
  );

  return new Response(script.replace(/\r\n/g, '\n'), {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      // Short, because a fix to the installer should reach people the same day.
      'Cache-Control': 'public, max-age=300, must-revalidate',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}
