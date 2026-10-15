import shutil
from pathlib import Path

import pytest
import yaml

from isobake import cli, iso, verify

needs_xorriso = pytest.mark.skipif(not shutil.which("xorriso"), reason="xorriso not installed")


def test_qemu_command_phases_and_devices(tmp_path: Path):
    disk, log, ovmf = tmp_path / "d.qcow2", tmp_path / "s.log", tmp_path / "OVMF.fd"
    install = verify.qemu_command(disk, log, 2048, 2, "uefi", ovmf, iso=tmp_path / "x.iso")
    assert "-boot" in install and install[install.index("-boot") + 1] == "d"
    assert any("media=cdrom" in a for a in install) and any(str(ovmf) in a for a in install)
    reboot = verify.qemu_command(disk, log, 2048, 2, "bios", None, tpm_sock=tmp_path / "t.sock",
                                 usb_key=tmp_path / "k.img")
    assert reboot[reboot.index("-boot") + 1] == "c" and not any("cdrom" in a for a in reboot)
    assert "-tpmdev" in reboot and any("usb-storage" in a for a in reboot)
    with pytest.raises(verify.MissingTool):
        verify.qemu_command(disk, log, 2048, 2, "uefi", None)


@pytest.mark.skipif(not shutil.which("mkfs.ext4"), reason="mkfs.ext4 not installed")
def test_usb_key_image_is_labelled(tmp_path: Path):
    img = verify.make_usb_key_image(tmp_path / "k.img", size_mb=8)
    assert img.stat().st_size == 8 * 1024 * 1024
    assert b"linux-key" in img.read_bytes()[:4096]


@needs_xorriso
def test_inject_poweroff_merges_into_existing_iso(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "root"
    (root / "boot" / "grub").mkdir(parents=True)
    (root / "boot" / "grub" / "grub.cfg").write_text("linux /casper/vmlinuz ---\n")
    import subprocess
    src = tmp_path / "src.iso"
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-o", str(src), str(root)], check=True)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "isobake.yaml").write_text("presets: [base, docker]\n")
    assert cli.main(["build", "--source", str(src)]) == 0
    prod = tmp_path / "out" / "node-01.iso"
    assert "poweroff" not in str(iso.inspect(prod)["user_data"])
    test_iso = verify.inject_poweroff(prod, tmp_path / "test.iso")
    doc = yaml.safe_load(str(iso.inspect(test_iso)["user_data"]))["autoinstall"]
    assert doc["shutdown"] == "poweroff" and doc["user-data"]["power_state"]["mode"] == "poweroff"
    assert "docker-ce" in doc["user-data"]["packages"]  # original content kept
    assert "poweroff" not in str(iso.inspect(prod)["user_data"])  # production ISO untouched


def test_doctor_runs(capsys):
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "xorriso" in out and "/10 available" in out


def test_phase_flags():
    p = cli.build_parser()
    assert cli._phases(p.parse_args(["verify", "x.iso"])) == 3
    assert cli._phases(p.parse_args(["verify", "x.iso", "--no-reboot"])) == 2
    assert cli._phases(p.parse_args(["build", "--installer-only"])) == 1
