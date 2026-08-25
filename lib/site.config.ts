/**
 * Everything about the product that appears on the page, in one place.
 *
 * The site and the agent are separate deliverables that must agree about
 * names, commands and links. Centralising them means a rename or a new install
 * route is one edit here, not a search across a dozen components.
 */

export const site = {
  name: 'Comodor',
  domain: 'comodor.ai',
  url: 'https://comodor.ai',
  // One address that names no file. It reads which client is asking and sends
  // curl and wget to the shell installer, PowerShell to the Windows one, and a
  // browser here. So the line on the page is the same line on every system,
  // and nobody has to pick.
  //
  // Not served from this host: a static export gives the same bytes to every
  // caller by definition, so it cannot answer curl and PowerShell differently.
  // The dispatcher is a small PHP file on the subdomain's own document root,
  // which is the only part of the stack that can read a request.
  installUrl: 'get.comodor.ai',
  tagline: 'It learns the way you correct it.',
  // Under 155 characters, because that is where Google cuts a snippet, and a
  // sentence that ends mid-clause in the result reads as a broken page.
  description:
    'A coding agent for your terminal that learns from the edits you make to ' +
    'its output — fix something once and the next answer already obeys.',
  // The date the page's content last changed, not the date it was last built.
  // A sitemap that claims a change on every deploy teaches crawlers to ignore
  // the field.
  updated: '2026-08-25',
  repo: 'https://github.com/ifekri/Comodor',
  pypi: 'comodor',
  pypiUrl: 'https://pypi.org/project/comodor/',
  command: 'comodor',
  pythonFloor: '3.11',
  // The release the page describes. Structured data quotes it, so it is
  // checkable against PyPI rather than a rounded claim.
  version: '0.15.0',
} as const;

export type OsId = 'macos' | 'linux' | 'windows';
export type InstallId = OsId | 'uv' | 'pipx' | 'pip' | 'source';

export interface InstallTarget {
  id: InstallId;
  label: string;
  /** The one-liner shown large. */
  command: string;
  /** Which shell the command is meant for, shown as the prompt glyph. */
  shell: string;
  note: string;
  /**
   * `auto` is the one-line installer that sorts out Python, an isolated
   * environment and PATH by itself. `manual` is for somebody who already has a
   * package manager and would rather use it.
   *
   * The distinction drives the ordering and the emphasis: the automatic
   * installers come first and are what a visitor gets by default, because they
   * are what works on a machine nobody has prepared.
   */
  kind: 'auto' | 'manual';
}

/**
 * Every way to install, in the order they are offered.
 *
 * The automatic installers lead, and one of them is what a visitor sees first;
 * the package managers sit beside them for anyone who already has one. Every
 * entry is in the markup from the first byte, so a wrong platform guess — or no
 * JavaScript at all — still leaves all of them reachable.
 */
export const installTargets: InstallTarget[] = [
  {
    id: 'macos',
    label: 'macOS',
    command: `curl -fsSL ${site.installUrl} | sh`,
    shell: '$',
    note: 'Sets up Python, an isolated environment and your PATH.',
    kind: 'auto',
  },
  {
    id: 'linux',
    label: 'Linux',
    command: `curl -fsSL ${site.installUrl} | sh`,
    shell: '$',
    note: `Any distribution with Python ${site.pythonFloor}+, or none at all.`,
    kind: 'auto',
  },
  {
    id: 'windows',
    label: 'Windows',
    command: `irm ${site.installUrl} | iex`,
    shell: '>',
    note: 'PowerShell 5.1 or newer. Windows Terminal recommended.',
    kind: 'auto',
  },
  {
    id: 'uv',
    label: 'uv',
    command: `uv tool install ${site.pypi}`,
    shell: '$',
    note: 'Fastest, and fetches a Python for you if you have none.',
    kind: 'manual',
  },
  {
    id: 'pipx',
    label: 'pipx',
    command: `pipx install ${site.pypi}`,
    shell: '$',
    note: 'Isolated, on your PATH, upgradable in place.',
    kind: 'manual',
  },
  {
    id: 'pip',
    label: 'pip',
    command: `pip install ${site.pypi}`,
    shell: '$',
    note: 'Into the environment you are in. Use a virtualenv.',
    kind: 'manual',
  },
  {
    id: 'source',
    label: 'source',
    command: `pipx install git+${site.repo}`,
    shell: '$',
    note: 'The latest commit, before it reaches PyPI.',
    kind: 'manual',
  },
];

export interface AltInstall {
  label: string;
  command: string;
  note: string;
}

/** For people who will not pipe a script into a shell — a fair position. */
export const alternatives: AltInstall[] = [
  {
    label: 'uv',
    command: `uv tool install ${site.pypi}`,
    note: 'Fastest. Manages its own Python if you have none.',
  },
  {
    label: 'pipx',
    command: `pipx install ${site.pypi}`,
    note: 'Isolated, on your PATH, upgradable in place.',
  },
  {
    label: 'pip',
    command: `pip install ${site.pypi}`,
    note: 'Into the current environment. Use a virtualenv.',
  },
  {
    label: 'from source',
    command: `pipx install git+${site.repo}`,
    note: 'Latest commit, before it reaches PyPI.',
  },
];
