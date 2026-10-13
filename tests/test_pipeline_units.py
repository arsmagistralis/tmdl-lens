"""Fragment-level tests for the pipeline helper functions."""

import builtins
import json
import os
import shutil

from tmdl_lens import pipeline as pipeline_mod
from tmdl_lens.pipeline import (
    Pipeline,
    PipelineConfig,
    _build_gen_config,
    _content_hash,
    _detect_multi_pbip_folders,
    _find_pbip_files,
    _get_output_path,
)

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


def _noop_logger(msg, level):
    pass


def test_find_pbip_files_recursive(tmp_path):
    (tmp_path / "A.pbip").write_text("", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "B.pbip").write_text("", encoding="utf-8")
    (sub / "not.txt").write_text("", encoding="utf-8")
    files = _find_pbip_files(str(tmp_path))
    assert len(files) == 2
    assert all(f.endswith(".pbip") for f in files)


def test_find_pbip_files_empty(tmp_path):
    assert _find_pbip_files(str(tmp_path)) == []


def test_detect_multi_pbip_folders():
    one = os.path.join("a", "one.pbip")
    two = os.path.join("a", "two.pbip")
    three = os.path.join("b", "three.pbip")
    skipped, runnable = _detect_multi_pbip_folders([one, two, three])
    assert skipped == {os.path.dirname(one)}
    assert runnable == [three]


def test_detect_multi_pbip_folders_all_unique():
    files = [os.path.join("a", "one.pbip"), os.path.join("b", "two.pbip")]
    skipped, runnable = _detect_multi_pbip_folders(files)
    assert skipped == set()
    assert runnable == files


def test_get_output_path_md_next_to_pbip():
    assert _get_output_path("rep", "Sales", "md", "") == os.path.join("rep", "README.md")


def test_get_output_path_html_custom_folder():
    assert _get_output_path("rep", "Sales", "html", "docs") == os.path.join("docs", "Sales", "Sales.html")


def test_build_gen_config():
    cfg = PipelineConfig(
        reports_folder="x", owner="O", team="T", refresh_schedule="R", include_dax=False
    )
    gen = _build_gen_config("Sales", cfg)
    assert gen == {
        "report_name":      "Sales",
        "owner":            "O",
        "team":             "T",
        "refresh_schedule": "R",
        "include_dax":      False,
        "include_lineage":  False,
    }


