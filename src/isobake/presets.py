"""Preset discovery, deep merge and ``${var}`` substitution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from isobake.errors import ConfigError

PLACEHOLDER = re.compile(r"\$\{([a-z][a-z0-9_]*)\}")


@dataclass(frozen=True)
class Preset:
    name: str
    path: Path
    fragment: dict[str, Any]
    description: str = ""


def bundled_dir() -> Path:
    return Path(str(resources.files("isobake").joinpath("presets")))


def discover(extra_dirs: list[Path] | None = None) -> dict[str, Preset]:
    """Return presets by name. Later directories override earlier ones."""
    found: dict[str, Preset] = {}
    for base in [bundled_dir(), *(extra_dirs or [])]:
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            f = d / "preset.yaml"
            if not f.is_file():
                continue
            data = yaml.safe_load(f.read_text()) or {}
            if not isinstance(data, dict):
                raise ConfigError(f"preset {f}: top level must be a mapping")
            found[d.name] = Preset(d.name, d, data, _first_line(d / "README.md"))
    return found


def _first_line(readme: Path) -> str:
    if not readme.is_file():
        return ""
    for line in readme.read_text().splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return ""


def deep_merge(base: Any, override: Any) -> Any:
    """Mappings merge recursively, lists append without duplicates, scalars: override wins."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = deep_merge(base[k], v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(override, list):
        out = list(base)
        for item in override:
            if item not in out:
                out.append(item)
        return out
    return override


def merge_presets(names: list[str], available: dict[str, Preset]) -> dict[str, Any]:
    unknown = [n for n in names if n not in available]
    if unknown:
        raise ConfigError(
            f"unknown preset(s): {', '.join(unknown)}. Known: {', '.join(sorted(available))}"
        )
    merged: dict[str, Any] = {}
    for n in names:
        merged = deep_merge(merged, available[n].fragment)
    return merged


def substitute(obj: Any, variables: dict[str, Any]) -> Any:
    """Replace ``${name}`` in every string. Raise ConfigError listing missing names."""
    missing: set[str] = set()

    def sub_str(s: str) -> str:
        def repl(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in variables:
                missing.add(name)
                return m.group(0)
            return str(variables[name])

        return PLACEHOLDER.sub(repl, s)

    def walk(o: Any) -> Any:
        if isinstance(o, str):
            return sub_str(o)
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    result = walk(obj)
    if missing:
        raise ConfigError(
            "missing variable(s): " + ", ".join(sorted(missing)) + ". Set them under `vars:`."
        )
    return result
