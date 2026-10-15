"""
test_cli_output.py - console output of the CLI: streams, naming, quiet mode.

Pins bug report L13: per-report lines name the report, warnings and errors
go to stderr, -q hides progress but keeps errors and the summary, the first
run does not warn about the output folder it is about to create, a missing
reports folder is reported once, and the summary counts skipped reports.
"""

import builtins
import os
import shutil

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


def test_quiet_prints_only_the_summary(tmp_path, capsys):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    rc = main(["--reports-folder", str(reports), "-q"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "done - 1 written\n"
    assert captured.err == ""


def test_written_line_names_the_report(tmp_path, capsys):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    rc = main(["--reports-folder", str(reports)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Sales - Sales.html written" in captured.out
    assert "found 1 report(s)" in captured.out


def test_error_line_names_the_report_on_stderr(tmp_path, capsys, monkeypatch):
    _make_report(tmp_path, "r1", "Alpha")
    _make_report(tmp_path, "r2", "Beta")
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if "Alpha" in str(file) and str(file).endswith(".tmdl") and "r" in mode:
            raise PermissionError(13, "simulated lock", str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    rc = main(["--reports-folder", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert any(
        line.startswith("Alpha - error: ") for line in captured.err.splitlines()
    )
    assert "done - 1 written - 1 errors" in captured.err
    assert "Beta - Beta.html written" in captured.out


def test_summary_counts_skipped_reports(tmp_path, capsys):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    assert main(["--reports-folder", str(reports)]) == 0
    capsys.readouterr()
    rc = main(["--reports-folder", str(reports)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Sales - skipped (file exists)" in captured.out
    assert "done - 0 written - 1 skipped" in captured.out


def test_first_run_does_not_warn_about_output_folder(tmp_path, capsys):
    reports = tmp_path / "reports"
    _make_report(reports, "", "Sales")
    out = tmp_path / "docs"
    rc = main(["--reports-folder", str(reports), "--output-folder", str(out)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "output_folder" not in captured.out
    assert "output_folder" not in captured.err
    assert (out / "Sales" / "Sales.html").exists()


def test_missing_reports_folder_reported_once(tmp_path, capsys):
    rc = main(["--reports-folder", str(tmp_path / "absent")])
    captured = capsys.readouterr()
    assert rc == 1
    combined = captured.out + captured.err
    assert combined.count("does not exist") == 1
    assert "does not exist" in captured.err
