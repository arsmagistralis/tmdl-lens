"""
test_readme.py - pytest tests for the Markdown/HTML generators.
"""

import re

from tmdl_lens.readme_generator import (
    _build_function_usage_map,
    _esc,
    _md_cell,
    _md_row,
    generate_html,
    generate_readme,
)
from tmdl_lens.source_resolver import resolve_sources
from tmdl_lens.tmdl_parser import (
    Column,
    Measure,
    Relationship,
    SecurityRole,
    SemanticModel,
    Table,
    TableFilter,
    UserFunction,
    _classify_m_content,
)


def test_readme_title(sample_model, sample_resolved, gen_config):
    readme = generate_readme(sample_model, sample_resolved, gen_config)
    assert readme.startswith("# tmdl-lens Test Report")


def test_readme_sections(sample_model, sample_resolved, gen_config):
    readme = generate_readme(sample_model, sample_resolved, gen_config)
    for heading in [
        "## Overview",
        "## 1. Data Sources",
        "## 2. Table Details",
        "## 3. Measures",
        "## 4. Functions",
        "## 5. Relationships",
        "## 6. Security Roles",
        "## 7. M Parameters",
        "## 8. Model Statistics",
    ]:
        assert heading in readme


def test_readme_functions_section(sample_model, sample_resolved, gen_config):
    readme = generate_readme(sample_model, sample_resolved, gen_config)
    assert "## 4. Functions" in readme
    assert "`AddTax`" in readme
    assert "`SafeStockThreshold`" in readme
    assert "Adds sales tax to a net amount using the given rate." in readme
    assert "Returns the reorder threshold for a product category." in readme
    assert "```dax" in readme
    assert "(amount: number, rate: number) => amount * (1 + rate)" in readme


def test_function_usage_map():
    fn = UserFunction(name="AddTax", expression="x")
    quoted_fn = UserFunction(name="My Func", expression="x")
    other = UserFunction(name="Unused", expression="x")
    measures = [
        Measure(name="Taxed", dax_expression="AddTax([Total], 0.23)"),
        Measure(name="Quoted Call", dax_expression="'My Func'([x]) + AddTax([y], 0.1)"),
        Measure(name="Plain", dax_expression="SUM('fact-sales'[amount])"),
    ]
    table = Table(name="_measures", table_type="measures_only", measures=measures)
    model = SemanticModel(report_name="T", tables=[table], functions=[fn, quoted_fn, other])
    usage = _build_function_usage_map(model)
    assert usage["AddTax"] == [("Taxed", "_measures"), ("Quoted Call", "_measures")]
    assert usage["My Func"] == [("Quoted Call", "_measures")]
    assert "Unused" not in usage


def test_esc_is_idempotent():
    once = _esc("a&b<c>d\"e")
    assert _esc(once) == once


def test_html_escapes_once():
    fn = UserFunction(name="Tax Calc", expression="x", description="R&D <Ops> \"q\"")
    measure = Measure(name="Taxed", dax_expression="AddTax([Total], 0.23)", description="R&D <Ops>")
    table = Table(name="_measures", table_type="measures_only", measures=[measure])
    model = SemanticModel(report_name="T", tables=[table], functions=[fn])
    html = generate_html(model, {}, {"report_name": "T", "include_dax": True})
    assert "R&amp;D &lt;Ops&gt;" in html
    assert "R&amp;amp;D" not in html
    assert "&amp;lt;" not in html
    assert "R&amp;D &lt;Ops&gt; &quot;q&quot;" in html


def test_html_role_dynamic_label_escaped_once():
    role = SecurityRole(
        name="R& D",
        table_filters=[TableFilter(table="t", dax_filter="[a] = \"x\"")],
        is_dynamic=True,
        dynamic_function="USER&NAME",
    )
    model = SemanticModel(report_name="T", tables=[], security_roles=[role])
    html = generate_html(model, {}, {"report_name": "T", "include_dax": True})
    assert "Yes (USER&amp;NAME)" in html
    assert "Yes (USER&amp;amp;NAME)" not in html


