# usb-keyfile

Unattended boot on an encrypted disk using a USB stick as the key, for
machines without a usable TPM. Plug a stick formatted `mkfs.ext4 -L linux-key`
in during the install: a random 256-byte keyfile is written to it (or reused
if present), added as a LUKS keyslot, and crypttab points at it through
cryptsetup's `passdev` keyscript with a 10-second wait. Stick in: boots.
Stick out: passphrase prompt. Requires `encrypted-disk`. The install logs
that contain the passphrase are shredded on first boot.
