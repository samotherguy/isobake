import shutil
import subprocess
from pathlib import Path

import pytest

from isobake import config, credentials
from isobake.errors import ConfigError


def test_hostname_sequence_pads_and_validates():
    assert credentials.hostname_sequence("edge", 3) == ["edge-01", "edge-02", "edge-03"]
    assert credentials.hostname_sequence("n", 100)[-1] == "n-100"
    with pytest.raises(ConfigError):
        credentials.hostname_sequence("bad name", 1)


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")
def test_hash_password_is_sha512_crypt_and_verifiable():
    pw = credentials.generate_password()
    assert len(pw) == 20 and pw.isalnum()
    digest = credentials.hash_password(pw)
    assert digest.startswith("$6$")
    salt = digest.split("$")[2]
    again = subprocess.run(["openssl", "passwd", "-6", "-salt", salt, pw],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert again == digest


def test_read_ssh_keys_skips_comments(tmp_path: Path):
    k = tmp_path / "id.pub"
    k.write_text("# comment\nssh-ed25519 AAAA one\n\nssh-rsa BBBB two\n")
    assert credentials.read_ssh_keys([k]) == ["ssh-ed25519 AAAA one", "ssh-rsa BBBB two"]
    with pytest.raises(ConfigError, match="ssh key not found"):
        credentials.read_ssh_keys([tmp_path / "missing.pub"])


def test_config_defaults_and_device_list():
    cfg = config.from_dict({})
    assert cfg.source_release == "24.04" and cfg.presets == ["base"]
    assert [d.hostname for d in cfg.devices] == ["node-01"]
    cfg = config.from_dict({"devices": {"list": ["rack-a", {"hostname": "lab-b", "username": "root1"}]}})
    assert [(d.hostname, d.username) for d in cfg.devices] == [("rack-a", "ubuntu"), ("lab-b", "root1")]


def test_config_reports_all_errors_at_once():
    with pytest.raises(ConfigError) as e:
        config.from_dict({"identity": {"username": "9bad"}, "devices": {"count": 0},
                          "vars": "nope", "kernel_args": "x"})
    msg = str(e.value)
    for frag in ("identity.username", "devices.count", "vars:", "kernel_args:"):
        assert frag in msg


def test_config_duplicate_hostnames_and_cli_overrides(tmp_path: Path):
    with pytest.raises(ConfigError, match="duplicate hostname: a"):
        config.from_dict({"devices": {"list": ["a", "a"]}})
    with pytest.raises(ConfigError, match="at least one device"):
        config.from_dict({"devices": {"list": []}})
    cfg = config.from_dict({"source": {"release": "22.04"}, "presets": ["base", "docker"]},
                           base_dir=tmp_path,
                           cli={"count": 3, "presets": "base", "output": "o", "vars": {"k": "v"},
                                "source": tmp_path / "x.iso"})
    assert len(cfg.devices) == 3 and cfg.presets == ["base"]
    assert cfg.output == tmp_path / "o" and cfg.variables == {"k": "v"}
    assert cfg.source_path == tmp_path / "x.iso" and cfg.source_release is None


def test_init_writes_loadable_starter(tmp_path: Path):
    p = tmp_path / "isobake.yaml"
    config.write_starter(p)
    cfg = config.load(p)
    assert cfg.devices[0].hostname == "node-01"
    with pytest.raises(ConfigError, match="already exists"):
        config.write_starter(p)
