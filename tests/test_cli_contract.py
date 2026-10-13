"""
test_cli_contract.py - guards the public CLI and config.json contract.

The items asserted here are the public API of tmdl-lens (frozen from
version 1.0.0) and are documented in the README section
"Compatibility & Public API". Renaming or removing a flag, an exit code or
a config.json key is a breaking change - this file exists so an accidental
change fails CI instead of silently breaking users.
"""

import pytest

from tmdl_lens import config as config_mod
from tmdl_lens.cli import _build_config, _make_parser, main

STABLE_LONG_FLAGS = {
    "--version",
    "--reports-folder",
    "--output-folder",
    "--format",
    "--include-dax",
    "--no-include-dax",
    "--overwrite",
    "--no-overwrite",
    "--skip-unchanged",
    "--no-skip-unchanged",
    "--owner",
    "--team",
    "--refresh-schedule",
    "--config",
    "--quiet",
}

STABLE_SHORT_FLAGS = {"-r", "-o", "-q"}

STABLE_CONFIG_KEYS = {
    "reports_folder",
    "output_folder",
    "output_format",
    "overwrite_readme",
    "include_dax",
    "skip_unchanged",
    "watch_debounce",
    "owner",
    "team",
    "refresh_schedule",
    "file_hashes",
    "features",
}


def _parser_flags():
    parser = _make_parser()
    flags = set()
    for action in parser._actions:
        flags.update(action.option_strings)
    return flags


def test_cli_exposes_all_contract_flags():
    flags = _parser_flags()
    assert STABLE_LONG_FLAGS <= flags
    assert STABLE_SHORT_FLAGS <= flags


STABLE_FORMATS = {"html", "md", "txt"}


def test_cli_format_accepts_all_contract_values():
    parser = _make_parser()
    action = next(a for a in parser._actions if "--format" in a.option_strings)
    assert STABLE_FORMATS <= set(action.choices)
    for value in STABLE_FORMATS:
        assert parser.parse_args(["--format", value]).format == value


def test_cli_rejects_unknown_format_with_exit_2():
    with pytest.raises(SystemExit) as exc:
        _make_parser().parse_args(["--format", "pdf"])
    assert exc.value.code == 2


def test_cli_exit_2_without_reports_folder():
    assert main([]) == 2


def test_cli_exit_1_when_reports_folder_missing(tmp_path):
    missing = str(tmp_path / "does-not-exist")
    assert main(["--reports-folder", missing]) == 1


def test_config_defaults_cover_contract_keys():
    assert STABLE_CONFIG_KEYS <= set(config_mod.DEFAULTS)


def test_build_config_maps_config_keys():
    saved = {
        "reports_folder": "cfg-reports",
        "output_folder": "cfg-out",
        "output_format": "md",
        "overwrite_readme": True,
        "include_dax": False,
        "skip_unchanged": True,
        "owner": "cfg-owner",
        "team": "cfg-team",
        "refresh_schedule": "cfg-schedule",
    }
    cfg = _build_config(_make_parser().parse_args([]), saved)
    assert cfg.reports_folder == "cfg-reports"
    assert cfg.output_folder == "cfg-out"
    assert cfg.output_format == "md"
    assert cfg.overwrite is True
    assert cfg.include_dax is False
    assert cfg.skip_unchanged is True
    assert cfg.owner == "cfg-owner"
    assert cfg.team == "cfg-team"
    assert cfg.refresh_schedule == "cfg-schedule"
