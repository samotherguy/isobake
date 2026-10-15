# isobake design

Date: 2026-10-15. Status: approved in conversation, v1 scope.

## Purpose

Build unattended Ubuntu install ISOs for machines that have no PXE server:
edge boxes, lab hardware, homelab nodes, small fleets. One command turns a
stock Ubuntu Server ISO plus a short config into one ISO per device, each
with its own hostname and credentials, optionally registering itself on
first boot. A built ISO can be boot-tested headless under QEMU before it
goes on a USB stick.

Who it is for: anyone provisioning Linux boxes by USB stick. Success looks
like: `pip install isobake`, `isobake build`, flash, boot, walk away.

## Scope

In v1:

- `isobake build` from an `isobake.yaml` project file plus CLI overrides.
- Composable presets (bundled and user-defined) merged into one autoinstall.
- Per-device hostname, user, SHA-512-crypt password, optional SSH keys.
- Fleet builds: N devices from one config, one ISO each.
- Source ISO download with SHA256 and GPG verification, cached locally.
- `isobake verify <iso>`: headless QEMU boot, pass on clean poweroff.
- `isobake inspect <iso>`: show the embedded autoinstall and boot args.
- `isobake presets`: list available presets and what they add.
- Tests, CI, MIT license, README, a Claude Code skill.

Out of v1: web UI, email or cloud delivery, inventory database, USB writer,
non-Ubuntu distros, desktop ISO (works in principle, not tested).

## CLI

```
isobake init                      # write a starter isobake.yaml
isobake fetch [--release 24.04]   # download + verify source ISO into cache
isobake build [-c isobake.yaml] [--count N] [--preset a,b] [--out DIR]
isobake verify out/edge-01.iso [--timeout 1800] [--keep-disk]
isobake inspect out/edge-01.iso
isobake presets
```

Exit codes: 0 ok, 1 usage or config error, 2 build failure, 3 verify failed.

## Project file

```yaml
# isobake.yaml
source:
  release: "24.04"            # or: path: /path/to/ubuntu.iso
presets: [base, docker, tailscale]
devices:
  count: 3                    # hostnames edge-01.. or explicit list below
  prefix: edge
  # list: [{hostname: rack-a, username: ops}]
identity:
  username: ops
  ssh_keys: [~/.ssh/id_ed25519.pub]
vars:                         # substituted into presets as ${name}
  tailscale_authkey: tskey-...
  webhook_url: https://example.com/register
overrides:                    # deep-merged last, raw autoinstall keys
  autoinstall:
    timezone: Asia/Singapore
output: ./out
```

## Presets

A preset is a directory with `preset.yaml` (an autoinstall fragment) and an
optional `README.md`. Fragments are deep-merged in order; lists append and
de-duplicate. `${var}` placeholders are filled from `vars` and from
per-device values (`hostname`, `username`, `password_hash`).

Bundled: `base` (locale, storage direct, openssh, qemu-guest-agent),
`docker`, `nvidia` (driver + container toolkit), `tailscale`,
`reverse-ssh` (autossh tunnel to a host you own), `webhook` (first-boot
POST of hostname, machine-id, MAC and IP to `${webhook_url}`),
`poweroff-after-install` (used by verify).

User presets: any directory passed with `--preset-dir` or listed under
`preset_dirs` in the project file.

## Credentials

Per device: hostname from prefix plus index or explicit list; password 20
chars from `secrets`; hash with `openssl passwd -6` (Python's `crypt` is
gone in 3.13). Plaintext is printed once at the end of `build`. It is never
written to disk unless `--credentials-file PATH` is passed, and then with
mode 0600. Presets must not contain literal passwords; the build fails if
any `password:` key holds a value that does not start with `$6$`.

## ISO repack

Written over xorriso in Python.

1. Extract only `/boot/grub/grub.cfg` from the source ISO.
2. Add `autoinstall ds=nocloud;s=/cdrom/nocloud/` to every `linux` line,
   and set the timeout to 1 so the menu does not wait.
3. Write `/nocloud/user-data` (the rendered autoinstall document, which
   embeds the cloud-init `user-data` section) and an empty `/nocloud/meta-data`.
4. `xorriso -indev src.iso -outdev out.iso -boot_image any replay -map ...`
   writes the new ISO with the original El Torito and hybrid MBR/GPT boot
   equipment preserved. No full extraction, no squashfs changes.
5. Confirm by listing `/nocloud` in the output and grepping the patched
   grub.cfg.

## Verify

`isobake verify` needs `qemu-system-x86_64` and OVMF. It creates a 20 GB
qcow2, boots the ISO with 4 GB RAM, KVM if `/dev/kvm` is writable,
`-nographic`, serial to a log file, `-no-reboot`. The build injects the
`poweroff-after-install` preset when `--verify` is passed to build, or the
user adds it. QEMU exiting 0 before the timeout is a pass. The serial log
is kept next to the ISO. Timeout or a non-zero exit is a fail with the last
40 log lines shown.

## Code layout

```
src/isobake/
  cli.py          argparse entry point
  config.py       load + validate isobake.yaml, apply CLI overrides
  presets.py      discover, load, deep-merge, substitute
  credentials.py  hostname, password, hash, ssh keys
  render.py       assemble user-data + meta-data
  source.py       release lookup, download, SHA256 + GPG verify, cache
  iso.py          grub patch and xorriso repack
  verify.py       QEMU runner
  presets/        bundled preset directories
tests/            pytest; unit for every module, integration on a tiny
                  synthetic ISO, QEMU test skipped when qemu is absent
skills/isobake/   Claude Code skill
.github/workflows/ci.yml
```

Dependencies: Python 3.10+, PyYAML. System: xorriso, gpg, openssl;
qemu-system-x86 and ovmf only for verify.

## Error handling

Every subprocess call checks the return code and surfaces stderr. Missing
system tools are reported by name with the apt package to install. Config
validation lists every problem at once. Builds are atomic: write to a temp
file and rename on success.

## Testing

- Unit: deep-merge rules, placeholder substitution, missing-var error,
  hostname generation, hash format, grub patch idempotence, config
  validation messages, plaintext-password guard.
- Integration: build a 1 MB synthetic ISO with a grub.cfg, repack it, assert
  `/nocloud/user-data` exists and grub has the autoinstall arg.
- End to end (local, before publish): fetch real 24.04 ISO, build with
  base + poweroff-after-install, verify under QEMU/KVM on this machine.
