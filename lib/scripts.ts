import { readFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * Reading the install scripts, in one place.
 *
 * Four routes serve two files — each script at its own name, for piping into a
 * shell, and again as `.txt`, for reading in a browser. The duplication exists
 * because of a difference between the two hosts:
 *
 * On the Node deployment a route handler sets `text/plain` and `/install.sh`
 * displays. On GitHub Pages there is no server and no header — the extension
 * decides, `.sh` maps to `application/x-sh`, and a browser downloads the file
 * rather than showing it. That silently makes the page's own invitation to
 * read before running untrue.
 *
 * `curl` never cared either way, so the piped command is unaffected. The `.txt`
 * copies are what the "read it first" links point at, and they behave the same
 * on both hosts.
 */

export type ScriptName = 'install.sh' | 'install.ps1';

/**
 * Normalised to LF on the way out. The file is edited on Windows, where an
 * ordinary text write turns every line ending into CRLF; `sh` then reads the
 * carriage return as part of the last token and dies before printing anything.
 * That shipped once.
 */
export async function readScript(name: ScriptName): Promise<string> {
  const source = await readFile(
    path.join(process.cwd(), 'lib', 'scripts', name),
    'utf8',
  );
  return source.replace(/\r\n/g, '\n');
}

export const PLAIN_TEXT = {
  'Content-Type': 'text/plain; charset=utf-8',
  // Short, because a fix to the installer should reach people the same day.
  'Cache-Control': 'public, max-age=300, must-revalidate',
  'X-Content-Type-Options': 'nosniff',
} as const;
