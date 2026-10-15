# tpm-unlock

Unattended boot on an encrypted disk: first boot enrols the LUKS volume with
the machine's TPM 2.0 (PCR 7, secure-boot state) using `systemd-cryptenroll`,
switches the initramfs to dracut because Ubuntu's initramfs-tools ignores
`tpm2-device=auto`, and rebuilds it. The passphrase stays in keyslot 0 as the
recovery key and is shredded from the install logs. Requires `encrypted-disk`
and a TPM 2.0 enabled in firmware. Pull the disk and it stays locked.
