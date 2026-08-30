# Releasing Comodor

Two workflows do the work. `ci.yml` runs on every push and pull request;
`release.yml` builds and publishes when a version tag is pushed.

## The tag is the version

Nothing in the tree carries a version number. `hatch-vcs` derives it from the
most recent tag at build time and writes `src/comodor/_version.py`, which is
generated, git-ignored, and what `__version__` reads.

So a release is a tag and nothing else:

```bash
git tag v0.2.1 && git push --tags
```

There is no file to bump, which means there is no file to forget. That was not
theoretical: the first `v0.2.1` tag failed its release twelve seconds in,
because the literal in `__init__.py` still said `0.2.0` and the workflow —
correctly — refused to publish a mismatched pair.

Between releases the version reads as `0.2.2.dev4+g56b14a7`: the next patch
number, how many commits past the tag you are, and which commit. A source tree
that has never been built reports `0.0.0+source`.

**The checkout must be deep.** `actions/checkout` fetches one commit by default,
which has no tags in it, and every build would come out as `0.1.dev1`.
`release.yml` sets `fetch-depth: 0` for exactly this reason.

## One-time setup: PyPI trusted publishing

`release.yml` publishes with **trusted publishing** — GitHub mints a short-lived
OIDC token that PyPI verifies. No API token is stored in the repository, so
there is nothing to leak and nothing to rotate.

`comodor` is already on PyPI, so this is a normal publisher rather than a
pending one — and **0.1.0 cannot be republished**. PyPI never lets a version
number be reused, even after a delete, so shipping a change always means
bumping the version first.

1. Sign in to <https://pypi.org> → **Your account** → **Publishing**.
2. Under **Add a new pending publisher**, choose GitHub and fill in:

   | Field | Value |
   |---|---|
   | PyPI project name | `comodor` |
   | Owner | `ifekri` |
   | Repository name | `Comodor` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. Save. The project is created on PyPI the first time the workflow publishes.

The `pypi` environment is also where you can add a required reviewer, if you
would rather every release paused for a human.

<details>
<summary>If you would rather use an API token</summary>

Trusted publishing is better, but a token works. Create one scoped to the
project, store it as the repository secret `PYPI_API_TOKEN`, then replace the
publish step in `release.yml` with:

```yaml
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}
```

and drop the `id-token: write` permission.
</details>

## Cutting a release

```bash
git tag v0.2.1
git push origin main --tags
```

That is the whole of it. Pushing the tag runs `release.yml`, which:

1. builds the sdist and the wheel, with the version taken from the tag;
2. reads the version back off the wheel filename — the answer that is actually
   going to PyPI — and **refuses to continue if it is not the tag**. It cannot
   disagree unless something is badly wrong, such as a shallow checkout; PyPI
   never lets a version number be reused, even after a delete, so the cost of
   finding out afterwards is a number gone for good;
3. runs `twine check --strict` over the metadata PyPI will render;
4. installs the wheel into a clean virtual environment and runs
   `comodor --version`, so a distribution that cannot start never ships, and
   checks that what it prints is the tag;
5. publishes to PyPI;
6. creates the GitHub release as a **draft**, attaches the sdist and wheel, and
   publishes it.

## Push the tag; do not create the release by hand

This repository has **immutable releases** turned on. Once a release is
published its assets are frozen, so the files have to go on while it is still a
draft — which is the order step 6 uses.

Creating the release in the web interface publishes it immediately. The tag push
then starts the workflow, which arrives to find a release it cannot add anything
to. That is what happened to `v0.20.2`:

```
Cannot upload asset comodor-0.20.2.tar.gz to an immutable release.
```

**The package had already reached PyPI.** Only the file attachment failed, and
a red cross on a job called "Release" said the wrong thing about a release that
worked.

The workflow no longer fails in that case — it says the release was already
published, that nothing is broken, and that the package is on PyPI. But the
files will be missing from the release page, so:

```bash
git tag v0.2.1
git push origin main --tags       # and nothing else
```

Let the workflow make the release. If you want to write the notes yourself,
make the release a **draft** first and leave it as a draft; the workflow will
attach the files and publish it.

## Two ways to run it

**Dry run** — Actions → Release → *Run workflow*, leaving **dry run** ticked.
Everything up to publishing happens, and the run summary says plainly that
nothing was published. Use it to rehearse.

**Publish by hand** — the same, with **dry run** unticked. Useful for the first
release, or to recover from a failed one. The version published is whatever
`pyproject.toml` says.

**Publish by tag** — the normal path, described above.

A run that publishes nothing still finishes green, so read the run summary: it
states which of the two happened.

## After the first release

Check that the site's install commands work end to end, since that is what the
front page tells people to run:

```bash
curl -fsSL https://comodor.ai/install.sh | sh
comodor --version
```

Until the first release lands, the installers can still be pointed at the
repository:

```bash
COMODOR_INSTALL_REF=main curl -fsSL https://comodor.ai/install.sh | sh
```

## Versioning

`0.x` while the interface and the brain's schema are still moving. The brain
migrates itself in place (`BrainStore._add_missing_columns`), so an upgrade
keeps everything it has learned — that is a promise worth not breaking.
