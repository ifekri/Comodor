# Comodor catalogues

Lists Comodor reads at runtime, kept off `main` so that changing one needs no
release.

Nothing else lives on this branch. It has no source, no tests and no history in
common with `main` — it is an orphan branch, like `skills`, so a clone of the
project does not carry it and editing a catalogue cannot break a build.

```
local-models.json    models that can be downloaded and run on the machine
```

## Why it is not on `main`

A catalogue that ships inside the package can only change when the package
does. The Dockerfile spent eleven releases pinned to a version for exactly that
reason, on a branch nobody's change went past.

The same shape of problem applies here in reverse: a new model, a corrected
size, a URL that moved. None of those is a code change, and none of them should
wait for one.

## Why it is not on `skills`

`skills` distributes skills. This distributes data the program reads. They
change for different reasons, by different people, at different rates, and one
branch holding both means every skill edit is a chance to break the model
picker.

## What reads this

`src/comodor/local/catalogue.py` on `main`, at most once a day, with three
fallbacks behind it:

```
1  a cached copy less than 24 hours old
2  this file                                  ← live
3  the cached copy however old it is
4  the snapshot bundled in the package
```

So a broken file here is survivable and an unreachable one is invisible. That
is deliberate — somebody with no network still gets a list — and it is also why
`catalogue-health.yml` on `main` checks this URL on a schedule rather than
trusting that a failure would be noticed.

## local-models.json

```jsonc
{
  "version": 1,             // the schema. A higher number is read as far as
                            // it can be, not refused.
  "updated": "2026-08-25",
  "models": [
    {
      "id":   "…",          // required. Becomes the filename on disk.
      "url":  "https://…",  // required, and https — refused otherwise
      "size": 986048800,    // required. Bytes, exact, a positive integer.

      "sha256": "…",        // strongly advised: a download is not finished
                            // until the bytes hash to this
      "needs_ram_gb": 4,    // strongly advised: lets a machine refuse before
                            // spending an hour on the download

      "name": "…", "description": "…", "context": 32768,
      "parameters": "1.5B", "quantization": "Q4_K_M",
      "license": "…", "good_at": ["code"], "tools": true, "vision": false
    }
  ]
}
```

Only `id`, `url` and `size` are required. Anything omitted is reported as
unknown rather than guessed — a wrong number here costs somebody a download and
a crash. One malformed entry is skipped on its own; it does not empty the list.

**Do not type a size or a checksum.** Read them:

```bash
curl -s 'https://huggingface.co/api/models/OWNER/REPO?blobs=true' |
  python -c "import json,sys;[print(f['rfilename'], f['size'], f.get('lfs',{}).get('sha256')) for f in json.load(sys.stdin)['siblings']]"
```

`needs_ram_gb` is the working set, not the file size: the weights plus the
context window plus room for the process. Understating it costs somebody a
download and a crash, so round it up.

## Changing a catalogue

Branch from here, open a pull request against `catalogues`, and delete the
branch after it merges. The health check on `main` validates what is published;
a pull request is where a mistake is cheap to find.

Never merge this branch into `main`, and never merge `main` into it. They share
no history and are not meant to.
