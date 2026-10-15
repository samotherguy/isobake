"""Per-device hostnames, passwords, SHA-512-crypt hashes and SSH keys."""

from __future__ import annotations

import secrets
import shutil
import string
import subprocess
from pathlib import Path

from isobake.errors import BuildError, ConfigError, MissingTool

ALPHABET = string.ascii_letters + string.digits  # easy to type at a console


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_password(password: str) -> str:
    """SHA-512 crypt via openssl. Python's ``crypt`` module was removed in 3.13."""
    if not shutil.which("openssl"):
        raise MissingTool("openssl", "openssl")
    out = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=password + "\n",
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise BuildError(f"openssl passwd failed: {out.stderr.strip()}")
    digest = out.stdout.strip()
    if not digest.startswith("$6$"):
        raise BuildError(f"unexpected hash format from openssl: {digest[:4]}...")
    return digest


def hostname_sequence(prefix: str, count: int, start: int = 1) -> list[str]:
    if not prefix or not prefix.replace("-", "").isalnum():
        raise ConfigError(f"devices.prefix must be alphanumeric with dashes, got {prefix!r}")
    width = max(2, len(str(start + count - 1)))
    return [f"{prefix}-{i:0{width}d}" for i in range(start, start + count)]


def read_ssh_keys(paths: list[str | Path]) -> list[str]:
    keys: list[str] = []
    for p in paths:
        path = Path(p).expanduser()
        if not path.is_file():
            raise ConfigError(f"ssh key not found: {path}")
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                keys.append(line)
    return keys
