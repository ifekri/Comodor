# Comodor in a container: the agent, its browser, and nothing else.
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

# The version to install. Pinned by default so a rebuild is reproducible;
# `--build-arg COMODOR_VERSION=` (empty) takes the newest release instead.
ARG COMODOR_VERSION=0.8.9

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

COPY --chown=comodor:comodor start /usr/local/bin/comodor-start
RUN chmod +x /usr/local/bin/comodor-start

# The browser interface, because that is what a container can offer: there is
# no terminal to attach a TUI to that the user did not already have.
ENTRYPOINT ["/usr/local/bin/comodor-start"]
