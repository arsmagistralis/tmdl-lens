"""Golden-file tests: both renderers compared byte for byte with reference output."""

import os
import re

import pytest

from tmdl_lens.json_writer import generate_json
from tmdl_lens.readme_generator import _SECTIONS, generate_html, generate_readme, generate_text
from tmdl_lens.source_resolver import resolve_sources
from tmdl_lens.tmdl_parser import (
    Column,
    Measure,
    MParameter,
    Relationship,
    SemanticModel,
    SourceExpression,
    Table,
    parse_semantic_model,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_DIR = os.path.join(REPO_ROOT, "tests", "golden")
SAMPLE_NAME = "tmdl-lens-test-report"
SAMPLE_MODEL_DIR = os.path.join(REPO_ROOT, "sample", f"{SAMPLE_NAME}.SemanticModel")
UPDATE = os.environ.get("TMDL_LENS_UPDATE_GOLDEN") == "1"

GOLDEN_FILES = {
    ("full", "md"): os.path.join(REPO_ROOT, "sample", "README.md"),
    ("full", "html"): os.path.join(GOLDEN_DIR, "sample-full.html"),
    ("nodax", "md"): os.path.join(GOLDEN_DIR, "sample-nodax.md"),
    ("nodax", "html"): os.path.join(GOLDEN_DIR, "sample-nodax.html"),
    ("empty", "md"): os.path.join(GOLDEN_DIR, "empty.md"),
    ("empty", "html"): os.path.join(GOLDEN_DIR, "empty.html"),
    ("edge", "md"): os.path.join(GOLDEN_DIR, "edge.md"),
    ("edge", "html"): os.path.join(GOLDEN_DIR, "edge.html"),
    ("full", "txt"): os.path.join(GOLDEN_DIR, "sample-full.txt"),
    ("nodax", "txt"): os.path.join(GOLDEN_DIR, "sample-nodax.txt"),
    ("empty", "txt"): os.path.join(GOLDEN_DIR, "empty.txt"),
    ("edge", "txt"): os.path.join(GOLDEN_DIR, "edge.txt"),
    ("full", "json"): os.path.join(GOLDEN_DIR, "sample-full.json"),
    ("nodax", "json"): os.path.join(GOLDEN_DIR, "sample-nodax.json"),
    ("empty", "json"): os.path.join(GOLDEN_DIR, "empty.json"),
    ("edge", "json"): os.path.join(GOLDEN_DIR, "edge.json"),
}

RENDERERS = {"md": generate_readme, "html": generate_html, "txt": generate_text, "json": generate_json}

SECTION_TITLES = [title for _, title in _SECTIONS]
CASES_WITH_UNRESOLVED = {"full", "nodax"}


def _gen_config(report_name, include_dax, metadata):
    return {
        "report_name": report_name,
        "owner": "Report Owner" if metadata else "",
        "team": "BI Team" if metadata else "",
        "refresh_schedule": "Daily at 06:00 UTC" if metadata else "",
        "include_dax": include_dax,
    }


def _sample():
    model = parse_semantic_model(SAMPLE_MODEL_DIR, SAMPLE_NAME)
    resolved = resolve_sources(model.source_expressions, model.m_parameters, tables=model.tables)
    return model, resolved


def _edge():
    sales_source = SourceExpression(
        name="sales-source",
        source_type="connector",
        connector_namespace="Web",
        connector_function="Contents",
        url="https://example.com/api/sales",
    )
    sales = Table(
        name="Sales",
        table_type="fact",
        partition_type="m",
        source_ref="sales-source",
        columns=[
            Column(name="Key", data_type="int64", is_key=True, summarize_by="none"),
            Column(name="Date", data_type="dateTime", format_string="yyyy-mm-dd"),
            Column(name="Amount", data_type="decimal", format_string="#,0.00"),
        ],
        measures=[
            Measure(name="Margin", dax_expression="SUM(Sales[Amount]) * 0.1",
                    display_folder="Finance\\Margins", format_string="0.0%"),
            Measure(name="Units", dax_expression="COUNTROWS(Sales)", display_folder="Volume"),
            Measure(name="Plain", dax_expression="1"),
        ],
    )
    hidden_lookup = Table(
        name="Lookup",
        table_type="dim",
        partition_type="m",
        is_hidden=True,
        inline_source=SourceExpression(
            name="Lookup",
            source_type="connector",
            connector_namespace="Sql",
            connector_function="Database",
            server="srv",
            database="db",
        ),
        columns=[Column(name="Key", data_type="int64")],
    )
    auto_date = Table(
        name="LocalDateTable_0001",
        table_type="other",
        partition_type="calculated",
        is_hidden=True,
        columns=[Column(name="Date", data_type="dateTime")],
    )
    model = SemanticModel(
        report_name="edge",
        tables=[sales, hidden_lookup, auto_date],
        relationships=[
            Relationship(from_table="Sales", from_column="Key", to_table="Lookup",
                         to_column="Key", cardinality="manyToOne"),
            Relationship(from_table="Sales", from_column="Date",
                         to_table="LocalDateTable_0001", to_column="Date"),
        ],
        source_expressions=[sales_source],
        m_parameters=[
            MParameter(name="BlankParam", value=""),
            MParameter(name="Region", value="EU"),
        ],
    )
    resolved = resolve_sources(model.source_expressions, model.m_parameters, tables=model.tables)
    return model, resolved


def _render(case, fmt):
    if case == "full":
        model, resolved = _sample()
        config = _gen_config(SAMPLE_NAME, include_dax=True, metadata=True)
    elif case == "nodax":
        model, resolved = _sample()
        config = _gen_config(SAMPLE_NAME, include_dax=False, metadata=False)
    elif case == "empty":
        model, resolved = SemanticModel(report_name="empty"), {}
        config = _gen_config("empty", include_dax=True, metadata=False)
    else:
        model, resolved = _edge()
        config = _gen_config("edge", include_dax=True, metadata=False)
    return RENDERERS[fmt](model, resolved, config)


@pytest.mark.parametrize("case, fmt", sorted(GOLDEN_FILES))
def test_renderer_matches_golden(case, fmt):
    path = GOLDEN_FILES[(case, fmt)]
    output = _render(case, fmt)
    if UPDATE:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(output)
        pytest.skip(f"golden updated: {os.path.relpath(path, REPO_ROOT)}")
    with open(path, "r", encoding="utf-8") as f:
        expected = f.read()
    assert output == expected


@pytest.mark.parametrize("case", ["full", "nodax", "empty", "edge"])
def test_both_renderers_emit_the_section_titles_in_order(case):
    expected = [
        title for title in SECTION_TITLES
        if title != "Unresolved Sources" or case in CASES_WITH_UNRESOLVED
    ]
    md_titles = [
        re.sub(r"^⚠ ", "", t)
        for t in re.findall(r"^## (.+)$", _render(case, "md"), re.MULTILINE)
    ]
    html_titles = [
        re.sub(r"^&#9888; ", "", t)
        for t in re.findall(r"<h2[^>]*>(.*?)</h2>", _render(case, "html"))
    ]
    text_lines = _render(case, "txt").split("\n")
    text_titles = [
        re.sub(r"^! ", "", line)
        for line, below in zip(text_lines, text_lines[1:])
        if line and below == "-" * len(line)
    ]
    assert md_titles == expected
    assert html_titles == expected
    assert text_titles == expected


@pytest.mark.parametrize("case", ["full", "nodax", "empty", "edge"])
def test_markdown_contents_match_rendered_headings_and_anchors(case):
    md = _render(case, "md")
    contents = md.split("**Contents**", 1)[1].split("\n---\n", 1)[0]
    entries = re.findall(r"^- \[(.+?)\]\(#([a-z-]+)\)$", contents, re.MULTILINE)
    anchored = re.findall(r'^<a id="([a-z-]+)"></a>\n## (.+)$', md, re.MULTILINE)
    headings = re.findall(r"^## (.+)$", md, re.MULTILINE)
    assert entries
    assert [label for label, _ in entries] == headings
    assert [(target, label) for label, target in entries] == anchored


@pytest.mark.parametrize("case", ["full", "nodax", "empty", "edge"])
def test_html_contents_match_rendered_headings_and_ids(case):
    html = _render(case, "html")
    nav = re.search(r'<nav class="toc">(.*?)</nav>', html).group(1)
    entries = re.findall(r'<li><a href="#([a-z-]+)">(.*?)</a></li>', nav)
    headings = re.findall(r'<h2 id="([a-z-]+)">(.*?)</h2>', html)
    assert entries
    assert entries == headings
    assert len(re.findall(r"<h2[^>]*>", html)) == len(headings)


@pytest.mark.parametrize("case", ["full", "nodax", "empty", "edge"])
def test_text_output_is_plain(case):
    text = _render(case, "txt")
    assert text.endswith("\n")
    assert "\r" not in text
    assert "⚠" not in text
    for line in text.split("\n"):
        assert line == line.rstrip()
    assert "```" not in text
    assert "**" not in text
    assert "<" + "code>" not in text
    assert "| ---" not in text and "|---|" not in text


def test_text_is_deterministic():
    assert _render("full", "txt") == _render("full", "txt")
