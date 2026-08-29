"""Handing the bot to the operating system, so a reboot brings it back.

`comodor <channel> start --background` survives closing the terminal and logging
out. It does not survive the machine restarting, and nothing a program starts
for itself can — that is the operating system's job, and every platform has a
place to ask for it.

    systemd    Linux, a *user* unit under ~/.config/systemd/user
    launchd    macOS, a LaunchAgent in ~/Library/LaunchAgents
    schtasks   Windows, a task that runs at logon

A user service on all three, never a system one. A system service runs as root
or as SYSTEM, and this is an agent that reads and writes a person's files with
their credentials — running it with more authority than the person who owns
those files buys nothing and costs everything if it is ever wrong.

Writing the unit and enabling it are separate steps here, and the file is
printed before anything is enabled, so nobody is asked to trust a daemon
definition they have not read.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from . import Channel


@dataclass
class Unit:
    """One platform's answer to "start this at login"."""

    kind: str
    path: Path
    body: str
    enable: list[list[str]]
    disable: list[list[str]]
    supported: bool = True
    why: str = ""


def _command(config: Config, channel: Channel) -> list[str]:
    """How the service starts the bot.

    The interpreter and the module, not the `comodor` console script: a service
    starts with a bare environment, and the directory a `pipx` or `uv tool`
    install puts that script in is on the PATH of a login shell rather than on
    the PATH of a daemon.
    """
    return [sys.executable, "-m", "comodor", channel.name, "start"]


def plan(config: Config, channel: Channel) -> Unit:
    """What would be written, and what would run it. Nothing is written here."""
    name = f"comodor-{channel.name}"
    label = f"ai.comodor.{channel.name}"
    command = _command(config, channel)
    workdir = str(Path(config.paths.project))

    if sys.platform.startswith("linux"):
        path = (Path.home() / ".config" / "systemd" / "user"
                / f"{name}.service")
        body = (
            "[Unit]\n"
            f"Description=Comodor on {channel.label}\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n"
            "\n"
            "[Service]\n"
            f"ExecStart={' '.join(command)}\n"
            f"WorkingDirectory={workdir}\n"
            "Restart=on-failure\n"
            "RestartSec=10\n"
            # These bots poll or hold a socket; a burst of restarts means the
            # network is down or the token is wrong, and hammering the API
            # helps neither.
            "StartLimitIntervalSec=300\n"
            "StartLimitBurst=5\n"
            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        return Unit(
            kind="systemd", path=path, body=body,
            enable=[["systemctl", "--user", "daemon-reload"],
                    ["systemctl", "--user", "enable", "--now",
                     f"{name}.service"]],
            disable=[["systemctl", "--user", "disable", "--now",
                      f"{name}.service"]],
            supported=shutil.which("systemctl") is not None,
            why="systemd is not on this machine",
        )

    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        args = "\n".join(f"    <string>{part}</string>" for part in command)
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            "<dict>\n"
            f"  <key>Label</key><string>{label}</string>\n"
            "  <key>ProgramArguments</key>\n  <array>\n"
            f"{args}\n"
            "  </array>\n"
            f"  <key>WorkingDirectory</key><string>{workdir}</string>\n"
            "  <key>RunAtLoad</key><true/>\n"
            "  <key>KeepAlive</key>\n"
            "  <dict><key>SuccessfulExit</key><false/></dict>\n"
            "</dict>\n</plist>\n"
        )
        target = f"gui/{os.getuid()}/{label}"
        return Unit(
            kind="launchd", path=path, body=body,
            enable=[["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)]],
            disable=[["launchctl", "bootout", target]],
        )

    if os.name == "nt":
        # `schtasks` takes the command on the command line rather than from a
        # file, so the "unit" written here is the XML the task is built from —
        # kept so `comodor <channel> service` can show what it asked for.
        path = Path(config.paths.user) / f"{name}.cmd"
        quoted = " ".join(f'"{part}"' if " " in part else part
                          for part in command)
        body = f'@echo off\r\ncd /d "{workdir}"\r\n{quoted}\r\n'
        return Unit(
            kind="schtasks", path=path, body=body,
            enable=[["schtasks", "/Create", "/F", "/SC", "ONLOGON",
                     "/TN", name, "/TR", f'"{path}"']],
            disable=[["schtasks", "/Delete", "/F", "/TN", name]],
        )

    return Unit(kind="none", path=Path(), body="", enable=[], disable=[],
                supported=False, why=f"no service manager known for {sys.platform}")


def install(config: Config, channel: Channel) -> tuple[bool, str, Unit]:
    """Write the unit and ask the system to run it from now on."""
    unit = plan(config, channel)
    if not unit.supported:
        return False, unit.why, unit

    try:
        unit.path.parent.mkdir(parents=True, exist_ok=True)
        unit.path.write_text(unit.body, encoding="utf-8")
        if unit.kind == "schtasks":
            os.chmod(unit.path, 0o700)
    except OSError as problem:
        return False, f"Could not write {unit.path}: {problem}", unit

    for step in unit.enable:
        done = subprocess.run(step, capture_output=True, text=True)
        if done.returncode != 0:
            detail = (done.stderr or done.stdout or "").strip().splitlines()
            return False, (f"`{' '.join(step)}` failed"
                           + (f": {detail[-1]}" if detail else "")), unit

    return True, f"Installed as a {unit.kind} service; it starts at login.", unit


def uninstall(config: Config, channel: Channel) -> tuple[bool, str]:
    """Stop the system starting it, and remove the unit."""
    unit = plan(config, channel)
    if not unit.supported:
        return False, unit.why

    trouble = ""
    for step in unit.disable:
        done = subprocess.run(step, capture_output=True, text=True)
        if done.returncode != 0:
            detail = (done.stderr or done.stdout or "").strip().splitlines()
            trouble = detail[-1] if detail else f"`{' '.join(step)}` failed"

    try:
        unit.path.unlink()
    except FileNotFoundError:
        pass
    except OSError as problem:
        return False, f"Could not remove {unit.path}: {problem}"

    if trouble and "not exist" not in trouble.lower():
        return False, trouble
    return True, "Removed. It will not start at login any more."


def installed(config: Config, channel: Channel) -> bool:
    """Whether the unit is on disk. Cheap, and does not shell out."""
    unit = plan(config, channel)
    try:
        return unit.supported and unit.path.exists()
    except OSError:
        return False
