"""Tests for CLI config loading, error handling and write-back."""

import json
import os
import shutil

import pytest

from tmdl_lens.cli import main

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_MODEL_DIR = os.path.join(
    REPO_ROOT, "sample", "tmdl-lens-test-report.SemanticModel"
)


def _make_report(reports_dir, folder, name):
    base = os.path.join(str(reports_dir), folder)
    os.makedirs(base, exist_ok=True)
    shutil.copytree(
        SAMPLE_MODEL_DIR, os.path.join(base, f"{name}.SemanticModel")
    )
    with open(os.path.join(base, f"{name}.pbip"), "w", encoding="utf-8") as f:
        f.write("")
    return os.path.join(base, f"{name}.pbip")


def _write_config(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("content", [
    b'{"owner": "o"',
    b"[]",
    b'\xff\xfe{"owner": "o"}',
])
def test_unreadable_config_errors_and_is_untouched(tmp_path, capsys, content):
    cfg = tmp_path / "config.json"
    cfg.write_bytes(content)
    rc = main(["--config", str(cfg), "--reports-folder", str(tmp_path)])
    assert rc == 2
    assert cfg.read_bytes() == content
    assert str(cfg) in capsys.readouterr().out


def test_missing_config_warns_and_creates_nothing(tmp_path, capsys):
    cfg = tmp_path / "missing.json"
    reports = tmp_path / "reports"
    reports.mkdir()
    rc = main(["--config", str(cfg), "--reports-folder", str(reports)])
    assert rc == 0
    assert not cfg.exists()
    assert str(cfg) in capsys.readouterr().out


def test_write_back_preserves_settings_and_merges_hashes(tmp_path):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    cfg = tmp_path / "config.json"
    _write_config(cfg, {
        "owner": "cfg-owner",
        "team": "cfg-team",
        "output_format": "md",
        "features": {"watcher": True},
        "file_hashes": {"legacy": "abc"},
    })
    rc = main(["--config", str(cfg), "--reports-folder", str(reports)])
    assert rc == 0
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["owner"] == "cfg-owner"
    assert saved["team"] == "cfg-team"
    assert saved["output_format"] == "md"
    assert saved["features"] == {"watcher": True}
    assert saved["file_hashes"]["legacy"] == "abc"
    assert "Sales.pbip" in saved["file_hashes"]


def test_relative_config_paths_resolve_against_config_dir(tmp_path):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"reports_folder": "reports", "output_format": "md"})
    rc = main(["--config", str(cfg)])
    assert rc == 0
    assert (reports / "README.md").exists()
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["reports_folder"] == "reports"


def test_write_back_leaves_no_temp_files(tmp_path):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    cfg = tmp_path / "config.json"
    _write_config(cfg, {})
    rc = main(["--config", str(cfg), "--reports-folder", str(reports)])
    assert rc == 0
    json.loads(cfg.read_text(encoding="utf-8"))
    assert list(tmp_path.glob("*.tmp")) == []


def test_bom_config_is_read(tmp_path):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    cfg = tmp_path / "config.json"
    cfg.write_bytes(b'\xef\xbb\xbf{"output_format": "md"}')
    rc = main(["--config", str(cfg), "--reports-folder", str(reports)])
    assert rc == 0
    assert (reports / "README.md").exists()


def test_wrong_typed_value_is_warned_replaced_and_kept_in_file(tmp_path, capsys):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"output_format": "md", "include_dax": "yes", "skip_unchanged": "no"})
    rc = main(["--config", str(cfg), "--reports-folder", str(reports)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "config key 'include_dax' has invalid value \"yes\", using true" in out
    assert "config key 'skip_unchanged' has invalid value \"no\", using false" in out
    assert (reports / "README.md").exists()
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["include_dax"] == "yes"
    assert "Sales.pbip" in saved["file_hashes"]


def test_txt_format_writes_one_lf_file_per_report(tmp_path):
    reports = tmp_path / "reports"
    _make_report(reports, "a", "Sales")
    _make_report(reports, "b", "Finance")
    out = tmp_path / "out"
    rc = main(["--reports-folder", str(reports), "--output-folder", str(out), "--format", "txt"])
    assert rc == 0
    for name in ("Sales", "Finance"):
        data = (out / name / f"{name}.txt").read_bytes()
        assert b"\r" not in data
        assert data.startswith(f"{name}\n".encode("utf-8"))
    assert sorted(p.name for p in out.rglob("*") if p.is_file()) == ["Finance.txt", "Sales.txt"]
