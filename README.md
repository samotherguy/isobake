# isobake

Bake unattended Ubuntu install ISOs for machines that have no PXE server.

One command turns a stock Ubuntu Server ISO plus a short YAML file into one
ISO per device, each with its own hostname and a unique SHA-512-hashed
password, optionally joining your tailnet, installing Docker and NVIDIA
drivers, or registering itself with a webhook on first boot. Every ISO can
be boot-tested headless under QEMU before it goes on a USB stick.

```
pipx install git+https://github.com/Abhyuday98/isobake   # or: pip install git+https://github.com/Abhyuday98/isobake
isobake init          # writes isobake.yaml
isobake build         # downloads + verifies Ubuntu 24.04, bakes out/node-01.iso
isobake verify out/node-01.iso
```

## Why

PXE, MAAS and Packer are the right answer when you own the network. They are
the wrong answer when you are shipping a GPU box to a site with no IT staff,
seeding a homelab, or standing up ten lab machines on a Tuesday. There you
want a USB stick that installs the OS, sets a unique hostname and password,
connects the machine back to you, and never asks a question.

isobake does exactly that, and nothing else.

## What you get

- **Presets you compose.** `base`, `docker`, `nvidia`, `tailscale`,
  `reverse-ssh`, `webhook`, `encrypted-disk`, `tpm-unlock`, `usb-keyfile`,
  `poweroff-after-install`. Write your own as a folder with a `preset.yaml`.
  Presets deep-merge in order.
- **Per-device credentials.** Hostnames `edge-01 .. edge-NN` or an explicit
  list. Each ISO gets a fresh 20-character password, hashed with
  `openssl passwd -6`. Plaintext is printed once and never stored unless you
  ask for `--credentials-file`.
- **A plaintext guard.** The build refuses any preset or override that
  contains a literal password.
- **Verified sources.** The Ubuntu `SHA256SUMS` file is checked against the
  Ubuntu CD image signing key with GPG, the ISO against the checksum, and
  the result is cached in `~/.cache/isobake/isos`.
- **Fast repack.** The source ISO is never extracted. xorriso rewrites it in
  place with the patched `grub.cfg` and the `nocloud` files, replaying the
  original El Torito and hybrid MBR/GPT boot equipment. About five seconds
  per ISO on an SSD.
- **Full-disk encryption that boots unattended.** `encrypted-disk` puts
  LUKS2 under LVM with a per-device passphrase. `tpm-unlock` seals a key in
  the TPM 2.0 so the box boots on its own but the disk is dead if pulled.
  `usb-keyfile` does the same with a USB stick for hardware without a TPM.
