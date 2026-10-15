"""Boot a built ISO headless under QEMU.

QEMU runs without ``-no-reboot``: a guest reboot (shim's fallback creating a boot entry, a kernel
update) restarts the VM in place, and QEMU only exits when the guest powers off. Phases, each
passing when the VM powers itself off:
  1. install     boot the ISO, the installer runs and powers off
  2. first boot  boot the installed disk, cloud-init runs every runcmd and powers off
  3. reboot      boot the disk again, it must come up unattended (TPM or USB unlock) and power off
All three rely on the ``poweroff-after-install`` preset. ``--inject-poweroff`` adds it to an
existing ISO on the fly so production media can be verified unchanged.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

from isobake.errors import MissingTool, VerifyError

OVMF_CANDIDATES = [
    "/usr/share/OVMF/OVMF_CODE_4M.fd",
    "/usr/share/OVMF/OVMF_CODE.fd",
    "/usr/share/edk2/ovmf/OVMF_CODE.fd",
    "/usr/share/edk2-ovmf/x64/OVMF_CODE.fd",
    "/usr/share/qemu/OVMF.fd",
]
MIN_PLAUSIBLE_SECONDS = 5  # a failed boot exits in about a second; a real one takes longer even on fast hardware
USB_KEY_LABEL = "linux-key"


def find_ovmf() -> Path | None:
    return next((Path(p) for p in OVMF_CANDIDATES if Path(p).is_file()), None)


def ovmf_vars_template(code: Path) -> Path | None:
    """The writable NVRAM image that pairs with an OVMF_CODE file, if the distro ships one."""
    cand = code.with_name(code.name.replace("CODE", "VARS"))
    return cand if cand != code and cand.is_file() else None


def kvm_available() -> bool:
    return os.access("/dev/kvm", os.R_OK | os.W_OK)


def qemu_command(
    disk: Path, log: Path, memory_mb: int, cpus: int, firmware: str, ovmf: Path | None,
    iso: Path | None = None, tpm_sock: Path | None = None, usb_key: Path | None = None,
    nvram: Path | None = None,
) -> list[str]:
    cmd = [
        "qemu-system-x86_64",
        "-m", str(memory_mb),
        "-smp", str(cpus),
        "-display", "none",
        "-monitor", "none",
        "-serial", f"file:{log}",
        "-drive", f"file={disk},format=qcow2,if=virtio",
        "-netdev", "user,id=n0",
        "-device", "virtio-net-pci,netdev=n0",
    ]
    if iso is not None:
        cmd += ["-drive", f"file={iso},media=cdrom,readonly=on", "-boot", "d"]
    else:
        cmd += ["-boot", "c"]
    if usb_key is not None:
        cmd += ["-drive", f"file={usb_key},format=raw,if=none,id=usbkey",
                "-device", "usb-storage,drive=usbkey", "-usb"]
    if tpm_sock is not None:
        cmd += ["-chardev", f"socket,id=chrtpm,path={tpm_sock}",
                "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
                "-device", "tpm-tis,tpmdev=tpm0"]
    if kvm_available():
        cmd += ["-enable-kvm", "-cpu", "host"]
    if firmware == "uefi":
        if ovmf is None:
            raise MissingTool("OVMF firmware", "ovmf")
        cmd += ["-drive", f"if=pflash,format=raw,readonly=on,file={ovmf}"]
        if nvram is not None:
            cmd += ["-drive", f"if=pflash,format=raw,file={nvram}"]
    return cmd


def make_usb_key_image(path: Path, size_mb: int = 16) -> Path:
    """An ext4 image labelled linux-key, what the usb-keyfile preset looks for."""
    if not shutil.which("mkfs.ext4"):
        raise MissingTool("mkfs.ext4", "e2fsprogs")
    with path.open("wb") as f:
        f.truncate(size_mb * 1024 * 1024)
    subprocess.run(["mkfs.ext4", "-q", "-L", USB_KEY_LABEL, str(path)], check=True, capture_output=True)
    return path


class _SoftwareTpm:
    """swtpm for a verify run. swtpm exits when QEMU disconnects, so it is restarted for every
    phase against the same state directory; the sealed key persists like it would in a real chip."""

    def __init__(self, workdir: Path):
        if not shutil.which("swtpm"):
            raise MissingTool("swtpm", "swtpm")
        self.state = workdir / "tpm"
        self.state.mkdir(exist_ok=True)
        self.sock = workdir / "swtpm.sock"
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> _SoftwareTpm:
        return self

    def socket(self) -> Path:
        """Start (or restart) swtpm and return its control socket."""
        if self.proc is not None and self.proc.poll() is None and self.sock.exists():
            return self.sock
        self.sock.unlink(missing_ok=True)
        self.proc = subprocess.Popen(
            ["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={self.state}",
             "--ctrl", f"type=unixio,path={self.sock}", "--log", "level=1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            if self.sock.exists():
                return self.sock
            time.sleep(0.1)
        raise VerifyError("swtpm did not create its control socket")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def inject_poweroff(iso: Path, dest: Path) -> Path:
    """Repack ``iso`` with the poweroff-after-install preset merged into its user-data."""
    from isobake import iso as isomod
    from isobake.presets import deep_merge, discover

    info = isomod.inspect(iso)
    if not info["user_data"]:
        raise VerifyError(f"{iso} has no /nocloud/user-data; is it an isobake ISO?")
    doc = yaml.safe_load(str(info["user_data"]))
    doc = deep_merge(doc, discover()["poweroff-after-install"].fragment)
    user_data = "#cloud-config\n" + yaml.safe_dump(doc, sort_keys=False, width=1000)
    cfgs = {p: isomod.extract_text(iso, p) for p in isomod.BOOT_CFGS if isomod.exists(iso, p)}
    return isomod.repack(iso, dest, user_data, cfgs)


def _phase(name: str, cmd: list[str], timeout: int, serial_log: Path, log) -> int:
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired as e:
        raise VerifyError(
            f"{name}: timed out after {timeout}s, the VM did not power off "
            f"(stuck installer, passphrase prompt, or reboot loop).\n{_tail(serial_log)}"
        ) from e
    elapsed = int(time.monotonic() - start)
    if proc.returncode != 0:
        raise VerifyError(
            f"{name}: qemu exited {proc.returncode} after {elapsed}s:\n"
            f"{proc.stderr.strip()}\n{_tail(serial_log)}"
        )
    if elapsed < MIN_PLAUSIBLE_SECONDS:
        raise VerifyError(
            f"{name}: qemu exited after only {elapsed}s; the VM probably did not boot.\n{_tail(serial_log)}"
        )
    log(f"{name}: ok, powered off after {elapsed}s")
    return elapsed


def run(
    iso: Path,
    timeout: int = 1800,
    memory_mb: int = 4096,
    cpus: int = 2,
    disk_gb: int = 20,
    firmware: str = "auto",
    keep_disk: bool = False,
    phases: int = 3,
    tpm: bool = False,
    usb_key: bool = False,
    inject: bool = False,
    disk: Path | None = None,
    log=print,
) -> Path:
    """Return the serial log path on success; raise VerifyError on timeout or bad exit."""
    for tool, pkg in (("qemu-system-x86_64", "qemu-system-x86"), ("qemu-img", "qemu-utils")):
        if not shutil.which(tool):
            raise MissingTool(tool, pkg)
    if not iso.is_file():
        raise VerifyError(f"ISO not found: {iso}")
    ovmf = find_ovmf()
    if firmware == "auto":
        firmware = "uefi" if ovmf else "bios"
    serial_log = iso.with_suffix(".verify.log")
    serial_log.unlink(missing_ok=True)
    resume = disk is not None
    if resume:
        if not disk.is_file():
            raise VerifyError(f"disk not found: {disk}")
        workdir = disk.parent
    else:
        workdir = Path(tempfile.mkdtemp(prefix="isobake-verify-"))
        disk = workdir / "disk.qcow2"
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", str(disk), f"{disk_gb}G"], check=True)
    nvram = None
    if firmware == "uefi" and ovmf is not None and (tpl := ovmf_vars_template(ovmf)):
        nvram = workdir / "nvram.fd"  # persistent across phases, like a real machine's NVRAM
        if not nvram.exists():
            shutil.copy(tpl, nvram)
    key_img = workdir / "usb-key.img" if usb_key else None
    if key_img is not None and not key_img.exists():
        make_usb_key_image(key_img)
    if inject:
        log("injecting poweroff-after-install into a temporary copy")
        iso = inject_poweroff(iso, workdir / iso.name)
    extras = [x for x, on in (("tpm", tpm), ("usb-key", usb_key), ("injected", inject)) if on]
    log(f"verify {iso.name}: {firmware}, {'kvm' if kvm_available() else 'tcg, slow'}, "
        f"{phases} phase(s), timeout {timeout}s per phase"
        + (f", {', '.join(extras)}" if extras else "") + f", serial log {serial_log}")
    names = ["install", "first boot", "reboot"][:phases]
    if resume:
        names = names[1:]  # the disk already holds an installed system
        log(f"resuming from {disk}, skipping the install phase")
    try:
        with _SoftwareTpm(workdir) if tpm else _NoTpm() as chip:
            for name in names:
                cmd = qemu_command(disk, serial_log, memory_mb, cpus, firmware, ovmf,
                                   iso=iso if name == "install" else None, tpm_sock=chip.socket(),
                                   usb_key=key_img, nvram=nvram)
                _phase(name, cmd, timeout, serial_log, log)
    finally:
        if keep_disk or resume:
            log(f"disk kept at {disk}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    log("pass")
    return serial_log


class _NoTpm:
    def __enter__(self) -> _NoTpm:
        return self

    def socket(self) -> None:
        return None

    def __exit__(self, *exc) -> None:
        pass


def _tail(log: Path, n: int = 40) -> str:
    if not log.is_file():
        return "(no serial output; add `console=ttyS0` to kernel_args to capture installer logs)"
    lines = log.read_text(errors="replace").splitlines()
    return "--- last serial lines ---\n" + "\n".join(lines[-n:]) if lines else "(serial log empty)"
