"""Assemble the per-device autoinstall document."""

from __future__ import annotations

from typing import Any

import yaml

from isobake.config import Config, Device
from isobake.errors import ConfigError
from isobake.presets import deep_merge, discover, merge_presets, substitute


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # no &id001 anchors in output
        return True


def render_device(
    cfg: Config,
    device: Device,
    password_hash: str,
    ssh_keys: list[str],
    extra_presets: list[str] | None = None,
    luks_passphrase: str = "",
) -> str:
    available = discover(cfg.preset_dirs)
    doc = merge_presets([*cfg.presets, *(extra_presets or [])], available)
    doc.setdefault("autoinstall", {})
    if not isinstance(doc["autoinstall"], dict):
        raise ConfigError("presets must produce a mapping under `autoinstall`")

    identity = {
        "hostname": device.hostname,
        "username": device.username,
        "password": password_hash,
    }
    if "realname" in doc["autoinstall"].get("identity", {}):
        identity["realname"] = doc["autoinstall"]["identity"]["realname"]
    doc["autoinstall"]["identity"] = identity
    if ssh_keys:
        doc["autoinstall"].setdefault("ssh", {})
        doc["autoinstall"]["ssh"]["authorized-keys"] = deep_merge(
            doc["autoinstall"]["ssh"].get("authorized-keys", []), ssh_keys
        )
    doc = deep_merge(doc, cfg.overrides)

    variables = {
        **cfg.variables,
        "hostname": device.hostname,
        "username": device.username,
        "password_hash": password_hash,
        "luks_passphrase": luks_passphrase,
    }
    doc = substitute(doc, variables)
    doc["autoinstall"].setdefault("version", 1)
    _guard_plaintext_passwords(doc)
    return "#cloud-config\n" + yaml.dump(doc, Dumper=_Dumper, sort_keys=False, width=1000)


# The installer needs the LUKS passphrase in clear to format the disk; isobake generates it per device.
PLAINTEXT_ALLOWED = {"autoinstall.storage.layout.password"}


def _guard_plaintext_passwords(obj: Any, path: str = "") -> None:
    """Refuse to bake a literal password. Only $6$ (SHA-512 crypt) hashes are allowed."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if here in PLAINTEXT_ALLOWED:
                continue
            if k in ("password", "passwd", "hashed_passwd", "plain_text_passwd") and isinstance(v, str):
                if not v.startswith("$6$"):
                    raise ConfigError(
                        f"{here}: plaintext password found. isobake only bakes SHA-512 "
                        "hashes; remove the literal value or hash it with `openssl passwd -6`."
                    )
            else:
                _guard_plaintext_passwords(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _guard_plaintext_passwords(v, f"{path}[{i}]")
