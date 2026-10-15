# poweroff-after-install

Test-only preset used by `isobake verify`: powers off when the installer
finishes, again at the end of first boot after every `runcmd`, and on every
boot after that once the system is up. Each power-off is one verify phase
passing. Never ship this on a production ISO.
