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
