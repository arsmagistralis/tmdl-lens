"""Golden-file tests: both renderers compared byte for byte with reference output."""

import os
import re

import pytest

from tmdl_lens.readme_generator import generate_html, generate_readme
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
}

SECTION_TITLES = [
    "Overview",
    "1. Data Sources",
    "2. Table Details",
    "3. Measures",
    "4. Functions",
    "5. Relationships",
    "6. Security Roles",
    "7. M Parameters",
    "Unresolved Sources",
    "8. Model Statistics",
]
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
    renderer = generate_readme if fmt == "md" else generate_html
    return renderer(model, resolved, config)


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
        for t in re.findall(r"<h2>(.*?)</h2>", _render(case, "html"))
    ]
    assert md_titles == expected
    assert html_titles == expected
