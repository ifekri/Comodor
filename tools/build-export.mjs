/**
 * The static export build, on any operating system.
 *
 * `NEXT_STATIC_EXPORT=1 next build` is the obvious way to write this and it
 * only works on a POSIX shell. On Windows `cmd` reads the assignment as a
 * command and answers:
 *
 *   'NEXT_STATIC_EXPORT' is not recognized as an internal or external command
 *
 * Cloudflare's builders run Linux, so the broken form would have deployed
 * perfectly and failed for anybody checking a build locally on Windows before
 * pushing — which is the worst place to put a difference between CI and a
 * developer's machine.
 */
import { spawnSync } from 'node:child_process';

const { status } = spawnSync('next', ['build'], {
  stdio: 'inherit',
  // `next` is a shell script on POSIX and a .cmd shim on Windows; only the
  // shell knows which to run.
  shell: true,
  env: { ...process.env, NEXT_STATIC_EXPORT: '1', NEXT_BASE_PATH: '' },
});

process.exit(status ?? 1);
