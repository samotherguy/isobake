"""Patch grub and repack the ISO with xorriso, preserving the original boot equipment."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from isobake.errors import BuildError, MissingTool

GRUB_CFG = "/boot/grub/grub.cfg"
LOOPBACK_CFG = "/boot/grub/loopback.cfg"  # read by grub loopback / Ventoy
BOOT_CFGS = [GRUB_CFG, LOOPBACK_CFG]
NOCLOUD = "/nocloud"
AUTOINSTALL_ARG = r"autoinstall ds=nocloud\;s=/cdrom/nocloud/"
LINUX_LINE = re.compile(r"^(\s*linux(?:16|efi)?\s+\S*vmlinuz\S*)(.*)$", re.MULTILINE)


def require_xorriso() -> str:
    exe = shutil.which("xorriso")
    if not exe:
        raise MissingTool("xorriso", "xorriso")
    return exe


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        tail = "\n".join(out.stderr.strip().splitlines()[-15:])
        raise BuildError(f"{' '.join(args[:2])} failed (exit {out.returncode}):\n{tail}")
    return out


def extract_text(iso: Path, iso_path: str) -> str:
    """Read one text file out of an ISO without mounting it."""
    require_xorriso()
    with tempfile.TemporaryDirectory(prefix="isobake-") as tmp:
        dest = Path(tmp) / "f"
        _run(["xorriso", "-indev", str(iso), "-osirrox", "on", "-extract", iso_path, str(dest)])
        return dest.read_text()


def exists(iso: Path, iso_path: str) -> bool:
    return iso_path in list_dir(iso, iso_path)


def patched_boot_cfgs(iso: Path, extra_args: list[str] | None = None) -> dict[str, str]:
    """Every grub config present in the ISO, patched. grub.cfg is required, loopback.cfg optional."""
    out: dict[str, str] = {}
    for cfg in BOOT_CFGS:
        if cfg == GRUB_CFG or exists(iso, cfg):
            out[cfg] = patch_grub(extract_text(iso, cfg), extra_args)
    return out


def list_dir(iso: Path, iso_path: str) -> list[str]:
    require_xorriso()
    out = subprocess.run(
        ["xorriso", "-indev", str(iso), "-find", iso_path], capture_output=True, text=True
    )
    if out.returncode != 0:
        return []
    return [line.strip().strip("'") for line in out.stdout.splitlines() if line.startswith("'")]


def patch_grub(text: str, extra_args: list[str] | None = None, timeout: int = 1) -> str:
    """Add the autoinstall kernel argument to every linux line. Idempotent."""
    args = " ".join([AUTOINSTALL_ARG, *(extra_args or [])])

    def repl(m: re.Match[str]) -> str:
        head, rest = m.group(1), m.group(2)
        if "autoinstall" in rest:
            return m.group(0)
        if " ---" in rest:
            before, after = rest.split(" ---", 1)
            return f"{head}{before.rstrip()} {args} ---{after}"
        return f"{head}{rest} {args}"

    patched, n = LINUX_LINE.subn(repl, text)
    if n == 0:
        raise BuildError("no `linux ... vmlinuz` lines found in grub.cfg; is this an Ubuntu ISO?")
    patched = re.sub(r"^set timeout=\d+", f"set timeout={timeout}", patched, flags=re.MULTILINE)
    return patched


def repack(source: Path, output: Path, user_data: str, boot_cfgs: dict[str, str], meta_data: str = "") -> Path:
    """Write ``output`` = ``source`` + patched boot configs + /nocloud files, boot equipment replayed."""
    require_xorriso()
    if not source.is_file():
        raise BuildError(f"source ISO not found: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="isobake-") as tmp:
        t = Path(tmp)
        (t / "user-data").write_text(user_data)
        (t / "meta-data").write_text(meta_data)
        maps = ["-map", str(t / "user-data"), f"{NOCLOUD}/user-data",
                "-map", str(t / "meta-data"), f"{NOCLOUD}/meta-data"]
        for i, (iso_path, text) in enumerate(boot_cfgs.items()):
            local = t / f"cfg{i}"
            local.write_text(text)
            maps += ["-map", str(local), iso_path]
        partial = output.with_suffix(output.suffix + ".part")
        try:
            _run(["xorriso", "-indev", str(source), "-outdev", str(partial),
                  "-boot_image", "any", "replay", *maps])
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)
    return output


def inspect(iso: Path) -> dict[str, str | list[str]]:
    grub = extract_text(iso, GRUB_CFG)
    files = list_dir(iso, NOCLOUD)
    user_data = extract_text(iso, f"{NOCLOUD}/user-data") if f"{NOCLOUD}/user-data" in files else ""
    kernel_lines = [ln.strip() for ln in grub.splitlines() if LINUX_LINE.match(ln)]
    return {"kernel_lines": kernel_lines, "nocloud": files, "user_data": user_data}
