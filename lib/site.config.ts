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
  tagline: 'It learns the way you correct it.',
  description:
    'A terminal coding agent that learns from the edits you make to its output. ' +
    'Deterministic, model-free, sub-millisecond — and it can prove it is improving.',
  repo: 'https://github.com/ifekri/Comodor',
  pypi: 'comodor',
  pypiUrl: 'https://pypi.org/project/comodor/',
  command: 'comodor',
  pythonFloor: '3.11',
} as const;

export type OsId = 'macos' | 'linux' | 'windows';

export interface InstallTarget {
  id: OsId;
  label: string;
  /** The one-liner shown large. */
  command: string;
  /** Which shell the command is meant for, shown as the prompt glyph. */
  shell: string;
  note: string;
}

/**
 * The hero commands. Ordering here is the server-rendered order; the client
 * reorders it once it knows the visitor's platform, but every entry stays in
 * the DOM so a wrong guess — or no JavaScript at all — still shows the rest.
 */
export const installTargets: InstallTarget[] = [
  {
    id: 'macos',
    label: 'macOS',
    command: `curl -fsSL ${site.url}/install.sh | sh`,
    shell: '$',
    note: 'Works with zsh and bash. Installs into an isolated environment.',
  },
  {
    id: 'linux',
    label: 'Linux',
    command: `curl -fsSL ${site.url}/install.sh | sh`,
    shell: '$',
    note: 'Any distribution with Python ' + site.pythonFloor + ' or newer.',
  },
  {
    id: 'windows',
    label: 'Windows',
    command: `irm ${site.url}/install.ps1 | iex`,
    shell: '>',
    note: 'PowerShell 5.1 or newer. Windows Terminal recommended.',
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
