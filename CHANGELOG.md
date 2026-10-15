# Changelog

## 0.2.0 (2026-10-15)

- `encrypted-disk` preset: LUKS2 under LVM with a per-device passphrase
- `tpm-unlock` preset: unattended boot via TPM 2.0, bound with Clevis during the install
- `usb-keyfile` preset: unattended boot via a keyfile on a `linux-key` USB partition
- verify runs a third phase, an unattended reboot, and can attach a software TPM (`--tpm`)
  or a virtual key stick (`--usb-key`); `build --verify` does so automatically
- `verify --inject-poweroff` tests a production ISO through a temporary copy; `--keep-disk` and `--resume`
- verify keeps UEFI NVRAM across phases and lets the guest reboot in place
- `doctor` command
- credentials table gains a disk passphrase column when encryption is selected

## 0.1.0 (2026-10-15)

First release.

- `init`, `fetch`, `build`, `verify`, `inspect`, `presets` commands
- Composable presets: base, docker, nvidia, tailscale, reverse-ssh, webhook, poweroff-after-install
- Per-device hostnames and SHA-512-crypt passwords, plaintext guard
- GPG and SHA256 verification of Ubuntu release media, local cache
- In-place xorriso repack preserving UEFI and BIOS boot
- Headless QEMU/KVM boot test
- Claude Code skill under `skills/isobake`