def test_md_cell_escapes_pipes_and_newlines():
    assert _md_cell("Net | gross") == "Net \\| gross"
    assert _md_cell("a\r\nb\nc\rd") == "a b c d"
    assert _md_cell("plain") == "plain"
    assert _md_cell(5) == "5"


def test_md_row_joins_escaped_cells():
    assert _md_row("`a`", "b | c", "-") == "| `a` | b \\| c | - |"


def test_readme_escapes_markdown_cells():
    measure = Measure(
        name="Taxed", dax_expression="AddTax([Total], 0.23)", description="Net | gross amount"
    )
    fn = UserFunction(name="Calc", expression="x", description="a | b")
    role = SecurityRole(
        name="Pipe Role",
        table_filters=[TableFilter(table="t", dax_filter="[a] = \"x\" || [b] = \"y\"\n&& [c] = \"z\"")],
    )
    table = Table(name="_measures", table_type="measures_only", measures=[measure])
    model = SemanticModel(report_name="T", tables=[table], functions=[fn], security_roles=[role])
    readme = generate_readme(model, {}, {"report_name": "T", "include_dax": True})
    assert "Net \\| gross amount" in readme
    assert "a \\| b" in readme
    assert '`[a] = "x" \\|\\| [b] = "y" && [c] = "z"`' in readme
    measures_row = next(line for line in readme.split("\n") if line.startswith("| `Taxed`"))
    assert measures_row.count("|") - measures_row.count("\\|") == 5


def test_html_detail_fields_match_markdown(sample_model, gen_config):
    resolved = resolve_sources(
        sample_model.source_expressions, sample_model.m_parameters, tables=sample_model.tables
    )
    html = generate_html(sample_model, resolved, gen_config)
    assert "<strong>Chain:</strong>" in html
    assert "<strong>Server:</strong>" in html
    assert "<strong>Database:</strong>" in html
    assert "<strong>Entity:</strong>" in html
    assert "<strong>Detail:</strong>" not in html
    assert "<code>dbo.orders</code>" in html


def test_sharepoint_contents_detail_fields():
    table = Table(
        name="sp-site",
        table_type="fact",
        partition_type="m",
        inline_source=_classify_m_content(
            'let\n'
            '    Source = SharePoint.Contents("https://contoso.sharepoint.com/sites/examples")\n'
            'in\n'
            '    Source',
            "sp-site",
        ),
    )
    model = SemanticModel(report_name="T", tables=[table])
    resolved = resolve_sources(model.source_expressions, model.m_parameters, tables=model.tables)
    readme = generate_readme(model, resolved, {"report_name": "T", "include_dax": True})
    html = generate_html(model, resolved, {"report_name": "T", "include_dax": True})
    row = next(line for line in readme.split("\n") if line.startswith("| `sp-site`"))
    assert "SharePoint Contents -> https://contoso.sharepoint.com/sites/examples" in row
    assert "**SharePoint URL:** `https://contoso.sharepoint.com/sites/examples`" in readme
    assert "<strong>SharePoint URL:</strong>" in html


def test_measure_inventory_counts_match_measures_section(sample_model, sample_resolved, gen_config):
    readme = generate_readme(sample_model, sample_resolved, gen_config)
    html = generate_html(sample_model, sample_resolved, gen_config)
    assert "**Format Strings Used (7 total, 3 unique)**" in readme
    assert "Measure Format Strings (7 total, 3 unique)" in html
    assert "| Measures | 7 | - |" in readme


def test_hidden_support_table_counted_once():
    hidden_calc = Table(
        name="hidden-calc", table_type="calculated", is_loaded=True, is_hidden=True
    )
    visible = Table(name="fact-sales", table_type="fact", is_loaded=True)
    model = SemanticModel(report_name="T", tables=[visible, hidden_calc])
    readme = generate_readme(model, {}, {"report_name": "T", "include_dax": True})
    html = generate_html(model, {}, {"report_name": "T", "include_dax": True})
    assert "| Hidden Tables | 1 |" in readme
    assert "<td>Hidden Tables</td><td>1</td>" in html


