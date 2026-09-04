"""From `owner/name` to a GitHub client that may act on it.

Every repository operation goes through here, and it is three questions in
order, each of which can say no:

    owner/name
        → which installation covers this owner?          (or: not connected)
        → was the app granted what this operation needs? (or: name what to add)
        → a token for that installation                  (minted, cached)
        → GitHub

The second question is the one worth having. Without it a missing permission
surfaces as a 403 from the middle of a sequence — after a branch has been
created, say — and the message names an endpoint rather than the setting to
change. Asked first, it is a sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import Config, GitHubInstallation
from .api import GitHub, NotConnected, Refused
from .tokens import Tokens

#: What each operation needs, and at what level. Read from the installation's
#: own reported permissions rather than assumed from the app's manifest: an
#: installation can be narrower than the app asks for, and often is.
NEEDS = {
    "read": [("metadata", "read"), ("contents", "read")],
    "write": [("contents", "write")],
    "issues": [("issues", "read")],
    "comment": [("issues", "write")],
    "pulls": [("pull_requests", "read")],
    "open_pull_request": [("pull_requests", "write"), ("contents", "write")],
    "checks": [("checks", "read")],
    "actions": [("actions", "read")],
}

#: `owner/name`, and nothing that is not. Deliberately strict: this string
#: becomes a URL path, and a name carrying `..` or a slash would address a
#: different repository than the one written down.
REPOSITORY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)$")


@dataclass(frozen=True)
class Target:
    """One repository, and the installation that reaches it."""

    owner: str
    name: str
    installation: GitHubInstallation

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def split(repository: str) -> tuple[str, str]:
    """`owner/name` as two parts, or a refusal saying what was wrong."""
    match = REPOSITORY.match((repository or "").strip())
    if not match:
        raise NotConnected(
            f"{repository!r} is not a repository. Write it as owner/name, "
            f"like ifekri/Comodor.")
    return match.group(1), match.group(2)


class Repositories:
    """Resolves repositories to installations, and hands out clients.

    Built once per session and held: the token cache inside it is the reason
    a turn touching six files makes one token request rather than six.
    """

    def __init__(self, config: Config, mint: Any) -> None:
        self.config = config
        self.tokens = Tokens(mint)

    def resolve(self, repository: str) -> Target:
        """Which installation covers this repository.

        By owner, because that is what an installation is scoped to. Whether
        the *repository* is in the installation's selection is GitHub's
        question, and asking it here would mean holding a list that goes stale
        the moment somebody adds a repository.
        """
        owner, name = split(repository)
        installation = self.config.github.find(owner)
        if installation is None:
            known = ", ".join(sorted(
                one.account_login for one in self.config.github.installations))
            raise NotConnected(
                f"no GitHub installation covers {owner}. "
                + (f"Connected: {known}. " if known else "")
                + "Run `comodor github connect` to add one.")
        return Target(owner=owner, name=name, installation=installation)

    def check(self, target: Target, operation: str) -> None:
        """Refuse now, in words, rather than at GitHub with a 403."""
        for permission, level in NEEDS.get(operation, []):
            if not target.installation.may(permission, level):
                raise Refused(
                    f"the GitHub app is not allowed to {level} {permission} "
                    f"on {target.owner}. Widen the installation's permissions "
                    f"at github.com/settings/installations, then run "
                    f"`comodor github refresh`.")

    def client(self, repository: str, operation: str = "read"
               ) -> tuple[GitHub, Target]:
        """A client bound to the installation covering this repository."""
        target = self.resolve(repository)
        self.check(target, operation)

        installation_id = target.installation.installation_id

        def token():
            return self.tokens.for_installation(installation_id)

        return GitHub(token), target

    def forget(self, installation_id: int) -> None:
        """Drop a cached token — after a revocation, or a refusal."""
        self.tokens.forget(installation_id)


def branch_name(prefix: str, kind: str, subject: str) -> str:
    """`comodor/fix-the-thing`, from a prefix, a kind and a description.

    Named rather than generated so a person scanning their branches can see
    what opened each one, and cut to something git will accept: a ref may not
    contain a space, a tilde, a caret, a colon, or a run of dots.
    """
    kind = re.sub(r"[^a-z]", "", (kind or "change").lower()) or "change"
    words = re.sub(r"[^A-Za-z0-9]+", "-", (subject or "").strip().lower())
    words = re.sub(r"-+", "-", words).strip("-")[:48].strip("-")
    prefix = (prefix or "comodor/").rstrip("/") + "/"
    return f"{prefix}{kind}-{words}" if words else f"{prefix}{kind}"
