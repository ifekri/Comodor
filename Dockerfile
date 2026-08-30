# Comodor in a container: the agent, its browser, and nothing else.
#
# This file lives on `main`, next to the code it installs. It used to live on a
# branch of its own, which is why it spent eleven releases pinned to 0.9.0 —
# nothing that changed the agent ever touched the branch that shipped it. A
# file nobody's change goes past is a file that goes stale, and no amount of
# remembering fixes that.
#
# **Nothing is pinned by default.** `ARG COMODOR_VERSION` is empty, so a build
# installs the newest release and cannot be out of date. Pass a version for a
# reproducible build:
#
#     docker build --build-arg COMODOR_VERSION=0.21.0 .
#
# Two decisions worth explaining, because both cost image size and both are
# deliberate.
#
# **Chromium is installed.** The browser tool drives a browser the machine
# already has, which is true of almost every laptop and true of almost no
# container. Without it the agent silently falls back to fetching pages as
# text — a real feature quietly downgraded, in the one environment where the
# user cannot fix it by installing something. So it is here, and it is the
# distribution's own build rather than a download.
#
# **git is installed.** A coding agent that cannot read history, make a branch
# or produce a diff is a worse tool, and `delegate` works in a git worktree.
#
# Built in two stages so the compilers and caches used to install do not travel
# in the image that runs.

# --------------------------------------------------------------------------- #
FROM python:3.13-slim-bookworm AS build

# Empty means the newest release on PyPI. A version here pins it.
ARG COMODOR_VERSION=

RUN python -m venv /opt/comodor \
 && /opt/comodor/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/comodor/bin/pip install --no-cache-dir \
      "comodor${COMODOR_VERSION:+==$COMODOR_VERSION}"

# --------------------------------------------------------------------------- #
FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.title="Comodor" \
      org.opencontainers.image.description="A self-improving terminal coding agent, in a browser." \
      org.opencontainers.image.source="https://github.com/ifekri/Comodor" \
      org.opencontainers.image.licenses="MIT"

# chromium: the browser tool, which has nothing to drive otherwise.
# chromium-sandbox: without it Chromium will not start at all here, and the
#        answer found everywhere online is --no-sandbox. That is the wrong
#        trade: the agent opens pages a model chose, so the renderer sandbox is
#        doing real work. This is the setuid helper Debian ships for exactly
#        this case, and it costs a couple of hundred kilobytes.
# git, ripgrep, curl, ca-certificates: what a coding agent reaches for.
# fonts: a headless Chromium with no fonts renders every page as empty boxes,
#        which makes a screenshot worse than useless.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      chromium \
      chromium-sandbox \
      git \
      ripgrep \
      curl \
      ca-certificates \
      fonts-dejavu-core \
      fonts-liberation \
      fonts-noto-core \
      fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/comodor /opt/comodor
ENV PATH="/opt/comodor/bin:${PATH}"

# Not root. The agent runs shell commands, and it should not run them as uid 0
# in a container that has the project bind-mounted from the host — a stray
# `chown` would then rewrite the ownership of files outside it.
RUN useradd --create-home --uid 1000 comodor \
 && mkdir -p /work /home/comodor/.comodor \
 && chown -R comodor:comodor /work /home/comodor
USER comodor

# Where the config, the brain and the session transcripts live. Declared so
# `docker run` without a volume still keeps them for the life of the container,
# and so compose can give them a named volume that outlives it.
VOLUME ["/home/comodor/.comodor"]

WORKDIR /work

# Nothing points at the browser: the tool already looks for "chromium" by name
# and finds /usr/bin/chromium on its own.
ENV COMODOR_WEB_PORT=8765 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

COPY --chown=comodor:comodor docker/start /usr/local/bin/comodor-start
# Explicitly, rather than relying on the mode in the checkout: a clone on
# Windows does not carry the executable bit, and the failure is the container
# exiting immediately with "permission denied" on the one file it runs.
RUN chmod +x /usr/local/bin/comodor-start

# A HEALTHCHECK, so `docker ps` and compose can tell "starting" from "wedged".
# 401 is the healthy answer: the server is up and refusing a request that
# carries no token. Anything else means it is not serving.
#
# Shell form on purpose. The exec form does not start a shell, so `$(…)` would
# be passed to curl as a literal string and the check would never pass.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
#
# No `-f`: it makes curl exit non-zero on an HTTP error without printing the
# code, and the code is the whole answer here.
  CMD test "$(curl -sS -o /dev/null -w '%{http_code}' \
      "http://127.0.0.1:${COMODOR_WEB_PORT}/" || true)" = "401"

# The browser interface, because that is what a container can offer: there is
# no terminal to attach a TUI to that the user did not already have.
ENTRYPOINT ["/usr/local/bin/comodor-start"]
