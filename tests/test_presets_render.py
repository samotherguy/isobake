from pathlib import Path

import pytest
import yaml

from isobake import config, presets, render
from isobake.errors import ConfigError


def test_deep_merge_rules():
    a = {"x": {"a": 1, "l": [1, 2]}, "s": "old"}
    b = {"x": {"b": 2, "l": [2, 3]}, "s": "new"}
    assert presets.deep_merge(a, b) == {"x": {"a": 1, "b": 2, "l": [1, 2, 3]}, "s": "new"}


def test_substitute_fills_and_reports_missing():
    assert presets.substitute({"k": ["hi ${name}", "$(shell) ${NOT_A_VAR}"]}, {"name": "x"}) == {
        "k": ["hi x", "$(shell) ${NOT_A_VAR}"]
    }
    with pytest.raises(ConfigError, match="missing variable.*alpha, beta"):
        presets.substitute({"a": "${alpha}", "b": ["${beta}", "${alpha}"]}, {})


def test_bundled_presets_discovered_and_valid():
    found = presets.discover()
    assert {"base", "docker", "nvidia", "tailscale", "reverse-ssh", "webhook",
            "poweroff-after-install"} <= set(found)
    for p in found.values():
        assert "autoinstall" in p.fragment, p.name
        assert p.description, f"{p.name} needs a README first line"


def test_unknown_preset_lists_known():
    with pytest.raises(ConfigError, match="unknown preset.*nope.*Known: .*base"):
        presets.merge_presets(["base", "nope"], presets.discover())


def test_user_preset_dir_overrides_bundled(tmp_path: Path):
    d = tmp_path / "base"
    d.mkdir()
    (d / "preset.yaml").write_text("autoinstall: {locale: de_DE.UTF-8}\n")
    (d / "README.md").write_text("# mine\n")
    found = presets.discover([tmp_path])
    assert found["base"].fragment["autoinstall"]["locale"] == "de_DE.UTF-8"
    assert found["base"].description == "mine"


def _cfg(**over) -> config.Config:
    raw = {"devices": {"prefix": "edge", "count": 2}, "identity": {"username": "ops"},
           "vars": {"tailscale_authkey": "tskey-test"}, **over}
    return config.from_dict(raw)


def test_render_identity_and_substitution():
    cfg = _cfg(presets=["base", "tailscale"])
    text = render.render_device(cfg, cfg.devices[1], "$6$abc$hash", ["ssh-ed25519 AAAA test"])
    assert text.startswith("#cloud-config\n")
    doc = yaml.safe_load(text)["autoinstall"]
    assert doc["identity"] == {"hostname": "edge-02", "username": "ops", "password": "$6$abc$hash"}
    assert doc["ssh"]["authorized-keys"] == ["ssh-ed25519 AAAA test"]
    assert doc["version"] == 1
    assert "tailscale up --authkey=tskey-test --hostname=edge-02 --ssh" in doc["user-data"]["runcmd"]


def test_render_overrides_merge_last_and_verify_preset():
    cfg = _cfg(overrides={"autoinstall": {"timezone": "Asia/Singapore", "packages": ["htop"]}})
    doc = yaml.safe_load(render.render_device(cfg, cfg.devices[0], "$6$x$y", [],
                                             ["poweroff-after-install"]))["autoinstall"]
    assert doc["timezone"] == "Asia/Singapore"
    assert "htop" in doc["packages"] and "curl" in doc["packages"]
    assert doc["shutdown"] == "poweroff"


def test_render_refuses_plaintext_password():
    cfg = _cfg(overrides={"autoinstall": {"user-data": {"users": [{"name": "x", "passwd": "hunter2"}]}}})
    with pytest.raises(ConfigError, match="plaintext password"):
        render.render_device(cfg, cfg.devices[0], "$6$x$y", [])


def test_render_allows_generated_luks_passphrase_only_at_storage_layout():
    cfg = _cfg(presets=["base", "encrypted-disk", "tpm-unlock"])
    text = render.render_device(cfg, cfg.devices[0], "$6$x$y", [], luks_passphrase="Secret24Chars")
    doc = yaml.safe_load(text)["autoinstall"]
    assert doc["storage"]["layout"] == {"name": "lvm", "password": "Secret24Chars"}
    assert any("Secret24Chars" in c for c in doc["late-commands"])
    assert "Secret24Chars" not in str(doc["user-data"])  # nothing secret reaches the installed seed
    cfg = _cfg(overrides={"autoinstall": {"identity": {"password": "plain"}}})
    with pytest.raises(ConfigError, match="identity.password: plaintext"):
        render.render_device(cfg, cfg.devices[0], "$6$x$y", [])
