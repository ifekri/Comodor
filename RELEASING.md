# Releasing Comodor

Two workflows do the work. `ci.yml` runs on every push and pull request;
`release.yml` builds and publishes when a version tag is pushed.

## The version lives in one place

`src/comodor/__init__.py` holds `__version__`; `pyproject.toml` reads it from
there. Two copies drift, and the one that drifts is the one `comodor --version`
prints — so the tag check would pass while users were told something else.

Bump it there, and the tag must match:

```bash
git tag v0.2.0 && git push --tags
```

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
# 1. Bump the version — this is the number the tag must match.
#    pyproject.toml → [project] version = "0.2.0"

# 2. Commit it.
git add pyproject.toml
git commit -m "Release 0.2.0"

# 3. Tag and push.
git tag v0.2.0
git push origin main --tags
```

Pushing the tag runs `release.yml`, which:

1. reads the version out of `pyproject.toml`;
2. **refuses to continue if the tag and the version disagree** — PyPI never lets
   a version number be reused, even after a delete, so a mismatched pair is not
   something you can take back;
3. builds the sdist and the wheel;
4. runs `twine check --strict` over the metadata PyPI will render;
5. installs the wheel into a clean virtual environment and runs
   `comodor --version`, so a distribution that cannot start never ships;
6. publishes to PyPI;
7. attaches the files to a GitHub release with generated notes.

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
