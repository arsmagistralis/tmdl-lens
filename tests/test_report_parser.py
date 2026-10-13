"""Tests for the read-only PBIR report-layer parser (stage A)."""

import os
import shutil
import subprocess
import sys

from tmdl_lens.report_parser import (
    FieldRef,
    FieldUsage,
    ReportLayer,
    parse_report_layer,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "report", "Example.Report")


def _col(table, name):
    return FieldRef(table=table, name=name, kind="column")


def _measure(table, name):
    return FieldRef(table=table, name=name, kind="measure")


def _layer():
    return parse_report_layer(FIXTURE)


def _page(layer, name):
    return next(p for p in layer.pages if p.name == name)


def _visual(page, name):
    return next(v for v in page.visuals if v.name == name)


def test_pages_follow_pages_json_order_and_visibility():
    layer = _layer()
    assert [(p.name, p.display_name, p.is_hidden) for p in layer.pages] == [
        ("p-overview", "Overview", False),
        ("p-details", "Details", True),
    ]


def test_visuals_are_sorted_with_group_parent_and_hidden_flags():
    overview = _page(_layer(), "p-overview")
    assert [(v.name, v.visual_type, v.is_group, v.parent_group, v.is_hidden) for v in overview.visuals] == [
        ("v-card", "card", False, "", False),
        ("v-chart", "clusteredColumnChart", False, "", False),
        ("v-group", "", True, "", False),
        ("v-hidden", "card", False, "", True),
        ("v-slicer", "slicer", False, "", False),
        ("v-table", "tableEx", False, "", False),
        ("v-text", "textbox", False, "v-group", False),
    ]
    assert _visual(overview, "v-group").usages == []
    assert _visual(overview, "v-text").usages == []


def test_projections_sort_and_aggregation():
    chart = _visual(_page(_layer(), "p-overview"), "v-chart")
    assert chart.usages == [
        FieldUsage(_col("Product", "Category"), "projection", "Category"),
        FieldUsage(_col("Sales", "Quantity"), "projection", "Tooltips"),
        FieldUsage(_measure("Sales", "Total Amount"), "projection", "Y"),
        FieldUsage(_measure("Sales", "Total Amount"), "sort", ""),
    ]


def test_hierarchy_level_reference():
    slicer = _visual(_page(_layer(), "p-overview"), "v-slicer")
    assert slicer.usages == [
        FieldUsage(FieldRef("Calendar", "Year", "hierarchy_level", "Calendar Hierarchy"), "projection", "Values"),
    ]


def test_visual_filter_resolves_from_aliases():
    table = _visual(_page(_layer(), "p-overview"), "v-table")
    assert table.usages == [
        FieldUsage(_col("Product", "Name"), "projection", "Values"),
        FieldUsage(_col("Product", "Segment"), "filter", ""),
        FieldUsage(_measure("Sales", "Order Count"), "projection", "Values"),
        FieldUsage(_col("Sales", "Region"), "filter", ""),
    ]


def test_formatting_only_reference_is_recorded_and_visual_calculations_ignored():
    card = _visual(_page(_layer(), "p-overview"), "v-card")
    assert card.usages == [
        FieldUsage(_measure("Sales", "Margin Color"), "formatting", ""),
        FieldUsage(_measure("Sales", "Order Count"), "projection", "Values"),
    ]
    assert not any("v-card" in problem for problem in _layer().problems)


def test_property_variation_source_maps_to_its_column():
    dates = _visual(_page(_layer(), "p-details"), "v-dates")
    assert dates.usages == [
        FieldUsage(_col("Sales", "Order Date"), "projection", "Category"),
        FieldUsage(_measure("Sales", "Total Amount"), "projection", "Y"),
    ]


def test_page_and_report_level_references():
    layer = _layer()
    assert layer.filters == [FieldUsage(_col("Product", "Category"), "filter", "")]
    assert _page(layer, "p-overview").filters == [FieldUsage(_measure("Sales", "Total Amount"), "filter", "")]
    assert _page(layer, "p-details").filters == [FieldUsage(_col("Product", "Name"), "other", "")]


def test_problems_are_collected_without_raising():
    assert _layer().problems == [
        "definition/pages/p-details/visuals/v-dates/visual.json: 1 field reference(s) could not be resolved",
        "definition/pages/p-overview/visuals/v-broken/visual.json: cannot be read (JSONDecodeError)",
    ]


def test_missing_definition_and_legacy_report(tmp_path):
    assert parse_report_layer(str(tmp_path / "Nothing.Report")) == ReportLayer(problems=["no report definition found"])
    legacy = tmp_path / "Legacy.Report"
    legacy.mkdir()
    (legacy / "report.json").write_text("{}", encoding="utf-8")
    assert parse_report_layer(str(legacy)) == ReportLayer(problems=["PBIR-Legacy report.json is not supported"])


def test_non_object_page_is_a_problem(tmp_path):
    report = tmp_path / "Odd.Report"
    page = report / "definition" / "pages" / "p-one"
    page.mkdir(parents=True)
    (page / "page.json").write_text("[]", encoding="utf-8")
    layer = parse_report_layer(str(report))
    assert layer.pages == []
    assert layer.problems == ["definition/pages/p-one/page.json: expected a JSON object"]


def _snapshot(root):
    state = {}
    for folder, _, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            with open(path, "rb") as f:
                state[os.path.relpath(path, root)] = (f.read(), os.stat(path).st_mtime_ns)
    return state


def test_parsing_is_read_only():
    before = _snapshot(FIXTURE)
    _layer()
    assert _snapshot(FIXTURE) == before


def test_parse_is_independent_of_file_write_order(tmp_path):
    copy = tmp_path / "Example.Report"
    files = []
    for folder, _, names in os.walk(FIXTURE):
        for name in names:
            files.append(os.path.relpath(os.path.join(folder, name), FIXTURE))
    for rel in sorted(files, reverse=True):
        target = copy / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(FIXTURE, rel), target)
    assert parse_report_layer(str(copy)) == _layer()
    assert _layer() == _layer()


def test_parser_is_not_imported_by_the_package():
    script = (
        "import sys\n"
        "import tmdl_lens.pipeline, tmdl_lens.cli, tmdl_lens.readme_generator, tmdl_lens.json_writer\n"
        "print('tmdl_lens.report_parser' in sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"