- **A real boot test.** `isobake verify` boots the ISO in QEMU with KVM and
  OVMF, headless, in three phases: the install must finish and power off,
  the installed disk must complete first boot (every preset's `runcmd`) and
  power off, then it must come back up unattended and power off once more.
  With `--tpm` and `--usb-key` the VM gets an emulated TPM or a virtual key
  stick, so the encryption presets are proven end to end.

## Project file

```yaml
# isobake.yaml
source:
  release: "24.04"            # or  path: /path/to/ubuntu-live-server.iso
presets: [base, docker, tailscale, webhook]
devices:
  prefix: edge
  count: 3                    # edge-01, edge-02, edge-03
  # list: [{hostname: rack-a, username: ops}, lab-b]
identity:
  username: ops
  ssh_keys: [~/.ssh/id_ed25519.pub]
vars:                         # fills ${name} placeholders in presets
  tailscale_authkey: tskey-auth-...
  webhook_url: https://inventory.example.com/register
overrides:                    # raw autoinstall keys, merged last
  autoinstall:
    timezone: Asia/Singapore
kernel_args: [console=ttyS0,115200n8]
output: ./out
```

```
$ isobake build
signature ok: SHA256SUMS signed by the Ubuntu CD image key
cached: /home/you/.cache/isobake/isos/ubuntu-24.04.5-live-server-amd64.iso
building out/edge-01.iso
building out/edge-02.iso
building out/edge-03.iso
hostname  username  password
edge-01   ops       kQ3xT9wLm2Zp7RfC1dHs
edge-02   ops       Vb8NcJ4yPq6WtE2gXz0K
edge-03   ops       mR5sYh1LqA9nD3vF7uBt

Passwords are shown once and are not stored. Copy them now.
```

Flash with `dd`, Ventoy, Rufus or balenaEtcher. Boot the machine from USB. Walk away.

## Presets

| Preset | What it does | Needs |
|---|---|---|
| `base` | US locale, direct whole-disk layout, OpenSSH, curl, qemu-guest-agent | |
| `docker` | Docker Engine and compose plugin from Docker's apt repo, user in `docker` group | internet |
| `nvidia` | Recommended NVIDIA driver plus Container Toolkit; configures Docker runtime if present | internet |
| `tailscale` | Joins your tailnet with Tailscale SSH on | `vars.tailscale_authkey` |
| `reverse-ssh` | Persistent autossh reverse tunnel to a host you own | `vars.reverse_ssh_host/user/port` |
| `webhook` | POSTs hostname, machine-id, MAC, IP and SSH host key on first boot | `vars.webhook_url` |
| `encrypted-disk` | LUKS2 under LVM, per-device passphrase shown once at build | |
| `tpm-unlock` | Seals the LUKS key in the TPM 2.0 (PCR 7) via `systemd-cryptenroll`, switches initramfs to dracut | `encrypted-disk`, TPM 2.0 on |
| `usb-keyfile` | Keyfile on a USB partition labelled `linux-key`, unlocked through cryptsetup's `passdev` | `encrypted-disk`, a stick: `mkfs.ext4 -L linux-key` |
| `poweroff-after-install` | Test only: power off after install, after first boot, and on every boot after | |

Merge rules: mappings merge recursively, lists append without duplicates,
scalars from later presets win. `overrides:` is applied after all presets.
Placeholders look like `${name}` with a lowercase name, so shell variables
like `$HOME` and `$(cmd)` in `runcmd` pass through untouched. Built-in
placeholders: `${hostname}`, `${username}`, `${password_hash}`.

Add your own:

```
my-presets/
  k3s/
    preset.yaml     # an autoinstall fragment
    README.md       # first line is the description shown by `isobake presets`
```

```
isobake build --preset-dir ./my-presets --preset base,k3s
```

## Verify

```
isobake build --verify            # bakes, then boots every ISO under QEMU
isobake verify out/edge-01.iso    # boot an ISO you built earlier
```

Needs `qemu-system-x86`, `qemu-utils` and `ovmf` (`sudo apt install` them).
The VM gets 4 GB RAM, 2 CPUs, a 20 GB qcow2 disk and user-mode networking.

Three phases, each with its own timeout:

1. **install**: boot the ISO. Pass when the installer finishes and runs
   `poweroff`.
2. **first boot**: boot the installed disk without the ISO. Pass when
   cloud-init has run every preset's `runcmd` and powers off.
3. **reboot**: boot the disk again. Pass when it comes up unattended and
   powers off. This is where TPM and USB unlock are proven: a passphrase
   prompt would sit there until the timeout.

Timeout or any other exit is a fail, and the last 40 lines of the serial
log are printed. Add `console=ttyS0,115200n8` to `kernel_args` to get the
installer's output in that log. `--no-reboot` stops after phase two,
`--installer-only` after phase one.

`--verify` on `build` injects the `poweroff-after-install` preset and, when
the config selects `tpm-unlock` or `usb-keyfile`, attaches a software TPM
(`swtpm`) or a 16 MB virtual stick labelled `linux-key`. On a standalone
`isobake verify` pass `--tpm` and `--usb-key` yourself.

To test a production ISO without rebuilding it:

```
isobake verify out/edge-01.iso --inject-poweroff --tpm
```

That merges the poweroff preset into a temporary copy and boots the copy.
The ISO you ship is untouched.

`isobake doctor` lists every tool verify and build need and what to install.

## Inspect

```
$ isobake inspect out/edge-01.iso
kernel lines:
  linux /casper/vmlinuz autoinstall ds=nocloud\;s=/cdrom/nocloud/ console=ttyS0,115200n8 ---
  linux /casper/hwe-vmlinuz autoinstall ds=nocloud\;s=/cdrom/nocloud/ console=ttyS0,115200n8 ---
nocloud files: /nocloud, /nocloud/meta-data, /nocloud/user-data
user-data:
  #cloud-config
  autoinstall:
    version: 1
    ...
```

## Encryption

```yaml
presets: [base, encrypted-disk, tpm-unlock]
```

```
$ isobake build
hostname  username  password              disk passphrase
edge-01   ops       kQ3xT9wLm2Zp7RfC1dHs  Hs8dKq2mN4vB7xR1tY6wP0zL
```

The installer formats the disk as LUKS2 under LVM with that passphrase.
On first boot `tpm-unlock` runs `systemd-cryptenroll --tpm2-device=auto
--tpm2-pcrs=7`, sets `tpm2-device=auto` in crypttab, installs dracut (Ubuntu's
initramfs-tools ignores TPM options) and regenerates the initrd. From the
next boot the disk unlocks itself when the secure-boot state matches. Move
the disk to another machine, or change the firmware, and it asks for the
passphrase instead. The passphrase stays in keyslot 0 as the recovery key,
and every copy of it in the install logs is shredded.

`usb-keyfile` is for hardware without a TPM 2.0. First boot writes a random
256-byte key to a partition labelled `linux-key`, enrols it as a keyslot,
and points crypttab at it through cryptsetup's `passdev` keyscript with a
10-second wait. Stick in: boots. Stick out: passphrase prompt.

Both are verified by `isobake build --verify`, which attaches an emulated
TPM or a virtual key stick to the VM and requires an unattended third boot.

Limits worth knowing: the LUKS passphrase has to reach the installer in
clear, so it is in `/nocloud/user-data` on the ISO. Treat built ISOs as
secrets and wipe the stick after use. TPM sealing against PCR 7 survives
kernel updates but not firmware or secure-boot changes; keep the passphrase.

## Requirements

Linux host, Python 3.10+, `xorriso`, `gpg`, `openssl`, `curl`. On Debian
and Ubuntu: `sudo apt install xorriso gnupg openssl curl`. QEMU and OVMF
only for `verify`, `swtpm` for `--tpm`, `e2fsprogs` for `--usb-key`.
Run `isobake doctor` to check. Tested with Ubuntu Server 24.04 ISOs; 22.04 should work
since the grub layout is the same. Desktop ISOs are not tested.

## How it works

1. `source.py` reads `releases.ubuntu.com/<release>/SHA256SUMS`, verifies
   its GPG signature with a dedicated keyring, picks the newest
   `live-server-amd64` ISO, downloads it with resume, checks the hash.
2. `presets.py` merges the chosen fragments and fills placeholders.
3. `render.py` adds `identity`, SSH keys and overrides, refuses plaintext
   passwords, and dumps a `#cloud-config` document with the `autoinstall` key.
4. `iso.py` pulls `/boot/grub/grub.cfg` from the source, adds
   `autoinstall ds=nocloud\;s=/cdrom/nocloud/` to each kernel line, sets the
   menu timeout to 1, and asks xorriso to write a new ISO with the patched
   grub plus `/nocloud/user-data` and `/nocloud/meta-data`, boot equipment
   replayed from the source.
5. `verify.py` runs QEMU with `-no-reboot` three times, ISO then disk then
   disk again, and treats three clean exits as pass.

## Security notes

- Passwords are generated with `secrets`, hashed with SHA-512 crypt, and
  printed to stdout once. `--credentials-file` writes them with mode 0600.
- Signature verification can be skipped with `--no-gpg`. Do not do that for
  machines you care about.
- Anything in `runcmd` runs as root on first boot. Read a preset before you
  trust it.
- The `reverse-ssh` and `tailscale` presets embed the auth material you
  give them in the ISO. Treat built ISOs as secrets.

## Development

```
git clone https://github.com/Abhyuday98/isobake
cd isobake
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check src tests
```

The test suite builds a 1 MB synthetic ISO with xorriso and runs the whole
pipeline against it, so it is fast and needs no download. The real boot test
is manual: `isobake build --verify` with a real release.

## Background

The USB-stick install is still how most machines outside a datacenter get
their OS: edge boxes, lab hardware, kiosks, homelab nodes. The tooling for
doing it unattended has been a bash script and a wiki page for a decade.
isobake is the tool I wanted for that job: presets instead of hand-edited
YAML, a unique identity per machine, encryption that does not need someone
at the keyboard, and a boot test so the stick works the first time.

## License

MIT
