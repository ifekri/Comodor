# Repositories on GitHub

Comodor reads and changes repositories that are checked out on your machine.
Connecting GitHub adds the ones that are not: read an issue, look at what CI
said, open a pull request against a repository you have never cloned.

It is a provider, not a foundation. Everything Comodor does to a local checkout
works with nothing connected, and disconnecting takes nothing away from it.

```bash
comodor github connect
```

That opens a browser, GitHub asks which account and which repositories, and a
line comes back to paste into the terminal. There is no personal access token
to make, store, or remember to rotate.

---

## What happens when you connect

```
comodor github connect
        │
        ├─ your machine generates a key pair for this connection
        │  the private half never leaves it
        │
        ├─ comodor.ai issues a short-lived signed state
        │  carrying your public key
        │
        ├─ browser opens github.com/apps/comodor/installations/new
        │
        ├─ you choose an account, then repositories
        │
        ├─ GitHub sends the browser back to comodor.ai, which
        │  asks GitHub to confirm who you are
        │
        ├─ you approve once more — this is the step that proves
        │  the installation is yours and not somebody else's
        │
        └─ the page shows a signed line; you paste it back
           it carries a grant naming your public key
```

### Why GitHub asks you twice

The first screen installs the app. The second signs you in, and it is not
ceremony: the installation id comes back to `comodor.ai` in a query string,
where anybody could put any number. Confirming that an installation *exists*
says nothing about whose it is.

So `comodor.ai` asks GitHub, as you, which installations you can reach, and
issues the grant only if the one in front of it is on that list. Somebody who
typed your installation id into their own connection reaches this step signed
in as themselves, is not on the list, and gets nothing.

The token GitHub issues for that check is used for one request and dropped. It
is not stored, not logged, not shown, and never sent to Comodor on your
machine — the agent never learns that step happened. Everything after it uses
an installation token, which is the app acting on the repositories you chose.

The line you paste is a **receipt**: it says which installation GitHub
confirmed, signed so it cannot be altered, and it expires in fifteen minutes.
It is not a password and it grants nothing on its own.

Why you copy it rather than the browser doing it silently: `comodor.ai` is a
static site with no database, and there is nowhere for it to leave a message
for your terminal. You are the one party present at both ends.

### Why the id from the URL is not enough

GitHub sends `installation_id` to `comodor.ai` as a query parameter, and a
query parameter is something anybody can type. Before anything is signed,
`comodor.ai` authenticates as the app and asks GitHub what that installation
is. What you paste is that verified answer, not the number from the URL.

### Why knowing an installation id gets you nothing

An installation id is not a credential. It is a small integer, it appears in
URLs, and other people can see it. So it is never what a request is granted
on.

What a request is granted on is the **grant**: `comodor.ai`'s signed statement
that installation *n* belongs to a particular public key. Every request that
could do something carries four things —

| | |
|---|---|
| the grant | says which installation, and which key speaks for it |
| a timestamp | so a captured request stops working |
| a nonce | so two requests in the same second are still distinct |
| a signature | over all of the above, made with your private key |

`comodor.ai` checks the grant is one it issued and unedited, then checks the
signature against the key the grant names, and only then reads the
installation id — **out of the grant, never out of the request**. A request
that merely names an id proves nothing and is refused before GitHub is
contacted.

Your private key is at `github/<installation id>.key` in Comodor's data
directory, written so only your account can read it. Losing it does not lose
access to anything on GitHub; it means this machine can no longer prove the
connection is its own, and `comodor github status` says so.

### What can and cannot be replayed

Stated plainly, because the honest version is short.

The state in the install URL is short-lived and signed, so it cannot be forged
or edited. It is **not** server-side one-time — marking one used needs
somewhere to write the mark, and `comodor.ai` has no database. Its nonce is
**not a secret** either: the payload is encoded, not encrypted, so anybody
holding the state can read it. The nonce is there so your terminal can tell its
own receipt from another attempt's, and nothing rests on it being unknown.

None of that gets anybody anything, because a state grants nothing. It names an
installation nobody has proved they own. What turns one into a connection is
the sign-in step above, and somebody replaying your state arrives there as
themselves.

