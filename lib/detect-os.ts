/**
 * Which install command to show first.
 *
 * Detection is a convenience, never a gate. The page renders every platform's
 * command server-side and this only decides the order, so a visitor on an
 * unrecognised system — or with JavaScript disabled — still sees a command
 * they can use rather than an empty box or a wrong guess with no way out.
 */

import type { OsId } from './site.config';

interface UserAgentData {
  platform?: string;
}

export function detectOs(): OsId | null {
  if (typeof navigator === 'undefined') return null;

  // userAgentData is the modern, un-spoofed source where it exists.
  const data = (navigator as Navigator & { userAgentData?: UserAgentData })
    .userAgentData;
  const platform = (data?.platform || navigator.platform || '').toLowerCase();
  const agent = navigator.userAgent.toLowerCase();
  const haystack = `${platform} ${agent}`;

  if (/win/.test(haystack)) return 'windows';
  // iPadOS reports as a Mac; both get the same command, so this is harmless.
  if (/mac|iphone|ipad|ipod|darwin/.test(haystack)) return 'macos';
  if (/linux|x11|cros|android|bsd/.test(haystack)) return 'linux';
  return null;
}

export function osLabel(id: OsId): string {
  return { macos: 'macOS', linux: 'Linux', windows: 'Windows' }[id];
}