def test_display_folder_backslashes_escaped():
    measure = Measure(
        name="Total", dax_expression="SUM([a])", display_folder="Metrics\\Base"
    )
    table = Table(name="_measures", table_type="measures_only", measures=[measure])
    model = SemanticModel(report_name="T", tables=[table])
    readme = generate_readme(model, {}, {"report_name": "T", "include_dax": True})
    assert "### Metrics\\\\Base" in readme
    assert "### Metrics\\Base" not in readme


def test_auto_date_tables_filtered():
    auto1 = Table(
        name="LocalDateTable_abc", table_type="calculated", is_loaded=True, is_hidden=True,
        columns=[Column(name="Date", data_type="dateTime", format_string="Short Date")],
    )
    auto2 = Table(
        name="DateTableTemplate_def", table_type="calculated", is_loaded=True, is_hidden=True,
        columns=[Column(name="Date", data_type="dateTime", format_string="Short Date")],
    )
    real_calc = Table(
        name="dim-date", table_type="calculated", is_loaded=True,
        columns=[Column(name="Date", data_type="dateTime", format_string="Long Date")],
    )
    real_fact = Table(
        name="fact-sales", table_type="fact", is_loaded=True,
        columns=[Column(name="amount", data_type="double", format_string="#,##0.00")],
    )
    helper = Table(name="helper-x", table_type="helper", is_loaded=True, is_hidden=True)
    rel_to_auto = Relationship(
        from_table="fact-sales", from_column="order_date",
        to_table="LocalDateTable_abc", to_column="Date",
    )
    model = SemanticModel(
        report_name="T",
        tables=[real_fact, real_calc, helper, auto1, auto2],
        relationships=[rel_to_auto],
    )
    readme = generate_readme(model, {}, {"report_name": "T", "include_dax": True})
    html = generate_html(model, {}, {"report_name": "T", "include_dax": True})
    for out in (readme, html):
        assert "LocalDateTable_abc" not in out
        assert "DateTableTemplate_def" not in out
        assert "1 calculated table" in out
        assert "Short Date" not in out
        assert "Long Date" in out
    assert "| Hidden Tables | 1 |" in readme


def test_hidden_loaded_tables_in_data_sources():
    visible = Table(name="fact-sales", table_type="fact", is_loaded=True)
    hidden = Table(name="helper-x", table_type="helper", is_loaded=True, is_hidden=True)
    model = SemanticModel(report_name="T", tables=[visible, hidden])
    readme = generate_readme(model, {}, {"report_name": "T", "include_dax": True})
    html = generate_html(model, {}, {"report_name": "T", "include_dax": True})
    for out in (readme, html):
        assert "2 loaded tables" in out
        assert "(hidden)" in out
    visible_row = next(line for line in readme.split("\n") if line.startswith("| `fact-sales`"))
    assert visible_row == "| `fact-sales` | - | - |"
    hidden_row = next(line for line in readme.split("\n") if line.startswith("| `helper-x`"))
    assert hidden_row == "| `helper-x` (hidden) | - | - |"


def test_table_details_covers_support_tables(sample_model, sample_resolved, gen_config):
    readme = generate_readme(sample_model, sample_resolved, gen_config)
    html = generate_html(sample_model, sample_resolved, gen_config)
    assert "### `dim-date`" in readme
    assert "### `param-metric-selector`" in readme
    assert "CALENDARAUTO" in readme
    assert "Source:** Field Parameter" in readme
    assert "### `_measures`" not in readme
    assert "CALENDARAUTO" in html
    assert "Source:</strong> Field Parameter" in html
    assert "<h3><code>_measures</code></h3>" not in html


