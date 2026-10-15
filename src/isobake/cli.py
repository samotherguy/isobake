"""isobake command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from isobake import __version__, config, credentials, iso, presets, render, source, verify
from isobake.errors import IsobakeError

VERIFY_PRESET = "poweroff-after-install"
TPM_PRESET = "tpm-unlock"
USB_PRESET = "usb-keyfile"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args) or 0
    except IsobakeError as e:
        log(f"error: {e}")
        return e.exit_code
    except KeyboardInterrupt:
        log("interrupted")
        return 130


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="isobake",
        description="Bake unattended Ubuntu install ISOs: presets, per-device credentials, "
        "fleet builds and a QEMU boot test.",
    )
    p.add_argument("--version", action="version", version=f"isobake {__version__}")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("init", help="write a starter isobake.yaml")
    s.add_argument("-c", "--config", type=Path, default=Path("isobake.yaml"))
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("fetch", help="download and verify a source ISO into the cache")
    s.add_argument("--release", default=config.DEFAULT_RELEASE)
    s.add_argument("--no-gpg", action="store_true", help="skip GPG signature verification")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("build", help="build one ISO per device")
    s.add_argument("-c", "--config", type=Path, default=Path("isobake.yaml"))
    s.add_argument("--source", type=Path, help="use this ISO instead of downloading")
    s.add_argument("--preset", action="append", help="preset name(s), comma separated; overrides config")
    s.add_argument("--preset-dir", action="append", type=Path, help="extra directory of presets")
    s.add_argument("--count", type=int, help="number of devices; overrides config")
    s.add_argument("--var", action="append", default=[], metavar="NAME=VALUE")
    s.add_argument("--out", type=Path, help="output directory")
    s.add_argument("--credentials-file", type=Path, help="also write credentials here (mode 0600)")
    s.add_argument("--no-gpg", action="store_true")
    s.add_argument("--verify", action="store_true",
                   help=f"add the {VERIFY_PRESET} preset and boot-test each ISO under QEMU")
    s.add_argument("--timeout", type=int, default=1800, help="verify timeout per phase in seconds")
    s.add_argument("--keep-disk", action="store_true", help="verify: keep each VM disk and TPM state")
    _phase_flags(s)
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("verify", help="boot an ISO headless under QEMU; pass on clean poweroff")
    s.add_argument("iso", type=Path)
    s.add_argument("--timeout", type=int, default=1800, help="seconds per phase")
    s.add_argument("--memory", type=int, default=4096, help="MiB")
    s.add_argument("--cpus", type=int, default=2)
    s.add_argument("--disk", type=int, default=20, help="GiB")
    s.add_argument("--firmware", choices=["auto", "uefi", "bios"], default="auto")
    s.add_argument("--keep-disk", action="store_true", help="keep the VM disk and TPM state afterwards")
    s.add_argument("--resume", type=Path, metavar="DISK", help="resume on a kept disk: skips the install phase")
    s.add_argument("--inject-poweroff", action="store_true",
                   help="verify a production ISO by adding the poweroff preset to a temporary copy")
    s.add_argument("--tpm", action="store_true", help="attach an emulated TPM 2.0 (needs swtpm)")
    s.add_argument("--usb-key", action="store_true", help="attach a USB stick labelled linux-key")
    _phase_flags(s)
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("doctor", help="check that every tool isobake needs is installed")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("inspect", help="show the autoinstall config and kernel args inside an ISO")
    s.add_argument("iso", type=Path)
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("presets", help="list available presets")
    s.add_argument("--preset-dir", action="append", type=Path)
    s.set_defaults(func=cmd_presets)
    return p


def _phase_flags(s: argparse.ArgumentParser) -> None:
    g = s.add_mutually_exclusive_group()
    g.add_argument("--installer-only", action="store_true", help="verify: only the install phase")
    g.add_argument("--no-reboot", action="store_true", help="verify: skip the third (reboot) phase")


def _phases(args: argparse.Namespace) -> int:
    return 1 if args.installer_only else 2 if args.no_reboot else 3


def cmd_doctor(args: argparse.Namespace) -> int:
    import shutil

    rows = [
        ("xorriso", shutil.which("xorriso"), "xorriso", "build"),
        ("gpg", shutil.which("gpg"), "gnupg", "build (signature check)"),
        ("openssl", shutil.which("openssl"), "openssl", "build (password hash)"),
        ("curl", shutil.which("curl"), "curl", "fetch"),
        ("qemu-system-x86_64", shutil.which("qemu-system-x86_64"), "qemu-system-x86", "verify"),
        ("qemu-img", shutil.which("qemu-img"), "qemu-utils", "verify"),
        ("OVMF", verify.find_ovmf(), "ovmf", "verify (UEFI)"),
        ("swtpm", shutil.which("swtpm"), "swtpm", "verify --tpm"),
        ("mkfs.ext4", shutil.which("mkfs.ext4"), "e2fsprogs", "verify --usb-key"),
        ("/dev/kvm", "/dev/kvm" if verify.kvm_available() else None, "add yourself to the kvm group", "fast verify"),
    ]
    missing = 0
    for name, found, pkg, used in rows:
        ok = found is not None
        missing += not ok
        fix = "" if ok else (pkg if " " in pkg else f"sudo apt install {pkg}")
        print(f"{'ok ' if ok else 'MISSING'}  {name:<20} {used:<24} {fix}".rstrip())
    print(f"\n{len(rows) - missing}/{len(rows)} available")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    config.write_starter(args.config)
    log(f"wrote {args.config}. Edit it, then run `isobake build`.")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    path = source.fetch(args.release, gpg=not args.no_gpg, log=log)
    print(path)
    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    found = presets.discover(args.preset_dir or [])
    width = max(len(n) for n in found) if found else 0
    for name, p in found.items():
        print(f"{name:<{width}}  {p.description}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    info = iso.inspect(args.iso)
    print("kernel lines:")
    for line in info["kernel_lines"]:
        print(f"  {line}")
    print(f"nocloud files: {', '.join(info['nocloud']) or '(none: not an isobake ISO)'}")
    if info["user_data"]:
        print("user-data:")
        print("  " + str(info["user_data"]).replace("\n", "\n  "))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    cli: dict = {
        "source": args.source,
        "presets": ",".join(args.preset) if args.preset else None,
        "preset_dirs": args.preset_dir,
        "count": args.count,
        "output": args.out,
        "vars": dict(_split_var(v) for v in args.var),
    }
    cfg = config.load(args.config, cli)
    extra = [VERIFY_PRESET] if args.verify else []
    # Fail on config mistakes and missing tools before any 3 GB download.
    presets.merge_presets([*cfg.presets, *extra], presets.discover(cfg.preset_dirs))
    keys = credentials.read_ssh_keys(cfg.ssh_keys)
    iso.require_xorriso()
    credentials.hash_password("probe")
    src = source.resolve(cfg.source_path, cfg.source_release, gpg=not args.no_gpg, log=log)
    boot_cfgs = iso.patched_boot_cfgs(src, cfg.kernel_args)

    rows: list[tuple[str, ...]] = []
    for dev in cfg.devices:
        password = credentials.generate_password()
        passphrase = credentials.generate_password(24)
        user_data = render.render_device(cfg, dev, credentials.hash_password(password), keys, extra,
                                         luks_passphrase=passphrase)
        out = cfg.output / f"{dev.hostname}.iso"
        log(f"building {out}")
        iso.repack(src, out, user_data, boot_cfgs)
        rows.append((dev.hostname, dev.username, password, passphrase if passphrase in user_data else ""))

    _print_credentials(rows, args.credentials_file)
    if args.verify:
        selected = set(cfg.presets)
        for dev in cfg.devices:
            verify.run(cfg.output / f"{dev.hostname}.iso", timeout=args.timeout, phases=_phases(args),
                       tpm=TPM_PRESET in selected, usb_key=USB_PRESET in selected,
                       keep_disk=args.keep_disk, log=log)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    verify.run(
        args.iso, timeout=args.timeout, memory_mb=args.memory, cpus=args.cpus,
        disk_gb=args.disk, firmware=args.firmware, keep_disk=args.keep_disk, phases=_phases(args),
        tpm=args.tpm, usb_key=args.usb_key, inject=args.inject_poweroff, disk=args.resume, log=log,
    )
    return 0


def _split_var(s: str) -> tuple[str, str]:
    if "=" not in s:
        raise SystemExit(f"--var expects NAME=VALUE, got {s!r}")
    k, v = s.split("=", 1)
    return k.strip(), v


def _print_credentials(rows: list[tuple[str, ...]], path: Path | None) -> None:
    width = max(len(r[0]) for r in rows)
    encrypted = any(r[3] for r in rows)
    header = f"{'hostname':<{width}}  username  {'password':<20}" + ("  disk passphrase" if encrypted else "")
    lines = [header.rstrip()]
    for h, u, p, lp in rows:
        lines.append((f"{h:<{width}}  {u:<8}  {p:<20}" + (f"  {lp}" if encrypted else "")).rstrip())
    text = "\n".join(lines)
    print(text)
    print("\nCredentials are shown once and are not stored. Copy them now.", file=sys.stderr)
    if path:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text + "\n")
        log(f"credentials written to {path} (mode 0600)")
