/**
 * Serve ./out the way GitHub Pages does, so a Pages deployment can be checked
 * before it is a Pages deployment.
 *
 * The point is the differences, not the similarities. Pages has no server, so:
 * it mounts the site under the repository name, it resolves `/a/` to
 * `/a/index.html`, it will not run a route handler, and it assigns content
 * types from the file extension alone. Testing against `next start` proves
 * none of that — it is a different host with different rules.
 *
 *   node tools/serve-export.mjs [port] [basePath]
 */

import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';

const port = Number(process.argv[2] || 4300);
const base = process.argv[3] ?? '/Comodor';
const root = path.join(process.cwd(), 'out');

/*
 * GitHub Pages' mapping, as far as it matters here. `.sh` and `.ps1` are the
 * interesting ones: there is no header to set on a static host, so whatever
 * this says is what a browser will do with the install scripts.
 */
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.xml': 'application/xml',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.ico': 'image/x-icon',
  '.sh': 'application/x-sh',
  '.ps1': 'application/octet-stream',
};

const server = createServer(async (request, response) => {
  let pathname = decodeURIComponent(new URL(request.url, 'http://x').pathname);

  if (base && pathname.startsWith(base)) {
    pathname = pathname.slice(base.length) || '/';
  } else if (base && pathname !== '/') {
    // Pages 404s anything outside the repository path.
    response.writeHead(404, { 'Content-Type': 'text/plain' });
    response.end('Not Found');
    return;
  }

  let file = path.join(root, pathname);
  try {
    const info = await stat(file);
    if (info.isDirectory()) file = path.join(file, 'index.html');
  } catch {
    // Pages tries `<path>.html` before giving up.
    try {
      await stat(`${file}.html`);
      file = `${file}.html`;
    } catch {
      try {
        await stat(path.join(file, 'index.html'));
        file = path.join(file, 'index.html');
      } catch {
        const notFound = await readFile(path.join(root, '404.html')).catch(() => null);
        response.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
        response.end(notFound ?? 'Not Found');
        return;
      }
    }
  }

  const body = await readFile(file);
  response.writeHead(200, {
    'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream',
    'Cache-Control': 'max-age=600',
  });
  response.end(body);
});

server.listen(port, () => {
  console.log(`serving ./out at http://localhost:${port}${base}/`);
});
