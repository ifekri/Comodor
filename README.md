# Comodor skills

Skills the agent can be asked to fetch, kept out of the package so that
installing Comodor stays small and adding a skill needs no release.

Nothing else lives on this branch. It has no source, no tests and no history in
common with `main`: it is an orphan branch, so cloning the project does not drag
a library of Markdown along with it, and editing a skill cannot break a build.

```
catalogue.json          what exists, and everything needed to show it
skills/<id>/SKILL.md    the skill itself
skills/<id>/…           anything it bundles: references/, scripts/, assets/
```

## Skills written elsewhere

Most of what is here was written by other people and is republished with their
permission — everything from [jakubkrehel/skills][jk],
[emilkowalski/skills][ek], [MengTo/Skills][mt] and
[codeswithroh/tastemaker][cr], all MIT.

MIT allows this and asks one thing in return: the copyright notice travels with
the copy. So **every borrowed skill carries a `NOTICE.md`** naming the author,
the repository, the exact commit it was taken at, and the full licence text —
and its catalogue entry records the real author rather than Comodor, with a
`source` block saying where to check it against.

If you add another from somebody else's repository, do the same. Listing
another person's work under your own name is the one way to do this that is
both wrong and trivially avoidable.

Their demo folders are not copied. Screenshots and video illustrate a
repository for a person browsing GitHub; no agent reads them, and git history
is permanent, so eighty-three megabytes of them would be carried by every clone
of this project for ever.

[jk]: https://github.com/jakubkrehel/skills
[ek]: https://github.com/emilkowalski/skills
[mt]: https://github.com/MengTo/Skills
[cr]: https://github.com/codeswithroh/tastemaker

## Adding one

Two steps, and the second is the one that matters.

**1. Write the skill.** A folder under `skills/` with a `SKILL.md` in it, in
the [Agent Skills](https://agentskills.io) open format — front matter with a
`name` and a `description`, then the instructions in plain Markdown:

```markdown
---
name: changelog
description: Write a changelog entry from a diff
triggers: [changelog, release notes]
---

Say what changed and why it mattered…
```

It may bundle `references/`, `scripts/` and `assets/` beside the manifest.
Those are named in the prompt and read only when the turn needs them, so a
thousand-line reference costs nothing until it is used.

**2. Add it to `catalogue.json`.** This is the file Comodor reads. A skill that
exists on this branch and is not in the catalogue is a skill nobody will ever
be shown:

```json
{
  "id": "changelog",
  "name": "changelog",
  "title": "Changelog entries",
  "description": "Write a changelog entry from a diff.",
  "summary": "One sentence more than the description, shown when the entry is selected.",
  "tags": ["git", "writing"],
  "author": "you",
  "version": "1.0.0",
  "updated": "2026-08-21",
  "path": "changelog/",
  "files": ["SKILL.md", "references/style.md"],
  "bytes": 2400
}
```

`files` is a list, not a wildcard, and that is deliberate: the client downloads
exactly what the catalogue names and nothing else, so a file added here by
accident cannot end up on somebody's machine.

## How large a skill may be

There are two ceilings, and a skill has to clear both.

**64 KB, or it will not load at all.** `SKILL.md` is read whole; past that the
loader refuses it with an error naming the file. This is a hard limit and there
is no setting for it.

**The turn's skill budget, or it is matched and then discarded.** A skill is
injected into the request that needs it, so what a turn may spend on skills is
capped by `skills.max_tokens` — 12,000 by default, shared between the
`skills.top_k` matches. A skill that does not fit is skipped and says so; it
does not silently vanish, and it no longer takes the skills ranked behind it
with it.

Roughly, 4 KB of Markdown is a thousand tokens. So a 40 KB skill costs ten
thousand of the twelve thousand available and leaves no room for a second one.

If a skill is too long for either, the format has an answer: keep `SKILL.md` to
the procedure and move the detail into `references/`. Those files are named in
the prompt and read on demand with `read_skill_file`, so they cost nothing
until the turn actually needs them — which also means a long reference is
*better* placed there than inline, whatever its size.

## The fields

| field | what it is for |
|---|---|
| `id` | the name used on the command line, and the folder it lands in |
| `name` | must match the `name` in the skill's own front matter |
| `title` | a few words, shown in the list |
| `description` | one line, shown in the list |
| `summary` | a sentence or two, shown when the entry is highlighted |
| `tags` | what it is about; used for filtering |
| `version` | bumped when the skill changes, so an installed copy knows it is behind |
| `updated` | the date of that change |
| `path` | the folder under `skills/`, with a trailing slash |
| `files` | every file to fetch, relative to `path` |
| `bytes` | roughly how large, so the size can be shown before downloading |

`base` at the top of the catalogue is where the client fetches from. It points
at this branch through `raw.githubusercontent.com`; changing it moves the whole
library somewhere else without touching a line of the program.

## How it reaches a user

```
comodor skills browse        the catalogue, with what is installed marked
comodor skills add <id>      fetch one into ~/.comodor/skills/
comodor skills update        refetch anything whose version has moved
```

The catalogue is cached and revalidated with an `ETag`, so the common case
costs one conditional request and no download at all.
