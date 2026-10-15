# encrypted-disk

Full-disk encryption: LUKS2 under LVM using the installer's `lvm` layout.
isobake generates a per-device passphrase and shows it once next to the
password. The machine asks for it at every boot unless you also select
`tpm-unlock` or `usb-keyfile`. Keep the passphrase: it is the recovery key.