A signed `/token` request can be replayed within its 120-second window by
somebody who captured it, which means breaking TLS first. Replay cannot widen
anything: the grant fixes the installation, so a replayed request mints exactly
what it always would have.

---

## What is stored, and where

On your machine, in `config.json`, under `github`:

```json
{
  "github": {
    "enabled": true,
    "allow_writes": false,
    "installations": [
      {
        "installation_id": 12345678,
        "account_login": "ifekri",
        "account_type": "User",
        "repository_selection": "selected",
        "permissions": { "contents": "write", "pull_requests": "write" },
        "grant": "g1.…"
      }
    ]
  }
}
```

**Nothing in there is a secret**, the grant included. It is a signed statement
about a public key, and it is useless to anybody who does not hold the private
half — which is not in this file. You can paste this config into a bug report.

**No token is in there.** A GitHub App does not have a long-lived credential to
store. It has a private key — held by the app, on the server, never on your
machine — which mints an access token that lasts an hour. Comodor asks for one
when it needs it and keeps it in memory for as long as it is useful.

That is also why there is no account to make and no password to set. The
installation belongs to the machine that completed the flow, and the file it
wrote is yours.

---

## Several accounts

A personal account and two organisations is three installations, and a
repository resolves to exactly one:

```bash
comodor github connect        # again, for the next account
comodor github status
```

```
Account      Kind          Repositories  May
ifekri       user          selected      contents:write, issues:write
comodor-ai   organization  all           contents:read, metadata:read
```

`ifekri/Comodor` uses the first. `comodor-ai/anything` uses the second, and
because that one is read-only it will decline to open a pull request — in
words, before it tries, naming what to widen.

---

## Reading and changing

Reading needs nothing beyond the connection:

```
Ask it: what does the CI say about the last commit on ifekri/Comodor?
        summarise the open issues on comodor-ai/site
        read src/index.ts from ifekri/Comodor and explain the retry logic
```

Changing is off until you say otherwise:

```bash
comodor github writes on
```

Then a change goes to a branch and a pull request:

```
comodor/fix-the-off-by-one
comodor/feature-add-a-flag
```

Never to the default branch, and never merged. That is checked rather than
conventional: passing the default branch by name is refused, and the default
branch is read from the repository rather than assumed to be `main`.

---

## When permissions change

Narrowing an installation on GitHub does not tell Comodor. Ask it:

```bash
comodor github refresh
```

It re-reads each installation and forgets any that have been uninstalled.

---

## Taking it away

```bash
comodor github disconnect ifekri
```

That forgets it here. The app may still be installed on GitHub — remove it at
**github.com/settings/installations** to revoke its access as well. The two are
separate on purpose: forgetting a connection on a laptop should not require
reaching GitHub, and revoking access should not depend on a laptop.

---

## What the app may do

Least privilege, and each one is here because something uses it:

| Permission | Level | Used for |
| --- | --- | --- |
| Metadata | Read | Mandatory for any app; reading a repository's default branch |
| Contents | Read & write | Reading files, creating a branch, committing to it |
| Pull requests | Read & write | Listing and opening pull requests, reading reviews |
| Issues | Read & write | Reading issues, and commenting on issues and pull requests |
| Checks | Read | What CI said about a commit |
| Actions | Read | Workflow runs |
| Commit statuses | Read | The older status API, which some repositories still use |

Not asked for, and not needed: administration, secrets, members, deploy keys,
workflow write. An app that can rewrite a workflow file can run arbitrary code
in the repository's CI, and nothing here needs that.

---

## What it will not do

**A comment cannot start a turn.** The webhook verifies GitHub's signature,
records what happened, and stops. Dispatching agent work from a comment turns
"type a sentence in a comment box" into "run a command on somebody's machine" —
and on a public repository, anybody can comment.

**Nothing read from GitHub is an instruction.** An issue body, a comment, a
commit message and a file are written by whoever could open one. They reach the
model labelled as data, with what they are and who could have written them.

**No secret is ever printed.** The private key, the JWT, the installation
token, and the webhook secret are absent from every message, error and log —
and anything that looks like a GitHub credential is stripped from an error
before it is shown.

---

[Configuration](configuration.md) · [What it will and will not do](safety.md) ·
[The CLI](cli.md)
