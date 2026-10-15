# isobake v1 implementation plan

Spec: `docs/superpowers/specs/2026-10-15-isobake-design.md`. Executed inline
in one session, test-first per module, one commit per task.

1. **Scaffold.** pyproject (setuptools, `isobake` console script, PyYAML),
   LICENSE (MIT), .gitignore, package skeleton, pytest config, ruff config.
2. **presets.py.** `deep_merge`, `substitute` with `${name}` placeholders,
   preset discovery from bundled dir plus user dirs. Tests for merge rules,
   list de-dup, missing var error, unknown preset error.
3. **credentials.py.** password, `openssl passwd -6` hash, hostname
   sequence, ssh key reading. Tests check hash prefix and verify round trip
   with `openssl passwd -6 -salt`.
4. **config.py.** dataclass, YAML load, validation with collected errors,
   device list resolution. Tests for each validation message.
5. **render.py.** assemble per-device autoinstall document, plaintext
   password guard, `#cloud-config` dump. Tests on a fixture config.
6. **iso.py.** grub patch (idempotent), xorriso repack with boot replay,
   inspect. Unit test on grub text; integration test on a synthetic ISO
   built with xorriso in a temp dir.
7. **source.py.** release index parse, download with resume, SHA256 check,
   GPG verify via dedicated keyring, cache. Tests mock the network and
   verify checksum failure path.
8. **verify.py.** QEMU runner with firmware detection, timeout, log tail.
   Test is skipped when qemu is missing; covered end to end locally.
9. **cli.py.** subcommands init, fetch, build, verify, inspect, presets.
   Test `--help` and a full `build` against the synthetic ISO.
10. **Bundled presets** with READMEs: base, docker, nvidia, tailscale,
    reverse-ssh, webhook, poweroff-after-install.
11. **Docs and packaging.** README with quickstart, preset table, verify
    section; CHANGELOG; GitHub Actions CI; Claude skill
    under `skills/isobake/`.
12. **End to end.** fetch 24.04, build with base + poweroff-after-install,
    `isobake verify` under KVM on this machine. Fix anything found.
13. **Publish.** create public repo `samotherguy/isobake`, push, confirm CI
    green, tag v0.1.0.
