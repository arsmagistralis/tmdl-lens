"""
test_config.py - pytest tests for src.config.
"""

import json
import os
import re
import sys

import pytest

from tmdl_lens import config
from tmdl_lens.config import validate_config

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "_config_path", lambda: str(path))
    return path


@pytest.fixture
def pip_layout(tmp_path, monkeypatch):
    package_parent = tmp_path / "site-packages"
    package_parent.mkdir()
    appdata = tmp_path / "appdata"
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(config, "_package_parent", lambda: str(package_parent))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(appdata))
    return package_parent, appdata / "tmdl-lens" / "config.json"


def test_valid_config_no_warnings(tmp_path):
    warnings = validate_config({
        "reports_folder": str(tmp_path),
        "output_folder":  str(tmp_path),
        "watch_debounce": 10,
        "output_format":  "md",
    })
    assert warnings == []


def test_empty_reports_folder_warns():
    warnings = validate_config({"reports_folder": ""})
    assert any("reports_folder" in w for w in warnings)


def test_missing_reports_folder_warns(tmp_path):
    missing = str(tmp_path / "does-not-exist")
    warnings = validate_config({"reports_folder": missing})
    assert any("does not exist" in w for w in warnings)


def test_missing_output_folder_warns(tmp_path):
    warnings = validate_config({
        "reports_folder": str(tmp_path),
        "output_folder":  str(tmp_path / "does-not-exist"),
    })
    assert any("output_folder" in w for w in warnings)


def test_watch_debounce_out_of_range_warns():
    warnings = validate_config({"watch_debounce": 500})
    assert any("watch_debounce" in w for w in warnings)


def test_watch_debounce_non_numeric_warns():
    warnings = validate_config({"watch_debounce": "abc"})
    assert any("watch_debounce" in w for w in warnings)


def test_invalid_output_format_warns():
    warnings = validate_config({"output_format": "pdf"})
    assert any("output_format" in w for w in warnings)


@pytest.mark.parametrize("value", ["html", "md", "txt"])
def test_supported_output_formats_do_not_warn(value):
    warnings = validate_config({"output_format": value})
    assert not any("output_format" in w for w in warnings)


def test_bom_file_loads_values(cfg_file):
    cfg_file.write_bytes(b'\xef\xbb\xbf{"owner": "o", "output_format": "md"}')
    result = config.load_result()
    assert result.error == ""
    assert result.config["owner"] == "o"
    assert result.config["output_format"] == "md"


@pytest.mark.parametrize("content", [
    b'{"owner": "o"',
    b"[1, 2]",
    '{"owner": "ł"}'.encode("cp1250"),
])
def test_unusable_file_reports_error_and_defaults(cfg_file, content):
    cfg_file.write_bytes(content)
    result = config.load_result()
    assert result.failed is True
    assert result.config == config.DEFAULTS
    assert cfg_file.read_bytes() == content


def test_missing_file_is_not_a_failure(cfg_file):
    result = config.load_result()
    assert result.error == "missing"
    assert result.failed is False
    assert result.config == config.DEFAULTS


def test_features_false_uses_default_with_warning(cfg_file):
    cfg_file.write_text(json.dumps({"features": False}), encoding="utf-8")
    result = config.load_result()
    assert result.config["features"] == {"watcher": True}
    assert len(result.warnings) == 1
    assert "'features'" in result.warnings[0]


def test_file_hashes_null_is_empty_without_warning(cfg_file):
    cfg_file.write_text(json.dumps({"file_hashes": None}), encoding="utf-8")
    result = config.load_result()
    assert result.config["file_hashes"] == {}
    assert result.warnings == []


def test_file_hashes_with_non_string_values_is_rejected(cfg_file):
    cfg_file.write_text(json.dumps({"file_hashes": {"a": 1}}), encoding="utf-8")
    result = config.load_result()
    assert result.config["file_hashes"] == {}
    assert len(result.warnings) == 1