def test_content_hash_deterministic(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (model / "a.tmdl").write_text("A", encoding="utf-8")
    (model / "b.tmdl").write_text("B", encoding="utf-8")
    cfg = PipelineConfig(reports_folder="")
    out = str(tmp_path / "Sales.html")
    h1 = _content_hash(str(model), cfg, out)
    h2 = _content_hash(str(model), cfg, out)
    assert h1 == h2
    assert len(h1) == 64


def test_content_hash_changes_with_content(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (model / "a.tmdl").write_text("A", encoding="utf-8")
    cfg = PipelineConfig(reports_folder="")
    out = str(tmp_path / "Sales.html")
    before = _content_hash(str(model), cfg, out)
    (model / "a.tmdl").write_text("B", encoding="utf-8")
    after = _content_hash(str(model), cfg, out)
    assert before != after


def test_content_hash_changes_with_config(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (model / "a.tmdl").write_text("A", encoding="utf-8")
    c1 = PipelineConfig(reports_folder="", include_dax=True)
    c2 = PipelineConfig(reports_folder="", include_dax=False)
    assert _content_hash(str(model), c1, "out") != _content_hash(str(model), c2, "out")


def test_content_hash_changes_with_output_path(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (model / "a.tmdl").write_text("A", encoding="utf-8")
    cfg = PipelineConfig(reports_folder="")
    assert _content_hash(str(model), cfg, "out1/x.html") != \
        _content_hash(str(model), cfg, "out2/x.html")


def test_content_hash_changes_with_version(tmp_path, monkeypatch):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (model / "a.tmdl").write_text("A", encoding="utf-8")
    cfg = PipelineConfig(reports_folder="")
    before = _content_hash(str(model), cfg, "out/x.html")
    monkeypatch.setattr(pipeline_mod, "__version__", "0.0.0-test")
    after = _content_hash(str(model), cfg, "out/x.html")
    assert before != after


def test_changed_hash_regenerates_despite_no_overwrite(tmp_path):
    pbip = _make_report(tmp_path, "r1", "Sales")
    out_path = os.path.join(str(tmp_path), "r1", "Sales.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("stale")
    cfg = PipelineConfig(
        reports_folder=str(tmp_path), skip_unchanged=True, overwrite=False
    )
    pipeline = Pipeline(
        cfg, saved_hashes={"r1/Sales.pbip": "deadbeef"}, logger=_noop_logger
    )
    single = pipeline.run_single(pbip)
    assert single.success
    assert not single.skipped


def test_hash_stored_when_skip_disabled_then_used(tmp_path):
    pbip = _make_report(tmp_path, "r1", "Sales")
    off = PipelineConfig(
        reports_folder=str(tmp_path), skip_unchanged=False, overwrite=True
    )
    first = Pipeline(off, logger=_noop_logger).run_single(pbip)
    assert first.success
    assert first.content_hash
    assert first.hash_key == "r1/Sales.pbip"
    on = PipelineConfig(
        reports_folder=str(tmp_path), skip_unchanged=True, overwrite=False
    )
    second = Pipeline(
        on, saved_hashes={first.hash_key: first.content_hash}, logger=_noop_logger
    ).run_single(pbip)
    assert second.skipped
    assert second.skip_reason == "unchanged"


def test_same_named_reports_get_distinct_hash_keys(tmp_path):
    _make_report(tmp_path, "r1", "Sales")
    _make_report(tmp_path, "r2", "Sales")
    cfg = PipelineConfig(reports_folder=str(tmp_path), overwrite=True)
    result = Pipeline(cfg, logger=_noop_logger).run()
    assert result.error_count == 0
    assert set(result.hashes) == {"r1/Sales.pbip", "r2/Sales.pbip"}
    assert os.path.exists(os.path.join(str(tmp_path), "r1", "Sales.html"))
    assert os.path.exists(os.path.join(str(tmp_path), "r2", "Sales.html"))


def test_same_named_reports_collide_in_custom_output(tmp_path):
    _make_report(tmp_path, "r1", "Sales")
    _make_report(tmp_path, "r2", "Sales")
    out = str(tmp_path / "docs")
    cfg = PipelineConfig(
        reports_folder=str(tmp_path), output_folder=out, overwrite=True
    )
    messages = []
    result = Pipeline(cfg, logger=lambda m, l: messages.append(m)).run()
    assert result.error_count == 2
    assert result.success_count == 0
    assert not os.path.exists(out) or os.listdir(out) == []
    assert len([m for m in messages if "collision" in m and "Sales" in m]) == 2


def test_unreadable_tmdl_errors_one_report_run_continues(tmp_path, monkeypatch):
    _make_report(tmp_path, "r1", "Alpha")
    _make_report(tmp_path, "r2", "Beta")
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if "Alpha" in str(file) and str(file).endswith(".tmdl") and "r" in mode:
            raise PermissionError(13, "simulated lock", str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    cfg = PipelineConfig(reports_folder=str(tmp_path), overwrite=True)
    result = Pipeline(cfg, logger=_noop_logger).run()
    assert result.error_count == 1
    assert result.success_count == 1
    assert list(result.hashes) == ["r2/Beta.pbip"]


def test_three_runs_only_edited_report_regenerates(tmp_path):
    _make_report(tmp_path, "r1", "Alpha")
    _make_report(tmp_path, "r2", "Beta")
    cfg = PipelineConfig(
        reports_folder=str(tmp_path), skip_unchanged=True, overwrite=False
    )

    run1 = Pipeline(cfg, logger=_noop_logger).run()
    assert run1.success_count == 2
    assert run1.error_count == 0

    run2 = Pipeline(cfg, saved_hashes=dict(run1.hashes), logger=_noop_logger).run()
    assert run2.skipped_count == 2
    assert all(r.skip_reason == "unchanged" for r in run2.results)

    model_file = os.path.join(
        str(tmp_path), "r1", "Alpha.SemanticModel", "definition", "model.tmdl"
    )
    with open(model_file, "a", encoding="utf-8") as f:
        f.write("\n// trigger change\n")

    run3 = Pipeline(cfg, saved_hashes=dict(run1.hashes), logger=_noop_logger).run()
    assert run3.success_count == 1
    assert run3.skipped_count == 1
    by_name = {r.report_name: r for r in run3.results}
    assert by_name["Alpha"].success
    assert by_name["Beta"].skipped
    assert by_name["Beta"].skip_reason == "unchanged"


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _make_project(base, pbip_name, report_folder, reference):
    pbip = os.path.join(str(base), f"{pbip_name}.pbip")
    _write_json(pbip, {
        "version": "1.0",
        "artifacts": [{"report": {"path": report_folder}}],
        "settings": {},
    })
    _write_json(
        os.path.join(str(base), report_folder, "definition.pbir"),
        {"version": "4.0", "datasetReference": reference},
    )
    return pbip


def _recording_logger():
    lines = []
    return lines, lambda msg, level: lines.append(msg)


def _run_one(tmp_path, pbip, **overrides):
    lines, logger = _recording_logger()
    cfg = PipelineConfig(reports_folder=str(tmp_path), **overrides)
    return Pipeline(cfg, logger=logger).run_single(pbip), lines


def test_renamed_pbip_uses_definition_pbir(tmp_path):
    shutil.copytree(SAMPLE_MODEL_DIR, str(tmp_path / "A.SemanticModel"))
    pbip = _make_project(tmp_path, "Renamed", "A.Report", {"byPath": {"path": "../A.SemanticModel"}})
    single, lines = _run_one(tmp_path, pbip)
    assert single.success
    assert single.table_count > 0
    assert single.report_name == "Renamed"
    assert single.output_path == os.path.join(str(tmp_path), "Renamed.html")
    assert "  model: A.SemanticModel (definition.pbir)" in lines


def test_by_path_to_differently_named_folder(tmp_path):
    shutil.copytree(SAMPLE_MODEL_DIR, str(tmp_path / "Shared.SemanticModel"))
    pbip = _make_project(tmp_path, "Sales", "Other.Report", {"byPath": {"path": "../Shared.SemanticModel"}})
    single, _ = _run_one(tmp_path, pbip)
    assert single.success
    assert single.table_count > 0


def test_empty_pbip_falls_back_to_name_guess_silently(tmp_path):
    pbip = _make_report(tmp_path, "r1", "Sales")
    single, lines = _run_one(tmp_path, pbip)
    assert single.success
    assert not any(line.startswith("  model:") for line in lines)


def test_model_bim_is_skipped_and_existing_output_is_untouched(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (model / "model.bim").write_text("{}", encoding="utf-8")
    pbip = tmp_path / "Sales.pbip"
    pbip.write_text("", encoding="utf-8")
    out = tmp_path / "Sales.html"
    out.write_bytes(b"good output")
    for overrides in ({"overwrite": True}, {"skip_unchanged": True}, {}):
        single, lines = _run_one(tmp_path, str(pbip), **overrides)
        assert single.skipped
        assert "model.bim" in single.skip_reason
        assert not single.content_hash
        assert out.read_bytes() == b"good output"
        assert lines == [f"Sales - skipped: {single.skip_reason}"]


def test_model_without_definition_or_bim_is_skipped(tmp_path):
    (tmp_path / "Sales.SemanticModel").mkdir()
    pbip = tmp_path / "Sales.pbip"
    pbip.write_text("", encoding="utf-8")
    single, _ = _run_one(tmp_path, str(pbip))
    assert single.skipped
    assert single.skip_reason == "no definition folder"


def test_missing_model_folder_is_skipped(tmp_path):
    pbip = tmp_path / "Sales.pbip"
    pbip.write_text("", encoding="utf-8")
    single, _ = _run_one(tmp_path, str(pbip))
    assert single.skipped
    assert single.skip_reason == "no semantic model folder"


def test_by_connection_is_skipped_without_name_guess(tmp_path):
    shutil.copytree(SAMPLE_MODEL_DIR, str(tmp_path / "Sales.SemanticModel"))
    pbip = _make_project(
        tmp_path, "Sales", "Sales.Report",
        {"byConnection": {"connectionString": "semanticmodelid=00000000-0000-0000-0000-000000000000"}},
    )
    single, _ = _run_one(tmp_path, pbip)
    assert single.skipped
    assert single.skip_reason == "report uses a live connection (byConnection), no local semantic model"


def test_broken_by_path_is_skipped_without_name_guess(tmp_path):
    shutil.copytree(SAMPLE_MODEL_DIR, str(tmp_path / "Sales.SemanticModel"))
    pbip = _make_project(tmp_path, "Sales", "Sales.Report", {"byPath": {"path": "../Gone.SemanticModel"}})
    single, _ = _run_one(tmp_path, pbip)
    assert single.skipped
    assert single.skip_reason == "definition.pbir points to a missing folder: ../Gone.SemanticModel"


def test_skipped_model_adds_no_hash_and_counts_as_skipped(tmp_path):
    folder = tmp_path / "r1"
    model = folder / "Sales.SemanticModel"
    model.mkdir(parents=True)
    (model / "model.bim").write_text("{}", encoding="utf-8")
    (folder / "Sales.pbip").write_text("", encoding="utf-8")
    cfg = PipelineConfig(reports_folder=str(tmp_path), skip_unchanged=True)
    result = Pipeline(cfg, logger=_noop_logger).run()
    assert result.hashes == {}
    assert result.skipped_count == 1
    assert result.success_count == 0
    assert result.error_count == 0


def test_content_hash_changes_with_include_lineage(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (model / "a.tmdl").write_text("A", encoding="utf-8")
    off = PipelineConfig(reports_folder="", include_lineage=False)
    on = PipelineConfig(reports_folder="", include_lineage=True)
    assert _content_hash(str(model), off, "out") != _content_hash(str(model), on, "out")


def test_lineage_warning_only_for_non_markdown_formats(tmp_path):
    _make_report(tmp_path, "r1", "Sales")
    message = "warning: the lineage diagram is only added to Markdown output"
    for output_format, expected in (("md", 0), ("html", 1), ("txt", 1), ("json", 1)):
        lines, logger = _recording_logger()
        cfg = PipelineConfig(reports_folder=str(tmp_path), output_format=output_format,
                             include_lineage=True, overwrite=True)
        Pipeline(cfg, logger=logger).run()
        assert lines.count(message) == expected, output_format
    lines, logger = _recording_logger()
    Pipeline(PipelineConfig(reports_folder=str(tmp_path), output_format="html", overwrite=True), logger=logger).run()
    assert message not in lines
