# tpm-unlock

Unattended boot on an encrypted disk. During the install, while the LUKS
volume is open, the key is sealed to the machine's TPM 2.0 against PCR 7
(secure-boot state) with Clevis, and Ubuntu's initramfs unlocks it at boot.
The passphrase stays in keyslot 0 as the recovery key, and the install logs
that contain it are shredded on first boot. Requires `encrypted-disk` and a
TPM 2.0 enabled in firmware; the install fails loudly if there is none.
Pull the disk, or change the firmware, and it asks for the passphrase.
