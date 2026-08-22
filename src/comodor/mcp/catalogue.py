"""MCP servers worth offering out of the box.

The same reasoning as the provider catalogue: a list of names is not a feature.
What makes one usable is knowing its command, what it needs, and what it will
be able to see once it is running — so choosing one is a single decision rather
than a research project.

Nothing here is installed or run until the user enables it. Each entry records
what it can reach, because "filesystem access" and "your GitHub account" are
not the same kind of permission and the difference belongs in front of the
person deciding, not in a README.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServerSpec:
    """One MCP server Comodor knows how to start."""

    id: str
    label: str
    #: What it gives the agent, in one line.
    blurb: str
    command: str
    args: tuple[str, ...] = ()
    #: Environment variables it needs, and what each is for.
    needs_env: tuple[tuple[str, str], ...] = ()
    #: A directory argument the user has to supply, described.
    needs_path: str = ""
    #: What it can reach once running. Shown before enabling.
    reach: str = ""
    #: Where to read about it.
    url: str = ""
    #: What has to be installed for the command to exist.
    requires: str = "Node.js (npx)"
    rank: int = 50


#: `npx -y` and `uvx` both fetch on first use and cache afterwards, so neither
#: needs a separate install step. That is the whole reason these are the two
#: launchers used: anything else would mean telling the user to go and install
#: a package before they could try a server.
CATALOGUE: tuple[ServerSpec, ...] = (
    ServerSpec(
        id="filesystem",
        label="Filesystem",
        blurb="Read and write files in a directory you choose.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-filesystem"),
        needs_path="the directory it may read and write",
        reach="Only the directory you name. Nothing above it.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        rank=1,
    ),
    ServerSpec(
        id="git",
        label="Git",
        blurb="Read history, diffs and blame from a repository.",
        command="uvx",
        args=("mcp-server-git",),
        needs_path="the repository to read",
        reach="One repository, read-only.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/git",
        requires="uv (uvx)",
        rank=2,
    ),
    ServerSpec(
        id="github",
        label="GitHub",
        blurb="Issues, pull requests, code search and releases.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-github"),
        needs_env=(("GITHUB_PERSONAL_ACCESS_TOKEN",
                    "a token from github.com/settings/tokens"),),
        reach="Everything your token can reach. Scope it narrowly.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/github",
        rank=3,
    ),
    ServerSpec(
        id="fetch",
        label="Fetch",
        blurb="Retrieve a URL and convert it to Markdown for reading.",
        command="uvx",
        args=("mcp-server-fetch",),
        reach="Any URL the agent asks for, from your machine.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
        requires="uv (uvx)",
        rank=4,
    ),
    ServerSpec(
        id="memory",
        label="Memory (knowledge graph)",
        blurb="A persistent graph of entities and relations across sessions.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-memory"),
        reach="Its own store. Nothing else.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
        rank=5,
    ),
    ServerSpec(
        id="sequential-thinking",
        label="Sequential thinking",
        blurb="A scratchpad for working a hard problem through in steps.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-sequential-thinking"),
        reach="Nothing outside the conversation.",
        url="https://github.com/modelcontextprotocol/servers/"
            "tree/main/src/sequentialthinking",
        rank=6,
    ),
    ServerSpec(
        id="sqlite",
        label="SQLite",
        blurb="Query and inspect a SQLite database.",
        command="uvx",
        args=("mcp-server-sqlite", "--db-path"),
        needs_path="the .db file to open",
        reach="One database file.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
        requires="uv (uvx)",
        rank=7,
    ),
    ServerSpec(
        id="postgres",
        label="PostgreSQL",
        blurb="Inspect schemas and run read-only queries.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-postgres"),
        needs_path="the connection string, as postgresql://…",
        reach="Read-only, on the database in the connection string.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
        rank=8,
    ),
    ServerSpec(
        id="puppeteer",
        label="Browser (Puppeteer)",
        blurb="Drive a real browser: navigate, click, screenshot.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-puppeteer"),
        reach="Any site it is pointed at, and it downloads a browser on first use.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer",
        rank=9,
    ),
    ServerSpec(
        id="brave-search",
        label="Brave Search",
        blurb="Web and local search results.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-brave-search"),
        needs_env=(("BRAVE_API_KEY", "a key from brave.com/search/api"),),
        reach="The Brave search API.",
        url="https://github.com/modelcontextprotocol/servers/"
            "tree/main/src/brave-search",
        rank=10,
    ),
    ServerSpec(
        id="slack",
        label="Slack",
        blurb="Read channels and post messages.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-slack"),
        needs_env=(("SLACK_BOT_TOKEN", "a bot token, xoxb-…"),
                   ("SLACK_TEAM_ID", "your workspace id")),
        reach="Every channel the bot is in.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
        rank=11,
    ),
    ServerSpec(
        id="time",
        label="Time and time zones",
        blurb="The current time anywhere, and conversions between zones.",
        command="uvx",
        args=("mcp-server-time",),
        reach="Nothing. It only does arithmetic on clocks.",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/time",
        requires="uv (uvx)",
        rank=12,
    ),
)


def get(server_id: str) -> ServerSpec | None:
    for spec in CATALOGUE:
        if spec.id == server_id:
            return spec
    return None


def offered() -> list[ServerSpec]:
    """The catalogue, in the order it should be shown."""
    return sorted(CATALOGUE, key=lambda spec: (spec.rank, spec.label))


def needing_setup(spec: ServerSpec) -> list[str]:
    """What the user must supply before this one can run."""
    wanted = [f"{name} — {why}" for name, why in spec.needs_env]
    if spec.needs_path:
        wanted.append(f"a path — {spec.needs_path}")
    return wanted