def test_readme_unresolved_section(sample_model, sample_resolved, gen_config):
    readme = generate_readme(sample_model, sample_resolved, gen_config)
    assert "## ⚠ Unresolved Sources" in readme
    assert "manual label" not in readme


def test_readme_includes_metadata(sample_model, sample_resolved, gen_config):
    readme = generate_readme(sample_model, sample_resolved, gen_config)
    assert "Report Owner" in readme
    assert "BI Team" in readme
    assert "Daily at 06:00 UTC" in readme


def test_readme_omits_blank_metadata(sample_model, sample_resolved):
    config = {
        "report_name":      "tmdl-lens Test Report",
        "owner":            "",
        "team":             "",
        "refresh_schedule": "",
        "include_dax":      True,
    }
    readme = generate_readme(sample_model, sample_resolved, config)
    assert "Owner" not in readme
    assert "Team" not in readme
    assert "Refresh Schedule" not in readme


def test_readme_dax_optional(sample_model, sample_resolved, gen_config):
    without_dax = generate_readme(
        sample_model, sample_resolved, {**gen_config, "include_dax": False}
    )
    with_dax = generate_readme(sample_model, sample_resolved, gen_config)
    assert len(with_dax) > len(without_dax)


def test_html_generation(sample_model, sample_resolved, gen_config):
    html = generate_html(sample_model, sample_resolved, gen_config)
    assert html.startswith("<!DOCTYPE html>")
    assert "tmdl-lens Test Report" in html
    assert '<h2 id="data-sources">1. Data Sources</h2>' in html
    assert '<h2 id="statistics">8. Model Statistics</h2>' in html


def test_generation_is_deterministic(sample_model, sample_resolved, gen_config):
    first_md = generate_readme(sample_model, sample_resolved, gen_config)
    second_md = generate_readme(sample_model, sample_resolved, gen_config)
    first_html = generate_html(sample_model, sample_resolved, gen_config)
    second_html = generate_html(sample_model, sample_resolved, gen_config)
    assert first_md.encode("utf-8") == second_md.encode("utf-8")
    assert first_html.encode("utf-8") == second_html.encode("utf-8")


def _statistics_counts(markup, html_mode):
    if html_mode:
        stats = markup.split('<h2 id="statistics">', 1)[1]
        loaded = re.search(r"<td>Loaded Tables</td><td>(\d+)</td>", stats)
        columns = re.search(r"<td>Columns</td><td>(\d+)</td>", stats)
        items = re.search(r"<td>Loaded Tables</td><td>\d+</td><td>(.*?)</td></tr>", stats)
        names = re.findall(r"<code>(.*?)</code>", items.group(1))
    else:
        stats = markup.split("## 8. Model Statistics", 1)[1]
        loaded = re.search(r"^\| Loaded Tables \| (\d+) \|", stats, re.MULTILINE)
        columns = re.search(r"^\| Columns \| (\d+) \|", stats, re.MULTILINE)
        items = re.search(r"^\| Loaded Tables \| \d+ \| (.+) \|$", stats, re.MULTILINE)
        names = re.findall(r"`(.*?)`", items.group(1))
    return int(loaded.group(1)), int(columns.group(1)), names


def test_statistics_agrees_with_summary(sample_model, sample_resolved, gen_config):
    summary_loaded = int(
        re.search(r"This model contains (\d+) loaded table", generate_readme(
            sample_model, sample_resolved, gen_config)).group(1)
    )
    tables_by_name = {t.name: t for t in sample_model.tables}
    for markup, html_mode in (
        (generate_readme(sample_model, sample_resolved, gen_config), False),
        (generate_html(sample_model, sample_resolved, gen_config), True),
    ):
        loaded_count, columns_count, item_names = _statistics_counts(markup, html_mode)
        assert loaded_count == summary_loaded
        assert loaded_count == len(item_names)
        assert columns_count == sum(
            len(tables_by_name[name].columns) for name in item_names
        )