def test_wrong_types_use_defaults_and_name_key_found_and_used(cfg_file):
    cfg_file.write_text(
        json.dumps({"owner": 5, "include_dax": "yes", "watch_debounce": True}),
        encoding="utf-8",
    )
    result = config.load_result()
    assert result.config["owner"] == ""
    assert result.config["include_dax"] is True
    assert result.config["watch_debounce"] == 10
    assert len(result.warnings) == 3
    by_key = {re.search(r"'([^']+)'", w).group(1): w for w in result.warnings}
    assert "has invalid value 5, using \"\"" in by_key["owner"]
    assert "has invalid value \"yes\", using true" in by_key["include_dax"]
    assert "has invalid value true, using 10" in by_key["watch_debounce"]


def test_reset_after_hash_update_writes_empty_hashes(cfg_file):
    loaded = config.load()
    loaded["file_hashes"]["Sales"] = "abc"
    assert config.DEFAULTS["file_hashes"] == {}
    assert config.reset() is True
    saved = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert saved["file_hashes"] == {}
    assert config.DEFAULTS["file_hashes"] == {}


def test_write_atomic_leaves_no_temp_file(tmp_path):
    path = tmp_path / "config.json"
    assert config.write_atomic(str(path), {"owner": "o"}) is True
    assert json.loads(path.read_text(encoding="utf-8")) == {"owner": "o"}
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_atomic_failure_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"owner": "keep"}', encoding="utf-8")

    def fail(src, dst):
        raise OSError("locked")

    monkeypatch.setattr(config.os, "replace", fail)
    assert config.write_atomic(str(path), {"owner": "new"}) is False
    assert path.read_text(encoding="utf-8") == '{"owner": "keep"}'
    assert list(tmp_path.glob("*.tmp")) == []


def test_config_path_frozen(tmp_path, monkeypatch):
    exe = tmp_path / "dist" / "tmdl-lens.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert config.config_path() == os.path.join(str(tmp_path / "dist"), "config.json")


def test_config_path_source_checkout(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert config.config_path() == os.path.join(REPO_ROOT, "config.json")


def test_config_path_pip_install(pip_layout):
    _, expected = pip_layout
    assert config.config_path() == str(expected)


def test_pip_install_migrates_legacy_file_once(pip_layout):
    package_parent, expected = pip_layout
    legacy = package_parent / "config.json"
    legacy.write_text(json.dumps({"owner": "legacy"}), encoding="utf-8")
    result = config.load_result()
    assert result.error == ""
    assert result.config["owner"] == "legacy"
    assert result.migrated_from == str(legacy)
    assert json.loads(expected.read_text(encoding="utf-8")) == {"owner": "legacy"}
    assert legacy.exists()


def test_pip_install_ignores_legacy_when_new_file_exists(pip_layout):
    package_parent, expected = pip_layout
    (package_parent / "config.json").write_text(json.dumps({"owner": "legacy"}), encoding="utf-8")
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({"owner": "current"}), encoding="utf-8")
    result = config.load_result()
    assert result.config["owner"] == "current"
    assert result.migrated_from == ""


def test_pip_install_unreadable_legacy_does_not_raise(pip_layout):
    package_parent, expected = pip_layout
    legacy = package_parent / "config.json"
    legacy.write_bytes(b"{not json")
    result = config.load_result()
    assert result.error == "missing"
    assert result.config == config.DEFAULTS
    assert not expected.exists()
    assert legacy.read_bytes() == b"{not json"


def test_defaults_match_readme_contract_keys():
    with open(os.path.join(REPO_ROOT, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    block = re.search(r"\*\*`config\.json` keys:\*\*(.+?)\n\n", readme, re.DOTALL)
    assert block is not None
    contract = set(re.findall(r"`([^`]+)`", block.group(1)))
    defaults = {k for k in config.DEFAULTS if k != "features"}
    defaults |= {f"features.{k}" for k in config.DEFAULTS["features"]}
    assert contract == defaults
