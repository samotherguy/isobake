---
name: isobake
description: Build unattended Ubuntu install ISOs with isobake. Use when the user wants an autoinstall or unattended Ubuntu ISO, a bootable USB that installs Ubuntu without prompts, per-device hostnames and passwords for a fleet of machines, Docker, NVIDIA or Tailscale baked into an install, or to boot-test an ISO in QEMU before flashing it.
---

# isobake

`isobake` bakes a stock Ubuntu Server ISO into one unattended-install ISO per
device. Config lives in `isobake.yaml`. Full docs: the project README.

## Workflow

1. **Check the tool is installed.** `isobake --version`. If missing:
   `pipx install git+https://github.com/samotherguy/isobake` and
   `sudo apt install xorriso gnupg openssl curl`.
2. **Start a project.** In an empty directory run `isobake init`, then edit
   `isobake.yaml`. Ask the user only for what the chosen presets need
   (see table). Default to `presets: [base]`, `username: ubuntu`, one device.
3. **Build.** `isobake build`. The first run downloads and GPG-verifies the
   Ubuntu ISO into `~/.cache/isobake/isos` (about 3 GB, cached after).
   The command prints a hostname/username/password table **once**. Show it
   to the user verbatim and tell them it is not stored. Use
   `--credentials-file creds.txt` only when the user asks to keep it.
4. **Test before flashing, if QEMU is available.** `isobake build --verify`
   or `isobake verify out/<host>.iso`. Three phases: install, first boot,
   unattended reboot; each must power off cleanly. `build --verify` attaches
   a software TPM or virtual USB key automatically for the encryption
   presets. For a production ISO use `verify --inject-poweroff`. Run
   `isobake doctor` first. Expect 10 to 20 minutes with KVM. Add `kernel_args: [console=ttyS0,115200n8]` to the
   config first so the serial log is useful on failure.
5. **Confirm the ISO contents** with `isobake inspect out/<host>.iso` when
   the user wants to see what was baked in.

## Presets and what to ask for

| Preset | Ask the user for |
|---|---|
| `base` | nothing |
| `docker` | nothing (needs internet during install) |
| `nvidia` | nothing; mention a reboot after first boot loads the driver |
| `tailscale` | `vars.tailscale_authkey` (reusable, pre-authorized key) |
| `reverse-ssh` | `vars.reverse_ssh_host`, `reverse_ssh_user`, `reverse_ssh_port`, and an SSH public key for `identity.ssh_keys` |
| `webhook` | `vars.webhook_url` |
| `encrypted-disk` | nothing; the build prints a per-device disk passphrase, show it once |
| `tpm-unlock` | confirm the hardware has TPM 2.0 enabled; needs `encrypted-disk` |
| `usb-keyfile` | a USB stick formatted `mkfs.ext4 -L linux-key`, plugged in during the install; needs `encrypted-disk` |
| `poweroff-after-install` | nothing; `--verify` adds it automatically |

## Rules

- Never put a plaintext password in a preset or override. The build fails
  on purpose if you do. isobake generates and hashes passwords itself.
- Never pass `--no-gpg` unless the user explicitly accepts unverified media.
- Built ISOs contain any auth keys from `vars`. Do not upload them anywhere
  without asking.
- For production ISOs do not add `poweroff-after-install`; machines should
  reboot into the installed system.
- Custom needs beyond the bundled presets: create `<dir>/<name>/preset.yaml`
  with an `autoinstall:` fragment and a `README.md`, then
  `isobake build --preset-dir <dir> --preset base,<name>`. Autoinstall
  reference: https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html

## Exit codes

0 ok, 1 config or usage error (message says what to fix), 2 build failure
(missing tool or xorriso error), 3 verify failed (serial log tail printed).

## Example session

```
isobake init
# edit isobake.yaml: presets: [base, docker, tailscale], devices: {prefix: edge, count: 3},
#   vars: {tailscale_authkey: tskey-auth-...}
isobake build --verify
```
