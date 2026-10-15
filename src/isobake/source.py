"""Find, download and verify the source Ubuntu ISO."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from isobake.errors import BuildError, ConfigError, MissingTool

RELEASES_URL = "https://releases.ubuntu.com/{release}/"
UBUNTU_SIGNING_KEY = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
KEYSERVER = "hkps://keyserver.ubuntu.com"
ISO_PATTERN = re.compile(r"^([0-9a-f]{64}) \*?(ubuntu-([\d.]+)-live-server-amd64\.iso)$", re.MULTILINE)


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "isobake" / "isos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (https only)
            return r.read()
    except OSError as e:
        raise BuildError(f"download failed: {url}: {e}") from e


def latest_server_iso(sums: str) -> tuple[str, str]:
    """Return (filename, sha256) of the newest live-server amd64 ISO in a SHA256SUMS file."""
    found = ISO_PATTERN.findall(sums)
    if not found:
        raise BuildError("no live-server amd64 ISO listed in SHA256SUMS")
    digest, name, _ = max(found, key=lambda t: tuple(int(x) for x in t[2].split(".")))
    return name, digest


def verify_signature(sums: Path, sig: Path, keyring: Path) -> None:
    if not shutil.which("gpg"):
        raise MissingTool("gpg", "gnupg")
    env = {**os.environ, "GNUPGHOME": str(keyring)}
    keyring.mkdir(parents=True, exist_ok=True, mode=0o700)
    have = subprocess.run(
        ["gpg", "--batch", "--list-keys", UBUNTU_SIGNING_KEY], env=env, capture_output=True
    )
    if have.returncode != 0:
        got = subprocess.run(
            ["gpg", "--batch", "--keyserver", KEYSERVER, "--recv-keys", UBUNTU_SIGNING_KEY],
            env=env, capture_output=True, text=True,
        )
        if got.returncode != 0:
            raise BuildError(
                "could not fetch the Ubuntu signing key from the keyserver:\n"
                f"{got.stderr.strip()}\nRetry, or pass --no-gpg to skip signature checks."
            )
    res = subprocess.run(
        ["gpg", "--batch", "--verify", str(sig), str(sums)], env=env, capture_output=True, text=True
    )
    if res.returncode != 0 or UBUNTU_SIGNING_KEY not in res.stderr.replace(" ", ""):
        raise BuildError(f"SHA256SUMS signature did not verify:\n{res.stderr.strip()}")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    """Resumable download with curl (present on every Ubuntu/Debian host)."""
    if not shutil.which("curl"):
        raise MissingTool("curl", "curl")
    part = dest.with_suffix(dest.suffix + ".part")
    res = subprocess.run(
        ["curl", "-fL", "--retry", "3", "-C", "-", "--progress-bar", "-o", str(part), url],
        stdout=sys.stderr,
    )
    if res.returncode != 0:
        raise BuildError(f"download failed (curl exit {res.returncode}): {url}")
    os.replace(part, dest)


def fetch(release: str, gpg: bool = True, log=print) -> Path:
    """Download (if needed) and verify the newest live-server ISO for ``release``."""
    if not re.fullmatch(r"\d\d\.\d\d", release):
        raise ConfigError(f"source.release must look like 24.04, got {release!r}")
    base = RELEASES_URL.format(release=release)
    cache = cache_dir()
    sums = cache / f"SHA256SUMS-{release}"
    sig = cache / f"SHA256SUMS-{release}.gpg"
    sums.write_bytes(_fetch(base + "SHA256SUMS"))
    sig.write_bytes(_fetch(base + "SHA256SUMS.gpg"))
    if gpg:
        verify_signature(sums, sig, cache.parent / "gnupg")
        log("signature ok: SHA256SUMS signed by the Ubuntu CD image key")
    name, digest = latest_server_iso(sums.read_text())
    iso = cache / name
    if iso.is_file() and sha256_of(iso) == digest:
        log(f"cached: {iso}")
        return iso
    log(f"downloading {base}{name}")
    _download(base + name, iso)
    actual = sha256_of(iso)
    if actual != digest:
        iso.unlink()
        raise BuildError(f"checksum mismatch for {name}: expected {digest}, got {actual}")
    log(f"checksum ok: {iso}")
    return iso


def resolve(path: Path | None, release: str | None, gpg: bool = True, log=print) -> Path:
    if path is not None:
        if not path.is_file():
            raise ConfigError(f"source ISO not found: {path}")
        return path
    return fetch(release or "24.04", gpg=gpg, log=log)
