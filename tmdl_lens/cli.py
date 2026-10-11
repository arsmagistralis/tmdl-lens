"""
cli.py - Command-line interface for tmdl-lens.

Headless mode: runs the documentation pipeline from the terminal with
no GUI dependencies. Installed as the `tmdl-lens` console command.
"""

import argparse
import json
import os
import sys

from tmdl_lens.config import validate_config
from tmdl_lens.pipeline import Pipeline, PipelineConfig
from tmdl_lens.version import __version__


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmdl-lens",
        description="Generate documentation for Power BI PBIP reports.",
    )
    parser.add_argument(
        "--version", action="version", version=f"tmdl-lens {__version__}"
    )
    parser.add_argument(
        "-r", "--reports-folder", default=None,
        help="root folder containing .pbip reports",
    )
    parser.add_argument(
        "-o", "--output-folder", default=None,
        help="output folder for generated docs",
    )
    parser.add_argument(
        "--format", choices=("html", "md"), default=None,
        help="output format: html or md",
    )
    parser.add_argument(
        "--include-dax", dest="include_dax", action="store_true", default=None,
        help="include DAX expressions",
    )
    parser.add_argument(
        "--no-include-dax", dest="include_dax", action="store_false",
        help="omit DAX expressions",
    )
    parser.add_argument(
        "--overwrite", dest="overwrite", action="store_true", default=None,
        help="overwrite existing output files",
    )
    parser.add_argument(
        "--no-overwrite", dest="overwrite", action="store_false",
        help="skip reports whose output already exists",
    )
    parser.add_argument(
        "--skip-unchanged", dest="skip_unchanged", action="store_true", default=None,
        help="skip reports whose content has not changed since the last run",
    )
    parser.add_argument(
        "--no-skip-unchanged", dest="skip_unchanged", action="store_false",
        help="always regenerate every report",
    )
    parser.add_argument(
        "--owner", default=None, help="documentation metadata: owner",
    )
    parser.add_argument(
        "--team", default=None, help="documentation metadata: team",
    )
    parser.add_argument(
        "--refresh-schedule", default=None,
        help="documentation metadata: refresh schedule",
    )
    parser.add_argument(
        "--config", default=None,
        help="path to config.json to read settings and persist skip_unchanged "
        "hashes (optional; CLI flags override its values)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress progress messages, keep errors and the summary",
    )
    return parser


def _load_settings(path: str) -> tuple[dict, str]:
    """
    Load a config file. Returns (settings, error) where error is "" on
    success, "missing" when the file does not exist, or a reason string
    when the file exists but cannot be used.
    """
    if not os.path.exists(path):
        return {}, "missing"
    try:
        with open(path, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except UnicodeDecodeError as e:
        return {}, f"file is not valid UTF-8: {e}"
    except json.JSONDecodeError as e:
        return {}, f"file is not valid JSON: {e}"
    except OSError as e:
        return {}, f"file cannot be read: {e}"
    if not isinstance(saved, dict):
        return {}, f"expected a JSON object, got {type(saved).__name__}"
    return saved, ""


def _build_config(args, saved: dict) -> PipelineConfig:
    def pick(cli_value, key, fallback):
        return cli_value if cli_value is not None else saved.get(key, fallback)

    return PipelineConfig(
        reports_folder=pick(args.reports_folder, "reports_folder", ""),
        output_folder=pick(args.output_folder, "output_folder", ""),
        include_dax=pick(args.include_dax, "include_dax", True),
        output_format=pick(args.format, "output_format", "html"),
        overwrite=pick(args.overwrite, "overwrite_readme", False),
        skip_unchanged=pick(args.skip_unchanged, "skip_unchanged", False),
        owner=pick(args.owner, "owner", ""),
        team=pick(args.team, "team", ""),
        refresh_schedule=pick(args.refresh_schedule, "refresh_schedule", ""),
    )


def main(argv=None) -> int:
    parser = _make_parser()
    args = parser.parse_args(argv)

    def log(msg: str, level: str = "msg") -> None:
        if args.quiet and level in ("msg", "info"):
            return
        print(msg)

    cfg_path = args.config
    config_loaded = False
    saved = {}
    if cfg_path:
        saved, load_error = _load_settings(cfg_path)
        if load_error == "missing":
            log(
                f"warning: config file not found: {cfg_path} - using defaults "
                "and CLI flags; the file will not be created",
                "warn",
            )
        elif load_error:
            log(f"error: could not load config file {cfg_path}: {load_error}", "err")
            return 2
        else:
            config_loaded = True

    build_source = saved
    if config_loaded:
        cfg_dir = os.path.dirname(os.path.abspath(cfg_path))
        build_source = dict(saved)
        for key in ("reports_folder", "output_folder"):
            value = build_source.get(key)
            if isinstance(value, str) and value and not os.path.isabs(value):
                build_source[key] = os.path.normpath(os.path.join(cfg_dir, value))
    config = _build_config(args, build_source)

    if not config.reports_folder:
        log(
            "error: reports folder is required - use --reports-folder "
            "or set reports_folder in config.json",
            "err",
        )
        return 2

    for warning in validate_config({
        "reports_folder": config.reports_folder,
        "output_folder": config.output_folder,
        "output_format": config.output_format,
    }):
        log(warning, "warn")

    if config.reports_folder and not os.path.isdir(config.reports_folder):
        log(f"error: reports folder does not exist: {config.reports_folder}", "err")
        return 1

    hashes = saved.get("file_hashes", {})
    if not isinstance(hashes, dict):
        hashes = {}

    pipeline = Pipeline(config, saved_hashes=hashes, logger=log)
    result = pipeline.run()

    if result.hashes and cfg_path and config_loaded:
        old_hashes = saved.get("file_hashes")
        if not isinstance(old_hashes, dict):
            old_hashes = {}
        saved["file_hashes"] = {**old_hashes, **result.hashes}
        tmp_path = cfg_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)
            os.replace(tmp_path, cfg_path)
        except OSError:
            log(f"warning: could not save content hashes to {cfg_path}", "warn")
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return 0 if result.error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
