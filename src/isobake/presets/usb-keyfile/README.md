# usb-keyfile

Unattended boot on an encrypted disk using a USB stick as the key, for
machines without a usable TPM. First boot looks for a partition labelled
`linux-key`, writes a random 256-byte keyfile to it if there is none, adds it
as a LUKS keyslot, and points crypttab at it through the `passdev` keyscript
with a 10-second wait. Boot with the stick in and the disk unlocks; boot
without it and the passphrase prompt appears. Requires `encrypted-disk`.
Prepare the stick with `mkfs.ext4 -L linux-key /dev/sdX1`.
