"""The GitHub REST API, as much of it as Comodor uses.

Written against the project's own HTTP client rather than a library, for the
reason `pyproject.toml` states out loud: `pip install comodor` pulls in `rich`
and nothing else. A GitHub SDK would be the second dependency, and the part of
one this needs is a few hundred lines.

Three things this is careful about, each because getting it wrong is quiet:

**The default branch is read, never assumed.** `main` is a default for new
repositories and nothing more; `master`, `develop` and `trunk` are all in
active use. Assuming produces a pull request against a branch that does not
exist, and the error names a ref rather than the assumption.

**Pagination is followed to the end.** GitHub returns thirty of anything by
default and says so only in a `Link` header. Reading page one and stopping
gives an answer that is right for small repositories and silently wrong for
the ones where it matters.

**A rate limit is a wait, not a failure.** GitHub says when the window resets;
a client that treats 403 as an error turns a pause into a lost turn.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator

from ..net import http
from .tokens import InstallationToken, redact

API = "https://api.github.com"

#: What GitHub asks clients to send. The version pin matters: the API changes
#: shape behind it, and an unpinned client gets whatever is current on the day
#: it runs.
HEADERS = {
    "accept": "application/vnd.github+json",
    "x-github-api-version": "2022-11-28",
}

#: How long one call may take.
TIMEOUT = 30.0

#: How long to wait out a rate limit before giving up on it instead. A few
#: seconds is a pause; ten minutes is a turn that appears to have hung, and
#: saying so is better than sitting there.
MOST_WAITING = 90.0

#: Pages to follow before stopping. A repository with more than this many
#: pages of anything is a question that wants narrowing, not more pages.
MOST_PAGES = 40


class GitHubError(RuntimeError):
    """GitHub refused, or could not be reached. Safe to show."""


class NotConnected(GitHubError):
    """No installation covers this repository."""


class Refused(GitHubError):
    """403 or 404 with a token that should have worked.

    Its own class because the cause is nearly always a permission the app was
    not granted, and the answer is to widen the installation rather than to
    retry.
    """


class RateLimited(GitHubError):
    """The limit was hit and the reset is further away than we will wait."""

    def __init__(self, message: str, resets_in: float = 0.0) -> None:
        super().__init__(message)
        self.resets_in = resets_in


class GitHub:
    """One installation's view of GitHub.

    Built per operation rather than held: the token behind it expires, and an
    object that outlived its token would carry a stale one into next hour's
    request.
    """

    def __init__(self, token: Callable[[], InstallationToken],
                 timeout: float = TIMEOUT) -> None:
        #: A callable rather than a token, so a long sequence of calls
        #: refreshes mid-way instead of failing at minute sixty-one.
        self._token = token
        self.timeout = timeout
        #: Every call made, for the tests and for `--verbose`. Method and path
        #: only: a URL can carry a query, and a query can carry a token.
        self.calls: list[tuple[str, str]] = []

    def __repr__(self) -> str:      # pragma: no cover - debugging only
        return f"<GitHub calls={len(self.calls)}>"

    # -- the one place a request is made ---------------------------------- #

    def call(self, method: str, path: str, body: Any = None,
             params: dict[str, Any] | None = None) -> Any:
        """One request. Raises a `GitHubError` for anything that is not a 2xx.

        The token is fetched per call rather than per client, so a sequence
        that runs past the hour refreshes rather than failing partway.
        """
        url = path if path.startswith("http") else f"{API}/{path.lstrip('/')}"
        self.calls.append((method.upper(), _without_query(url)))

        headers = dict(HEADERS)
        headers["authorization"] = f"Bearer {self._token().token}"

        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["content-type"] = "application/json"

        deadline = time.monotonic() + MOST_WAITING
        while True:
            try:
                answer = http.request(method.upper(), url, data=payload,
                                      headers=headers, params=params,
                                      timeout=self.timeout)
            except Exception as problem:
                raise GitHubError(
                    f"could not reach GitHub: {redact(problem)}") from None

            if answer.status_code == 403 or answer.status_code == 429:
                wait = _rate_limit_wait(answer)
                if wait and time.monotonic() + wait < deadline:
                    time.sleep(wait)
                    continue
                if wait:
                    raise RateLimited(
                        f"GitHub's rate limit resets in {int(wait)}s",
                        resets_in=wait)

            if 200 <= answer.status_code < 300:
                return _decode(answer)

            raise _failure(answer, method, url)

    def paged(self, path: str, params: dict[str, Any] | None = None,
              key: str = "") -> Iterator[dict[str, Any]]:
        """Every item across every page.

        `key` names the field holding the list on endpoints that wrap it —
        `/installation/repositories` answers `{"repositories": [...]}` where
        `/repos/x/y/issues` answers a bare array.
        """
        asked = dict(params or {})
        asked.setdefault("per_page", 100)
        url = path
        pages = 0

        while url and pages < MOST_PAGES:
            answer = self._raw("GET", url, params=asked if pages == 0 else None)
            body = _decode(answer)
            items = body.get(key, []) if (key and isinstance(body, dict)) else body
            if not isinstance(items, list):
                return
            yield from (item for item in items if isinstance(item, dict))

            url = _next_page(answer)
            pages += 1

    def _raw(self, method: str, path: str,
             params: dict[str, Any] | None = None) -> Any:
        """A request whose `Response` is wanted, not only its body.

        Pagination needs the `Link` header, which `call` discards.
        """
        url = path if path.startswith("http") else f"{API}/{path.lstrip('/')}"
        self.calls.append((method.upper(), _without_query(url)))
        headers = dict(HEADERS)
        headers["authorization"] = f"Bearer {self._token().token}"
        try:
            answer = http.request(method, url, headers=headers, params=params,
                                  timeout=self.timeout)
        except Exception as problem:
            raise GitHubError(
                f"could not reach GitHub: {redact(problem)}") from None
        if not (200 <= answer.status_code < 300):
            raise _failure(answer, method, url)
        return answer

    # -- repositories ------------------------------------------------------ #

    def repository(self, owner: str, name: str) -> dict[str, Any]:
        return self.call("GET", f"repos/{owner}/{name}")

    def default_branch(self, owner: str, name: str) -> str:
        """The branch this repository actually calls its default.

        Read rather than assumed. `main` is what new repositories get and is
        not what every repository has.
        """
        branch = str(self.repository(owner, name).get("default_branch") or "")
        if not branch:
            raise GitHubError(
                f"{owner}/{name} reports no default branch")
        return branch

    def repositories(self) -> list[dict[str, Any]]:
        """Everything this installation can see."""
        return list(self.paged("installation/repositories",
                               key="repositories"))

    # -- reading ------------------------------------------------------------ #

    def read_file(self, owner: str, name: str, path: str,
                  ref: str = "") -> tuple[str, str]:
        """One file's text and its blob sha.

        The sha comes back because updating a file requires it: GitHub uses it
        to refuse a write that would clobber a change made since the read.
        """
        import base64

        params = {"ref": ref} if ref else None
        found = self.call("GET", f"repos/{owner}/{name}/contents/{path}",
                          params=params)
        if isinstance(found, list):
            raise GitHubError(f"{path} is a directory, not a file")
        content = str(found.get("content") or "")
        encoding = str(found.get("encoding") or "")
        if encoding != "base64":
            raise GitHubError(f"{path} came back as {encoding or 'nothing'}")
        text = base64.b64decode(content).decode("utf-8", "replace")
        return text, str(found.get("sha") or "")

    def list_directory(self, owner: str, name: str, path: str = "",
                       ref: str = "") -> list[dict[str, Any]]:
        params = {"ref": ref} if ref else None
        found = self.call("GET",
                          f"repos/{owner}/{name}/contents/{path}".rstrip("/"),
                          params=params)
        return found if isinstance(found, list) else [found]

    def commits(self, owner: str, name: str, sha: str = "",
                path: str = "") -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if sha:
            params["sha"] = sha
        if path:
            params["path"] = path
        return list(self.paged(f"repos/{owner}/{name}/commits", params))

    def diff(self, owner: str, name: str, base: str, head: str) -> dict[str, Any]:
        return self.call("GET", f"repos/{owner}/{name}/compare/{base}...{head}")

    # -- branches ----------------------------------------------------------- #

    def branch_head(self, owner: str, name: str, branch: str) -> str:
        found = self.call("GET", f"repos/{owner}/{name}/git/ref/heads/{branch}")
        return str((found.get("object") or {}).get("sha") or "")

    def create_branch(self, owner: str, name: str, branch: str,
                      from_sha: str) -> dict[str, Any]:
        return self.call("POST", f"repos/{owner}/{name}/git/refs", {
            "ref": f"refs/heads/{branch}",
            "sha": from_sha,
        })

    # -- writing ------------------------------------------------------------ #

    def write_file(self, owner: str, name: str, path: str, text: str,
                   message: str, branch: str, sha: str = "") -> dict[str, Any]:
        """Create or update one file, as one commit.

        `sha` is the blob's, from a previous read. Passing it makes the write
        conditional: GitHub refuses if the file changed underneath, rather
        than overwriting somebody else's commit.
        """
        import base64

        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        return self.call("PUT", f"repos/{owner}/{name}/contents/{path}", body)

    # -- issues and pull requests ------------------------------------------- #

    def issues(self, owner: str, name: str, state: str = "open"
               ) -> list[dict[str, Any]]:
        return list(self.paged(f"repos/{owner}/{name}/issues",
                               {"state": state}))

    def issue(self, owner: str, name: str, number: int) -> dict[str, Any]:
        return self.call("GET", f"repos/{owner}/{name}/issues/{number}")

    def comment(self, owner: str, name: str, number: int, text: str
                ) -> dict[str, Any]:
        """A comment on an issue or a pull request.

        One endpoint for both: GitHub models a pull request as an issue with
        extra fields, and its comments live on the issue.
        """
        return self.call("POST",
                         f"repos/{owner}/{name}/issues/{number}/comments",
                         {"body": text})

    def pull_requests(self, owner: str, name: str, state: str = "open"
                      ) -> list[dict[str, Any]]:
        return list(self.paged(f"repos/{owner}/{name}/pulls", {"state": state}))

    def pull_request(self, owner: str, name: str, number: int) -> dict[str, Any]:
        return self.call("GET", f"repos/{owner}/{name}/pulls/{number}")

    def open_pull_request(self, owner: str, name: str, *, title: str,
                          head: str, base: str, body: str = "",
                          draft: bool = False) -> dict[str, Any]:
        return self.call("POST", f"repos/{owner}/{name}/pulls", {
            "title": title, "head": head, "base": base,
            "body": body, "draft": bool(draft),
        })

    def update_pull_request(self, owner: str, name: str, number: int,
                            **fields: Any) -> dict[str, Any]:
        return self.call("PATCH", f"repos/{owner}/{name}/pulls/{number}",
                         {k: v for k, v in fields.items() if v is not None})

    def reviews(self, owner: str, name: str, number: int
                ) -> list[dict[str, Any]]:
        return list(self.paged(f"repos/{owner}/{name}/pulls/{number}/reviews"))

    # -- what CI said -------------------------------------------------------- #

    def checks(self, owner: str, name: str, ref: str) -> list[dict[str, Any]]:
        return list(self.paged(f"repos/{owner}/{name}/commits/{ref}/check-runs",
                               key="check_runs"))

    def statuses(self, owner: str, name: str, ref: str) -> dict[str, Any]:
        return self.call("GET", f"repos/{owner}/{name}/commits/{ref}/status")

    def workflow_runs(self, owner: str, name: str, branch: str = ""
                      ) -> list[dict[str, Any]]:
        params = {"branch": branch} if branch else None
        return list(self.paged(f"repos/{owner}/{name}/actions/runs", params,
                               key="workflow_runs"))


# --------------------------------------------------------------------------- #
# the parts that are not the API surface
# --------------------------------------------------------------------------- #


def _decode(answer: Any) -> Any:
    if answer.status_code == 204 or not (answer.content or b""):
        return {}
    try:
        return json.loads(answer.content.decode("utf-8", "replace"))
    except ValueError:
        raise GitHubError("GitHub sent something that is not JSON") from None


def _failure(answer: Any, method: str, url: str) -> GitHubError:
    """One exception for a refusal, with GitHub's own words where it gave any.

    Everything is passed through `redact`. The message is shown to the user
    and may be written to a session transcript, and an error carrying an
    installation token would put a credential in both.
    """
    detail = ""
    try:
        body = json.loads(answer.content.decode("utf-8", "replace"))
        detail = str(body.get("message") or "")
    except Exception:
        pass

    where = f"{method.upper()} {_without_query(url)}"
    said = f": {redact(detail)}" if detail else ""

    if answer.status_code in (401, 403, 404):
        return Refused(
            f"GitHub refused {where} ({answer.status_code}){said}. "
            f"Usually a permission the app was not granted, or a repository "
            f"the installation cannot see.")
    return GitHubError(f"{where} answered {answer.status_code}{said}")


def _rate_limit_wait(answer: Any) -> float:
    """Seconds until the limit resets, or 0 if this is not a rate limit.

    Two headers, because GitHub uses two mechanisms: a primary limit with a
    remaining count and a reset time, and a secondary one that answers with
    `Retry-After`.
    """
    retry_after = answer.headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass

    remaining = answer.headers.get("x-ratelimit-remaining")
    reset = answer.headers.get("x-ratelimit-reset")
    if remaining == "0" and reset:
        try:
            return max(0.0, float(reset) - time.time())
        except ValueError:
            pass
    return 0.0


def _next_page(answer: Any) -> str:
    """The `rel="next"` URL from a Link header, or empty.

    Followed rather than counted: GitHub's own pagination is the only thing
    that knows when it has finished, and incrementing a page number until an
    empty answer makes one request too many every time.
    """
    link = answer.headers.get("link") or ""
    for part in link.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        if 'rel="next"' in section[1].replace(" ", "").replace("'", '"'):
            return section[0].strip().strip("<>")
    return ""


def _without_query(url: str) -> str:
    """A URL safe to record. Queries can carry tokens; paths do not."""
    return url.split("?", 1)[0]
