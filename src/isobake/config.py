"""Load and validate ``isobake.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from isobake.errors import ConfigError

DEFAULT_RELEASE = "24.04"


@dataclass
class Device:
    hostname: str
    username: str


@dataclass
class Config:
    source_release: str | None = DEFAULT_RELEASE
    source_path: Path | None = None
    presets: list[str] = field(default_factory=lambda: ["base"])
    preset_dirs: list[Path] = field(default_factory=list)
    devices: list[Device] = field(default_factory=list)
    username: str = "ubuntu"
    ssh_keys: list[Path] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    kernel_args: list[str] = field(default_factory=list)
    output: Path = Path("out")


STARTER = """\
# isobake project file. Run `isobake build` in this directory.
source:
  release: "24.04"          # or  path: /path/to/ubuntu-live-server.iso
presets: [base]             # see `isobake presets`
devices:
  prefix: node
  count: 1
identity:
  username: ubuntu
  ssh_keys: []              # e.g. [~/.ssh/id_ed25519.pub]
vars: {}                    # values for ${name} placeholders in presets
overrides: {}               # raw autoinstall keys merged last
kernel_args: []             # e.g. [console=ttyS0,115200n8]
output: ./out
"""


def load(path: Path, cli: dict[str, Any] | None = None) -> Config:
    if not path.is_file():
        raise ConfigError(f"config not found: {path}. Run `isobake init` to create one.")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return from_dict(raw, base_dir=path.parent, cli=cli or {})


def from_dict(raw: dict[str, Any], base_dir: Path = Path("."), cli: dict[str, Any] | None = None) -> Config:
    cli = cli or {}
    errors: list[str] = []
    cfg = Config()

    src = raw.get("source") or {}
    if not isinstance(src, dict):
        errors.append("source: must be a mapping with `release` or `path`")
        src = {}
    if "path" in src:
        cfg.source_path = _resolve(base_dir, src["path"])
        cfg.source_release = None
    else:
        cfg.source_release = str(src.get("release", DEFAULT_RELEASE))
    if cli.get("source"):
        cfg.source_path = Path(cli["source"]).expanduser()
        cfg.source_release = None

    presets = cli.get("presets") or raw.get("presets", ["base"])
    if isinstance(presets, str):
        presets = [p.strip() for p in presets.split(",") if p.strip()]
    if not isinstance(presets, list) or not all(isinstance(p, str) for p in presets):
        errors.append("presets: must be a list of names")
    else:
        cfg.presets = presets
    for extra in [*(raw.get("preset_dirs") or []), *(cli.get("preset_dirs") or [])]:
        cfg.preset_dirs.append(_resolve(base_dir, extra))

    ident = raw.get("identity") or {}
    if not isinstance(ident, dict):
        errors.append("identity: must be a mapping")
        ident = {}
    cfg.username = str(ident.get("username", cfg.username))
    if not _valid_username(cfg.username):
        errors.append(f"identity.username: {cfg.username!r} is not a valid Linux username")
    cfg.ssh_keys = [_resolve(base_dir, k) for k in ident.get("ssh_keys") or []]

    cfg.devices, dev_errors = _devices(raw.get("devices") or {}, cfg.username, cli)
    errors += dev_errors

    for key, attr in (("vars", "variables"), ("overrides", "overrides")):
        val = raw.get(key) or {}
        if not isinstance(val, dict):
            errors.append(f"{key}: must be a mapping")
        else:
            setattr(cfg, attr, val)
    for k, v in (cli.get("vars") or {}).items():
        cfg.variables[k] = v

    kargs = raw.get("kernel_args") or []
    if not isinstance(kargs, list):
        errors.append("kernel_args: must be a list of strings")
    else:
        cfg.kernel_args = [str(a) for a in kargs]

    cfg.output = _resolve(base_dir, cli.get("output") or raw.get("output") or "out")

    if errors:
        raise ConfigError("invalid config:\n  - " + "\n  - ".join(errors))
    return cfg


def _devices(raw: Any, default_user: str, cli: dict[str, Any]) -> tuple[list[Device], list[str]]:
    from isobake.credentials import hostname_sequence

    errors: list[str] = []
    if not isinstance(raw, dict):
        return [], ["devices: must be a mapping"]
    devices: list[Device] = []
    if "list" in raw:
        for i, item in enumerate(raw["list"] or []):
            if isinstance(item, str):
                item = {"hostname": item}
            if not isinstance(item, dict) or not item.get("hostname"):
                errors.append(f"devices.list[{i}]: needs a hostname")
                continue
            host = str(item["hostname"])
            if not _valid_hostname(host):
                errors.append(f"devices.list[{i}]: {host!r} is not a valid hostname")
            devices.append(Device(host, str(item.get("username", default_user))))
    else:
        count = cli.get("count") or raw.get("count", 1)
        prefix = str(raw.get("prefix", "node"))
        try:
            count = int(count)
            if count < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"devices.count: must be a positive integer, got {count!r}")
            count = 1
        try:
            devices = [Device(h, default_user) for h in hostname_sequence(prefix, count)]
        except ConfigError as e:
            errors.append(str(e))
    if not devices and not errors:
        errors.append("devices: at least one device is required")
    seen: set[str] = set()
    for d in devices:
        if d.hostname in seen:
            errors.append(f"duplicate hostname: {d.hostname}")
        seen.add(d.hostname)
    return devices, errors


def _resolve(base: Path, p: str | Path) -> Path:
    path = Path(p).expanduser()
    return path if path.is_absolute() else (base / path)


def _valid_username(u: str) -> bool:
    return bool(u) and u[0].isalpha() and all(c.isalnum() or c in "-_" for c in u) and len(u) <= 32


def _valid_hostname(h: str) -> bool:
    return bool(h) and len(h) <= 63 and all(c.isalnum() or c == "-" for c in h) and h[0] != "-"


def write_starter(path: Path) -> None:
    if path.exists():
        raise ConfigError(f"{path} already exists")
    path.write_text(STARTER)
