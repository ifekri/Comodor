/**
 * Two hosts, one codebase.
 *
 * The Hostinger deployment runs `next start`, a real Node server, so route
 * handlers set their own headers there. GitHub Pages serves static files and
 * nothing else — no server, no headers, no rewrites — so this switches to
 * `output: 'export'` when asked.
 *
 *   NEXT_STATIC_EXPORT=1     produce ./out instead of a server build
 *   NEXT_BASE_PATH=/Comodor  when the site lives in a repository subpath
 *
 * `basePath` is the one that silently ruins a Pages deployment: at
 * `user.github.io/Repo/`, every absolute asset URL resolves a level too high
 * and the page arrives unstyled. It has to be empty again the moment a custom
 * domain is pointed at the same build.
 */

const isExport = process.env.NEXT_STATIC_EXPORT === '1';
const basePath = process.env.NEXT_BASE_PATH || '';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // The client fetches the hero artwork by absolute path, and an absolute path
  // is wrong the moment the site lives in a repository subpath. This is the
  // only way the browser gets told what that prefix is.
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
  poweredByHeader: false,
  compress: true,

  ...(isExport
    ? {
        output: 'export',
        basePath,
        // Pages resolves /a/ to /a/index.html; without this, /a would 404.
        trailingSlash: true,
        // No image optimiser exists on a static host.
        images: { unoptimized: true },
      }
    : {
        // Only meaningful with a server in front. Declaring them under export
        // makes the build warn about routes it cannot apply, and leaves the
        // config claiming something that is not true.
        async headers() {
          return [
            {
              source: '/:path*',
              headers: [
                { key: 'X-Content-Type-Options', value: 'nosniff' },
                { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
                { key: 'X-Frame-Options', value: 'DENY' },
              ],
            },
          ];
        },
      }),
};

export default nextConfig;
