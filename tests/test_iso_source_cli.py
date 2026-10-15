import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from isobake import cli, iso, source
from isobake.errors import BuildError

GRUB = """set timeout=30

menuentry "Try or Install Ubuntu Server" {
\tset gfxpayload=keep
\tlinux\t/casper/vmlinuz  ---
\tinitrd\t/casper/initrd
}
menuentry "HWE" {
\tlinux\t/casper/hwe-vmlinuz  ---
\tinitrd\t/casper/hwe-initrd
}
menuentry 'Test memory' {
\tlinux16 /boot/memtest86+x64.bin
}
"""

needs_xorriso = pytest.mark.skipif(not shutil.which("xorriso"), reason="xorriso not installed")


def test_patch_grub_adds_arg_before_separator_and_is_idempotent():
    out = iso.patch_grub(GRUB, ["console=ttyS0"])
    assert "linux\t/casper/vmlinuz autoinstall ds=nocloud\\;s=/cdrom/nocloud/ console=ttyS0 ---" in out
    assert "hwe-vmlinuz autoinstall ds=nocloud\\;s=/cdrom/nocloud/ console=ttyS0 ---" in out
    assert "memtest86+x64.bin autoinstall" not in out
    assert "set timeout=1\n" in out
    assert iso.patch_grub(out, ["console=ttyS0"]) == out


def test_patch_grub_without_separator_and_rejects_foreign():
    assert iso.patch_grub("linux /casper/vmlinuz quiet\n").rstrip().endswith(
        "quiet autoinstall ds=nocloud\\;s=/cdrom/nocloud/")
    with pytest.raises(BuildError, match="no `linux"):
        iso.patch_grub("menuentry 'x' { }\n")


@pytest.fixture
def synthetic_iso(tmp_path: Path) -> Path:
    """A tiny ISO with the same grub.cfg layout as an Ubuntu installer, no boot image."""
    root = tmp_path / "root"
    (root / "boot" / "grub").mkdir(parents=True)
    (root / "boot" / "grub" / "grub.cfg").write_text(GRUB)
    (root / "boot" / "grub" / "loopback.cfg").write_text(GRUB)
    (root / "casper").mkdir()
    (root / "casper" / "vmlinuz").write_bytes(b"\0" * 1024)
    out = tmp_path / "src.iso"
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-o", str(out), "-V", "TEST", str(root)],
                   check=True, capture_output=True)
    return out


@needs_xorriso
def test_repack_and_inspect_round_trip(synthetic_iso: Path, tmp_path: Path):
    cfgs = iso.patched_boot_cfgs(synthetic_iso)
    assert set(cfgs) == {iso.GRUB_CFG, iso.LOOPBACK_CFG}
    out = iso.repack(synthetic_iso, tmp_path / "out" / "x.iso", "#cloud-config\nautoinstall: {version: 1}\n", cfgs)
    assert out.is_file() and not out.with_suffix(".iso.part").exists()
    info = iso.inspect(out)
    assert "/nocloud/user-data" in info["nocloud"] and "/nocloud/meta-data" in info["nocloud"]
    assert all("autoinstall" in ln for ln in info["kernel_lines"] if "vmlinuz" in ln)
    assert yaml.safe_load(info["user_data"]) == {"autoinstall": {"version": 1}}
    assert "autoinstall ds=nocloud" in iso.extract_text(out, iso.LOOPBACK_CFG)
    # the source is untouched
    assert "autoinstall" not in iso.extract_text(synthetic_iso, iso.GRUB_CFG)


@needs_xorriso
def test_cli_build_end_to_end_on_synthetic_iso(synthetic_iso: Path, tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "isobake.yaml").write_text(
        "presets: [base, webhook]\ndevices: {prefix: box, count: 2}\n"
        "vars: {webhook_url: https://example.test/hook}\nkernel_args: [console=ttyS0]\n")
    rc = cli.main(["build", "--source", str(synthetic_iso), "--credentials-file", "creds.txt"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "box-01" in out and "box-02" in out
    assert (tmp_path / "out" / "box-01.iso").is_file() and (tmp_path / "out" / "box-02.iso").is_file()
    assert oct((tmp_path / "creds.txt").stat().st_mode)[-3:] == "600"
    info = iso.inspect(tmp_path / "out" / "box-02.iso")
    doc = yaml.safe_load(info["user_data"])["autoinstall"]
    assert doc["identity"]["hostname"] == "box-02" and doc["identity"]["password"].startswith("$6$")
    assert "https://example.test/hook" in doc["user-data"]["runcmd"][0]
    assert any("console=ttyS0" in ln for ln in info["kernel_lines"])


def test_cli_errors_map_to_exit_codes(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["build"]) == 1  # no config
    assert "isobake init" in capsys.readouterr().err
    (tmp_path / "isobake.yaml").write_text("presets: [nope]\n")
    assert cli.main(["build", "--source", str(tmp_path / "missing.iso")]) == 1
    assert cli.main(["presets"]) == 0
    assert "poweroff-after-install" in capsys.readouterr().out


def test_latest_server_iso_picks_newest_point_release():
    sums = "\n".join([
        "aa" * 32 + " *ubuntu-24.04.3-live-server-amd64.iso",
        "bb" * 32 + " *ubuntu-24.04.10-live-server-amd64.iso",
        "cc" * 32 + " *ubuntu-24.04.5-desktop-amd64.iso",
    ]) + "\n"
    assert source.latest_server_iso(sums) == ("ubuntu-24.04.10-live-server-amd64.iso", "bb" * 32)
    with pytest.raises(BuildError):
        source.latest_server_iso("nothing here")


def test_fetch_rejects_checksum_mismatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    sums = "ab" * 32 + " *ubuntu-24.04.9-live-server-amd64.iso\n"
    monkeypatch.setattr(source, "_fetch", lambda url: sums.encode() if url.endswith("SHA256SUMS") else b"sig")
    monkeypatch.setattr(source, "_download", lambda url, dest: dest.write_bytes(b"not the iso"))
    with pytest.raises(BuildError, match="checksum mismatch"):
        source.fetch("24.04", gpg=False, log=lambda *_: None)
    assert not (tmp_path / "isobake" / "isos" / "ubuntu-24.04.9-live-server-amd64.iso").exists()
