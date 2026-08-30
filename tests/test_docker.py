"""The container, checked from the repository that ships it.

These files spent eleven releases pinned to Comodor 0.9.0. Not because anyone
decided to stay there — because they lived on a branch of their own, so no
change to the agent ever went past them and nothing ever said they were stale.
Moving them to `main` is most of the fix; the rest is here, so that a change
which breaks the container fails on the machine that made it.

What is checked is what a person actually experiences when they run
`docker compose up`:

*It starts the browser interface.* There is no terminal in a container to
attach a TUI to, so the web server is not an option — it is the product.

*It prints an address that can be opened.* The server binds `0.0.0.0`, because
binding loopback inside a container hides the port from the machine that
started it. The address printed must not be the address bound: nobody can open
`http://0.0.0.0:8765`.

*Nothing carries a version number written by hand.* That is the bug this file
exists because of.

Building the image needs a Docker daemon and several minutes, so that happens
in CI (`.github/workflows/image.yml`, which runs on pull requests that touch
any of this). Everything here is about the contents of the files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
START = ROOT / "docker" / "start"
WORKFLOW = ROOT / ".github" / "workflows" / "image.yml"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# it is here at all
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", [DOCKERFILE, COMPOSE, START, WORKFLOW],
                         ids=lambda path: path.name)
def test_the_container_is_part_of_this_repository(path):
    """On `main`, beside the code. A file on a branch of its own is a file
    every change goes around."""
    assert path.is_file(), f"{path.relative_to(ROOT)} is missing"


# --------------------------------------------------------------------------- #
# the bug that started this
# --------------------------------------------------------------------------- #


def test_the_dockerfile_pins_no_version_by_default():
    """`ARG COMODOR_VERSION=0.9.0` is how the image stayed eleven releases
    behind. Empty means the newest release, which cannot go stale."""
    found = re.search(r"^ARG\s+COMODOR_VERSION=(.*)$", text(DOCKERFILE),
                      re.MULTILINE)

    assert found, "the Dockerfile no longer takes a version at all"
    assert found.group(1).strip() in ("", '""'), \
        f"a version is pinned by hand: {found.group(1)!r}"


def test_compose_pins_no_version_by_default():
    import yaml

    args = yaml.safe_load(text(COMPOSE))["services"]["comodor"]["build"]["args"]
    pinned = str(args.get("COMODOR_VERSION", ""))

    assert not re.fullmatch(r"\d+\.\d+\.\d+", pinned), \
        f"compose pins {pinned}, which somebody has to remember to change"


def test_a_version_can_still_be_pinned_on_purpose():
    """Reproducible builds need it. What must not happen is a default."""
    assert "--build-arg COMODOR_VERSION=" in text(DOCKERFILE)


def test_the_image_is_rebuilt_on_a_release():
    """The trigger that was missing. Without it a release ships and the
    published image stays where it was."""
    import yaml

    triggers = yaml.safe_load(text(WORKFLOW))
    on = triggers[True] if True in triggers else triggers["on"]

    assert "release" in on, "nothing rebuilds the image when a version ships"
    assert "pull_request" in on, \
        "a change to the Dockerfile has to prove the image still starts"


def test_the_workflow_uses_no_yaml_anchors():
    """GitHub Actions does not expand them, and the failure is a workflow whose
    path filter silently matches nothing."""
    body = text(WORKFLOW)

    assert "&" not in body.split("jobs:")[0].replace("&&", ""), \
        "an anchor in the triggers will not do what it looks like"


# --------------------------------------------------------------------------- #
# what happens when somebody runs it
# --------------------------------------------------------------------------- #


def test_the_web_interface_is_what_starts():
    """Not a shell, not the TUI. A container has no terminal of its own to put
    an interface on."""
    body = text(START)

    assert "comodor web" in body
    assert body.rstrip().endswith('"$@"'), "arguments must reach the server"


def test_it_binds_every_address_inside_the_container():
    """Loopback inside a container is invisible from outside it, so the
    interface would be unreachable by the person who started it."""
    assert "--host 0.0.0.0" in text(START)


def test_it_does_not_try_to_open_a_browser_in_a_container():
    assert "--no-browser" in text(START)


def test_the_port_is_published_to_this_machine_only():
    """Drop the `127.0.0.1` and the port is on every interface — and this port
    runs shell commands."""
    import yaml

    ports = yaml.safe_load(text(COMPOSE))["services"]["comodor"]["ports"]

    assert ports, "nothing is published, so nothing can be opened"
    for entry in ports:
        assert str(entry).startswith("127.0.0.1:"), \
            f"{entry} puts a shell on every interface of the machine"


def test_the_entrypoint_is_the_start_script():
    body = text(DOCKERFILE)

    assert 'ENTRYPOINT ["/usr/local/bin/comodor-start"]' in body
    assert "COPY --chown=comodor:comodor docker/start" in body


def test_the_start_script_is_made_executable():
    """A clone on Windows does not carry the executable bit, and the failure is
    the container exiting at once on the one file it runs."""
    assert "chmod +x /usr/local/bin/comodor-start" in text(DOCKERFILE)


def test_it_does_not_run_as_root():
    """The agent runs shell commands against a bind-mounted project. As uid 0
    a stray `chown` rewrites ownership of files on the host."""
    body = text(DOCKERFILE)

    assert "USER comodor" in body
    assert body.index("USER comodor") < body.index("ENTRYPOINT")


def test_the_healthcheck_runs_through_a_shell():
    """The exec form starts no shell, so `$(…)` would reach curl as a literal
    string and the container would never report healthy."""
    body = text(DOCKERFILE)
    healthcheck = body[body.index("HEALTHCHECK"):]

    assert "CMD test" in healthcheck, "an exec-form CMD cannot expand $(…)"
    assert "CMD [" not in healthcheck


# --------------------------------------------------------------------------- #
# the keys, which are silently useless when they are wrong
# --------------------------------------------------------------------------- #


def test_every_key_compose_passes_is_one_a_provider_reads():
    """`GEMINI_API_KEY` was in this file and nothing has ever read it — the
    catalogue calls it `GOOGLE_API_KEY`. A key passed under the wrong name is
    not passed, and nothing anywhere says so: the container starts, and the
    first task fails with an authentication error.
    """
    import yaml

    from comodor import catalogue

    known = {spec.env_key for spec in catalogue.CATALOGUE if spec.env_key}
    known |= {"COMODOR_WEB_TOKEN", "COMODOR_PROVIDER", "COMODOR_MODEL"}

    passed = set(yaml.safe_load(text(COMPOSE))["services"]["comodor"]
                 ["environment"])
    unknown = passed - known

    assert not unknown, f"nothing reads {sorted(unknown)}"


def test_the_common_providers_are_all_passed_through():
    import yaml

    passed = set(yaml.safe_load(text(COMPOSE))["services"]["comodor"]
                 ["environment"])

    for needed in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                   "GOOGLE_API_KEY", "XIAOMI_API_KEY"):
        assert needed in passed, f"{needed} never reaches the container"


# --------------------------------------------------------------------------- #
# it is findable
# --------------------------------------------------------------------------- #


def test_the_readme_says_docker_can_be_used():
    """It said nothing at all, so the only people who found the container were
    the ones who already knew it existed."""
    readme = text(ROOT / "README.md").lower()

    assert "docker" in readme, "the README does not mention it"
    assert "docker compose up" in readme or "docker run" in readme, \
        "the README mentions Docker without saying how to start it"


def test_the_documented_command_is_one_that_works():
    """`docs/docker.md` told people to clone a branch. The files are on `main`
    now, and instructions that send somebody to the old place are worse than
    none."""
    page = text(ROOT / "docs" / "docker.md")

    assert "-b docker" not in page, \
        "the documentation still sends people to the branch this replaced"
    assert "docker compose up" in page


# --------------------------------------------------------------------------- #
# the translations, where a stale command is hardest to notice
# --------------------------------------------------------------------------- #


TRANSLATIONS = sorted((ROOT / "docs").glob("*/docker.md"))


@pytest.mark.parametrize("page", TRANSLATIONS,
                         ids=lambda page: page.parent.name)
def test_no_translation_carries_a_command_that_no_longer_works(page):
    """The prose in these needs a person who speaks the language. The commands
    do not — they are the same in every one, and a reader who cannot check them
    against the English is exactly the reader a stale command strands."""
    body = text(page)

    for stale, why in [
        ("-b docker", "the container is on `main` now"),
        ("comodor-docker", "the clone no longer makes that directory"),
        ("GEMINI_API_KEY", "nothing reads it; the catalogue says GOOGLE_API_KEY"),
        ("0.9.0", "a version pinned by hand, which is the bug this fixed"),
    ]:
        assert stale not in body, f"{page.parent.name}: {stale!r} — {why}"


@pytest.mark.parametrize("page", TRANSLATIONS,
                         ids=lambda page: page.parent.name)
def test_every_translation_still_names_the_one_command(page):
    assert "docker compose up" in text(page)
