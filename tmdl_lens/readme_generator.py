"""
readme_generator.py - Markdown README generator for tmdl-lens.

Takes a parsed SemanticModel and resolved sources dict and produces
a structured README.md for each Power BI report.
"""

import re
from dataclasses import replace

from tmdl_lens.tmdl_parser import SemanticModel, Table
from tmdl_lens.source_resolver import CONNECTOR_TYPE_LABEL, ResolvedSource, get_table_source


# ---------------------------------------------------------------------------
# Data type display map
# ---------------------------------------------------------------------------

_DTYPE = {
    "string":     "Text",
    "int64":      "Integer",
    "double":     "Decimal",
    "decimal":    "Decimal",
    "dateTime":   "Date/Time",
    "boolean":    "True/False",
    "calculated": "Calculated",
    "unknown":    "-",
}

def _dtype(raw: str) -> str:
    return _DTYPE.get(raw, raw)


# ---------------------------------------------------------------------------
# Source type display map
# ---------------------------------------------------------------------------

_SOURCE_TYPE_LABEL = {
    "hardcoded":     "Hardcoded (Inline M)",
    "embedded":      "Embedded Data",
    "table_combine": "Combined Queries",
    "dynamic":       "Dynamic M",
    "unresolved":    "Unresolved",
    "function_def":  "Helper Function",
    "scalar_helper": "Scalar Helper",
    "generated":     "Generated (M)",
}

def _source_type_label(source_type: str) -> str:
    return _SOURCE_TYPE_LABEL.get(source_type, source_type.replace("_", " ").title())


# Connector type labels: single source of truth is
# source_resolver.CONNECTOR_TYPE_LABEL, imported at the top of this module.

def _connector_type_label(rs: ResolvedSource) -> str:
    """Return a short Source Type display name for a ResolvedSource.
    Uses connector_namespace/connector_function for connectors; falls
    back to _source_type_label for non-connector types."""
    if rs.source_type == "connector":
        key = (rs.connector_namespace, rs.connector_function)
        label = CONNECTOR_TYPE_LABEL.get(key)
        if label:
            return label
        return f"{rs.connector_namespace} {rs.connector_function}"
    return _source_type_label(rs.source_type)


def _source_label(rs: ResolvedSource) -> str:
    """
    Returns the display string for the Source column in the Data Sources table.
    Uses rs.label which already contains the full chain (e.g. 'FVInput -> Smartsheet (US)').
    Falls back to manual_label if set. Returns '-' for scalar/helper types.
    """
    if rs.manual_label:
        return rs.manual_label
    # Non-source types return '-' regardless of unresolved status
    if rs.source_type in ("scalar_helper", "function_def", "embedded", "hardcoded", "dynamic", "generated"):
        return "-"
    if rs.unresolved:
        return rs.unresolved_reason or "Unresolved"
    label = rs.label or "-"
    if rs.source_type == "connector" and rs.connector_namespace in ("PowerBI", "PowerPlatform"):
        if rs.entity:
            if rs.chain:
                return label
            return rs.entity
        return label
    return label


# ---------------------------------------------------------------------------
# Table type display map
# ---------------------------------------------------------------------------

_TABLE_TYPE_LABEL = {
    "calculated":      "Calculated (DAX)",
    "field_parameter": "Field Parameter",
    "measures_only":   "Measures",
    "calc_group":      "Calculation Group",
}

def _table_type_label(table_type: str) -> str:
    return _TABLE_TYPE_LABEL.get(table_type, "Loaded")


# ---------------------------------------------------------------------------
# Auto date table filter
# Power BI auto-generates these hidden tables and their relationships.
# They add noise to the output and are suppressed.
# ---------------------------------------------------------------------------

def _is_auto_date_table(name: str) -> bool:
    return name.startswith("LocalDateTable_") or name.startswith("DateTableTemplate_")


def _collect(model: SemanticModel, show_hidden: bool) -> dict:
    tables = [t for t in model.tables if not _is_auto_date_table(t.name)]
    replaced = replace(model, tables=tables)
    support_types = {"calculated", "field_parameter", "measures_only", "calc_group"}
    loaded = [t for t in tables if t.is_loaded and t.table_type not in support_types]
    support = [t for t in tables if t.is_loaded and t.table_type in support_types]
    staging = [t for t in tables if not t.is_loaded]
    loaded_visible = [t for t in loaded if not t.is_hidden]
    hidden_tables = [t for t in tables if t.is_loaded and t.is_hidden]
    return {
        "model": replaced,
        "tables": tables,
        "loaded": loaded,
        "support": support,
        "staging": staging,
        "loaded_visible": loaded_visible,
        "hidden_tables": hidden_tables,
        "measures": [
            (t.name, m) for t in tables for m in t.measures
            if show_hidden or not m.is_hidden
        ],
        "all_measures": [(t.name, m) for t in tables for m in t.measures],
        "calc_cols": [c for t in tables for c in t.columns if c.is_calculated],
    }


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def _model_summary(
    loaded_tables: list[Table],
    staging_tables: list[Table],
    support_tables: list[Table],
    model: SemanticModel,
) -> str:
    n_loaded   = len(loaded_tables)
    n_staging  = len(staging_tables)
    n_meas     = sum(len(t.measures) for t in model.tables)
    visible_rels = [
        r for r in model.relationships
        if not _is_auto_date_table(r.from_table) and not _is_auto_date_table(r.to_table)
    ]
    n_rels = len(visible_rels)

    parts = [f"{n_loaded} loaded {'table' if n_loaded == 1 else 'tables'}"]
    if support_tables:
        labels = []
        calc   = [t for t in support_tables if t.table_type == "calculated"]
        fp     = [t for t in support_tables if t.table_type == "field_parameter"]
        mo     = [t for t in support_tables if t.table_type == "measures_only"]
        cg     = [t for t in support_tables if t.table_type == "calc_group"]
        if calc: labels.append(f"{len(calc)} calculated {'table' if len(calc) == 1 else 'tables'}")
        if fp:   labels.append(f"{len(fp)} field {'parameter' if len(fp) == 1 else 'parameters'}")
        if mo:   labels.append(f"{len(mo)} measures-only {'table' if len(mo) == 1 else 'tables'}")
        if cg:   labels.append(f"{len(cg)} calculation {'group' if len(cg) == 1 else 'groups'}")
        if labels:
            parts.append(", ".join(labels))
    if n_staging:
        parts.append(f"{n_staging} not loaded")
    parts.append(f"{n_meas} {'measure' if n_meas == 1 else 'measures'}")
    parts.append(f"{n_rels} {'relationship' if n_rels == 1 else 'relationships'}")

    return "This model contains " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _md_cell(value) -> str:
    return (
        str(value)
        .replace("|", "\\|")
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _md_row(*cells) -> str:
    return "| " + " | ".join(_md_cell(c) for c in cells) + " |"


def _overview_section(config: dict, model: SemanticModel) -> str:
    rows = []
    if config.get("owner"):
        rows.append(_md_row("**Owner**", config["owner"]))
    if config.get("team"):
        rows.append(_md_row("**Team**", config["team"]))
    if config.get("refresh_schedule"):
        rows.append(_md_row("**Refresh Schedule**", config["refresh_schedule"]))
    rows.extend([
        _md_row("**Culture**", model.model_culture or "-"),
        _md_row("**Compatibility Level**", model.database_compatibility_level or "-"),
        _md_row("**Data Source Version**", model.model_data_source_version or "-"),
    ])

    lines = [
        "## Overview",
        "",
        "| Property | Value |",
        "|---|---|",
        *rows,
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _data_sources_section(
    loaded_tables: list[Table],
    staging_tables: list[Table],
    support_tables: list[Table],
    resolved: dict[str, ResolvedSource],
    model: SemanticModel,
) -> str:
    lines = ["## 1. Data Sources", ""]
    lines += [_model_summary(loaded_tables, staging_tables, support_tables, model), ""]

    if loaded_tables:
        lines += [
            "| Table | Source Type | Source |",
            "|---|---|---|",
        ]
        for t in loaded_tables:
            rs = get_table_source(t, resolved)
            if rs:
                src_type = _connector_type_label(rs)
                label    = _source_label(rs)
            else:
                src_type = "-"
                label    = "-"
            name_cell = f"`{t.name}` (hidden)" if t.is_hidden else f"`{t.name}`"
            lines.append(_md_row(name_cell, src_type, label))
        lines.append("")
    else:
        lines += ["*No loaded tables found.*", ""]

    if support_tables:
        lines += [
            "### Support Tables",
            "",
            "| Table | Type |",
            "|---|---|",
        ]
        for t in support_tables:
            lines.append(_md_row(f"`{t.name}`", _table_type_label(t.table_type)))
        lines.append("")

    if staging_tables:
        lines += [
            "### Not Loaded",
            "",
            "> These tables have `enableLoad = false` and are not visible in the report.",
            "> They are typically used as intermediate query steps.",
            "",
            "| Table | Source Type | Source |",
            "|---|---|---|",
        ]
        for t in staging_tables:
            rs = get_table_source(t, resolved)
            if rs:
                src_type = _connector_type_label(rs)
                label    = _source_label(rs)
            else:
                src_type = "-"
                label    = "-"
            lines.append(_md_row(f"`{t.name}`", src_type, label))
        lines.append("")
        staging_fmt = _column_format_string_inventory(staging_tables, heading="Not Loaded Table Format Strings Used")
        if staging_fmt:
            lines.append(staging_fmt)
    else:
        lines += ["### Not Loaded", "", "*None.*", ""]

    lines += ["---", ""]
    return "\n".join(lines)


def _source_detail_fields(rs: ResolvedSource) -> list:
    fields = []
    fields.append(("Source", _connector_type_label(rs)))
    if rs.source_type == "connector" and rs.connector_namespace in ("PowerBI", "PowerPlatform") and rs.entity:
        fields.append(("Entity", f"`{rs.entity}`"))
    if rs.source_type == "connector" and rs.connector_namespace in ("Sql", "AzureSQL", "AmazonRedshift") and rs.connector_function == "Database":
        if rs.schema and rs.table_or_view:
            fields.append(("Table", f"`{rs.schema}.{rs.table_or_view}`"))
        if rs.physical_tables:
            if len(rs.physical_tables) == 1:
                ref = rs.physical_tables[0]
                label = f"{ref.schema}.{ref.table}" if ref.schema else ref.table
                suffix = " (native query)" if ref.source == "native_query" else ""
                fields.append(("Physical table", f"`{label}`{suffix}"))
            else:
                parts = []
                for ref in rs.physical_tables:
                    label = f"{ref.schema}.{ref.table}" if ref.schema else ref.table
                    if ref.source == "native_query":
                        label += " (native query)"
                    parts.append(f"`{label}`")
                fields.append(("Physical tables", ", ".join(parts)))
        if rs.server:
            fields.append(("Server", f"`{rs.server}`"))
        if rs.database:
            fields.append(("Database", f"`{rs.database}`"))
    if rs.source_type == "connector" and (
        (rs.connector_namespace in ("Oracle", "MySql", "PostgreSQL", "DB2", "SapHana") and rs.connector_function == "Database")
        or (rs.connector_namespace == "Snowflake" and rs.connector_function == "Databases")
    ):
        if rs.server:
            fields.append(("Server", f"`{rs.server}`"))
        if rs.database:
            fields.append(("Database", f"`{rs.database}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "Teradata" and rs.connector_function == "Database":
        if rs.server:
            fields.append(("Server", f"`{rs.server}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "Databricks" and rs.connector_function in ("Catalogs", "Contents"):
        if rs.server:
            fields.append(("Host", f"`{rs.server}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "Dataverse" and rs.connector_function == "Feed":
        if rs.url:
            fields.append(("Environment URL", f"`{rs.url}`"))
    if rs.source_type == "connector" and (
        (rs.connector_namespace == "AzureDevOps" and rs.connector_function == "Contents")
        or (rs.connector_namespace == "Dynamics365" and rs.connector_function == "FinanceAndOperations")
        or (rs.connector_namespace in ("GoogleSheets", "QuickBooks", "GitHub") and rs.connector_function == "Contents")
    ):
        if rs.url:
            fields.append(("URL", f"`{rs.url}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "Salesforce" and rs.url:
        fields.append(("URL", f"`{rs.url}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "AzureStorage":
        if rs.account:
            fields.append(("Account", f"`{rs.account}`"))
        if rs.container:
            fields.append(("Container", f"`{rs.container}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "Odbc" and rs.connector_function == "DataSource" and rs.dsn:
        fields.append(("DSN", f"`{rs.dsn}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "SharePoint" and rs.connector_function in ("Files", "Tables") and rs.sharepoint_url:
        fields.append(("SharePoint URL", f"`{rs.sharepoint_url}`"))
    if rs.source_type == "connector" and (
        (rs.connector_namespace == "Excel" and rs.connector_function == "Workbook")
        or (rs.connector_namespace == "Csv" and rs.connector_function == "Document")
    ) and rs.file_name:
        fields.append(("File", f"`{rs.file_name}`"))
    if rs.source_type == "connector" and rs.connector_namespace == "Excel" and rs.connector_function == "Workbook" and rs.sheet_name:
        fields.append(("Sheet", f"`{rs.sheet_name}`"))
    if rs.source_type == "connector" and (
        (rs.connector_namespace == "Web" and rs.connector_function == "Contents")
        or (rs.connector_namespace == "OData" and rs.connector_function == "Feed")
    ) and rs.url:
        fields.append(("URL", f"`{rs.url}`"))
    if rs.chain:
        fields.append(("Chain", f"`{rs.label}`"))
    if rs.unresolved:
        fields.append(("⚠ Unresolved", rs.unresolved_reason))
    if rs.physical_tables and not (
        rs.source_type == "connector"
        and rs.connector_namespace in ("Sql", "AzureSQL", "AmazonRedshift")
        and rs.connector_function == "Database"
    ):
        if len(rs.physical_tables) == 1:
            ref = rs.physical_tables[0]
            label = f"{ref.schema}.{ref.table}" if ref.schema else ref.table
            suffix = " (native query)" if ref.source == "native_query" else ""
            fields.append(("Physical table", f"`{label}`{suffix}"))
        else:
            parts = []
            for ref in rs.physical_tables:
                label = f"{ref.schema}.{ref.table}" if ref.schema else ref.table
                if ref.source == "native_query":
                    label += " (native query)"
                parts.append(f"`{label}`")
            fields.append(("Physical tables", ", ".join(parts)))
    return fields


def _table_detail_block(
    table: Table,
    resolved: dict[str, ResolvedSource],
    include_dax: bool,
    tables_by_name: dict | None = None,
    hidden_measures_map: dict | None = None,
    hidden_columns_map: dict | None = None,
    show_hidden: bool = True,
) -> str:
    lines = [f"### `{table.name}`", ""]

    rs = get_table_source(table, resolved)

    if rs:
        for label, value in _source_detail_fields(rs):
            lines.append(f"**{label}:** {value}  ")
    elif table.table_type == "calculated":
        lines.append("**Source:** Calculated (DAX)  ")
        if include_dax and table.dax_partition:
            lines += ["", "```dax", table.dax_partition, "```"]
    elif table.table_type == "field_parameter":
        lines.append("**Source:** Field Parameter  ")
    elif table.table_type == "measures_only":
        lines.append("**Source:** Measures only - no data source  ")

    if not table.is_loaded:
        lines += ["", "> ⚠ Not loaded (`enableLoad = false`)."]

    if table.is_hidden:
        lines += ["**Hidden:** Yes  "]

    lines.append("")

    all_cols = [c for c in table.columns if not c.is_calculated]
    if show_hidden:
        display_cols = all_cols
    else:
        display_cols = [c for c in all_cols if not c.is_hidden]
    if display_cols:
        lines += [
            "**Columns**", "",
            "| Column | Type | Format | Summarize By | Source Column | Sort By | Description | Hidden |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for col in display_cols:
            fmt     = f"`{col.format_string}`" if col.format_string else "-"
            summ    = col.summarize_by or "-"
            src_col = f"`{col.source_column}`" if col.source_column else "-"
            sort_by = f"`{col.sort_by_column}`" if col.sort_by_column else "-"
            desc    = col.description or "-"
            hidden  = "Hidden" if col.is_hidden else ""
            lines.append(
                _md_row(f"`{col.name}`", _dtype(col.data_type), fmt, summ, src_col, sort_by, desc, hidden)
            )
        lines.append("")

        key_cols = [c.name for c in display_cols if c.is_key]
        if key_cols:
            lines += ["**Key Column:** " + ", ".join(f"`{k}`" for k in key_cols) + "  ", ""]

        cat_cols = [(c.name, c.data_category) for c in display_cols if c.data_category]
        if cat_cols:
            parts = [f"`{name}` = {cat}" for name, cat in cat_cols]
            lines += ["**Data Categories:** " + ", ".join(parts) + "  ", ""]

    calc_cols = [c for c in table.columns if c.is_calculated]
    if calc_cols:
        lines += ["**Calculated Columns**", ""]
        for col in calc_cols:
            if include_dax and col.dax_expression:
                lines += [f"- **`{col.name}`**", "  ```dax", f"  {col.dax_expression}", "  ```"]
                if tables_by_name is not None:
                    note = _hidden_reference_note(
                        _find_hidden_references(
                            col.dax_expression, tables_by_name,
                            hidden_measures_map or {}, hidden_columns_map or {}
                        )
                    )
                    if note:
                        lines += ["", f"  {note}"]
            else:
                lines.append(f"- `{col.name}`")
        lines.append("")

    if table.calculation_items:
        lines += ["**Calculation Items**", "", "| Item | Ordinal | Format String |", "|---|---|---|"]
        for item in table.calculation_items:
            fmt = f"`{item.format_string_expression}`" if item.format_string_expression else "-"
            lines.append(_md_row(f"`{item.name}`", item.ordinal, fmt))
        lines.append("")
        lines += [
            "> Calculation items can be applied to any measure at report-build time "
            "(via `SELECTEDMEASURE()`). TMDL has no static record of which measures "
            "a given item is actually used with.",
            "",
        ]
        if include_dax:
            lines += ["**Item DAX**", ""]
            for item in table.calculation_items:
                lines += [f"**`{item.name}`**", "```dax", item.dax_expression, "```", ""]

    if show_hidden:
        display_measures = table.measures[:]
    else:
        display_measures = [m for m in table.measures if not m.is_hidden]

    if display_measures:
        lines += ["**Measures**", "", "| Measure | Format | Description | Hidden |", "|---|---|---|---|"]
        for m in display_measures:
            fmt    = f"`{m.format_string}`" if m.format_string else "-"
            desc   = m.description or "-"
            hidden = "Hidden" if m.is_hidden else ""
            lines.append(_md_row(f"`{m.name}`", fmt, desc, hidden))
        if include_dax:
            lines += ["", "**Measure DAX**", ""]
            for m in display_measures:
                if not m.dax_expression.strip():
                    continue
                lines += [f"**`{m.name}`**", "```dax", m.dax_expression, "```", ""]
                if tables_by_name is not None:
                    note = _hidden_reference_note(
                        _find_hidden_references(
                            m.dax_expression, tables_by_name,
                            hidden_measures_map or {}, hidden_columns_map or {}
                        )
                    )
                    if note:
                        lines += ["", note, ""]

    return "\n".join(lines)


def _table_details_section(
    loaded_tables: list[Table],
    support_tables: list[Table],
    resolved: dict[str, ResolvedSource],
    include_dax: bool,
    tables_by_name: dict | None = None,
    hidden_measures_map: dict | None = None,
    hidden_columns_map: dict | None = None,
    show_hidden: bool = True,
) -> str:
    lines = ["## 2. Table Details", ""]
    detail_support = [
        t for t in support_tables
        if t.table_type in ("calc_group", "calculated", "field_parameter")
    ]
    if show_hidden:
        all_tables = loaded_tables + detail_support
    else:
        all_tables = [t for t in loaded_tables if not t.is_hidden] + detail_support
    if all_tables:
        for t in all_tables:
            lines.append(_table_detail_block(t, resolved, include_dax, tables_by_name, hidden_measures_map, hidden_columns_map, show_hidden))
            lines += ["---", ""]
    else:
        lines += ["*No loaded tables.*", "", "---", ""]
    lines.append(_column_format_string_inventory(loaded_tables + support_tables))
    return "\n".join(lines)


def _column_format_string_inventory(tables: list[Table], heading: str = "Format Strings Used") -> str:
    all_columns = [(t.name, c) for t in tables for c in t.columns]
    if not all_columns:
        return ""

    groups: dict[str, list[tuple[str, str]]] = {}
    for table_name, c in all_columns:
        key = c.format_string.strip() if c.format_string.strip() else "(none)"
        groups.setdefault(key, []).append((c.name, table_name))

    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    total = len(all_columns)
    unique = len(groups)

    lines = [
        "",
        f"**{heading} ({total} total, {unique} unique)**",
        "",
        "| Format String | Count | Columns |",
        "|---|---|---|",
    ]
    for fmt, items in sorted_groups:
        items_str = ", ".join(f"`{name}` ({tbl})" for name, tbl in items)
        fmt_cell = f"`{fmt}`" if fmt != "(none)" else "(none)"
        lines.append(_md_row(fmt_cell, len(items), items_str))
    lines.append("")
    return "\n".join(lines)


def _measure_format_string_inventory(measures: list) -> str:
    if not measures:
        return ""

    groups: dict[str, list[tuple[str, str]]] = {}
    for table_name, m in measures:
        key = m.format_string.strip() if m.format_string.strip() else "(none)"
        groups.setdefault(key, []).append((m.name, table_name))

    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    total = len(measures)
    unique = len(groups)

    lines = [
        "",
        f"**Format Strings Used ({total} total, {unique} unique)**",
        "",
        "| Format String | Count | Measures |",
        "|---|---|---|",
    ]
    for fmt, items in sorted_groups:
        items_str = ", ".join(f"`{name}` ({tbl})" for name, tbl in items)
        fmt_cell = f"`{fmt}`" if fmt != "(none)" else "(none)"
        lines.append(_md_row(fmt_cell, len(items), items_str))
    lines.append("")
    return "\n".join(lines)


def _measures_section(measures: list, include_dax: bool) -> str:
    all_measures = measures
    lines = ["## 3. Measures", ""]

    if not all_measures:
        lines += ["*No measures defined in this model.*", "", "---", ""]
        return "\n".join(lines)

    folders: dict[str, list[tuple]] = {}
    for table_name, m in all_measures:
        folder = m.display_folder or "General"
        folders.setdefault(folder, []).append((table_name, m))

    for folder in sorted(folders.keys()):
        lines += [f"### {folder.replace(chr(92), chr(92) * 2)}", "", "| Measure | Table | Format | Description |", "|---|---|---|---|"]
        for table_name, m in folders[folder]:
            fmt  = f"`{m.format_string}`" if m.format_string else "-"
            desc = m.description or "-"
            lines.append(_md_row(f"`{m.name}`", f"`{table_name}`", fmt, desc))
        lines.append("")
        if include_dax:
            for _, m in folders[folder]:
                if not m.dax_expression.strip():
                    continue
                lines += [f"**`{m.name}`**", "```dax", m.dax_expression, "```", ""]

    lines.append(_measure_format_string_inventory(measures))
    lines += ["---", ""]
    return "\n".join(lines)


def _build_function_usage_map(model: SemanticModel) -> dict:
    usage: dict = {}
    for t in model.tables:
        for m in t.measures:
            for fn in model.functions:
                if re.search(
                    r"(?:'" + re.escape(fn.name) + r"'|\b" + re.escape(fn.name) + r")\s*\(",
                    m.dax_expression,
                ):
                    usage.setdefault(fn.name, []).append((m.name, t.name))
    return usage


def _functions_section(model: SemanticModel, include_dax: bool) -> str:
    lines = ["## 4. Functions", ""]

    if not model.functions:
        lines += ["*No user-defined functions defined.*", "", "---", ""]
        return "\n".join(lines)

    usage_map = _build_function_usage_map(model)
    lines += ["| Function | Used By | Description |", "|---|---|---|"]
    for fn in model.functions:
        used_by = usage_map.get(fn.name)
        used_cell = (
            ", ".join(f"`{mname}` ({tbl})" for mname, tbl in used_by) if used_by else "-"
        )
        desc = fn.description or "-"
        lines.append(_md_row(f"`{fn.name}`", used_cell, desc))
    lines.append("")
    if include_dax:
        for fn in model.functions:
            if not fn.expression.strip():
                continue
            lines += [f"**`{fn.name}`**", "```dax", fn.expression, "```", ""]

    lines += ["---", ""]
    return "\n".join(lines)


def _relationships_section(model: SemanticModel) -> str:
    lines = ["## 5. Relationships", ""]

    visible = [
        r for r in model.relationships
        if not _is_auto_date_table(r.from_table) and not _is_auto_date_table(r.to_table)
    ]

    if not visible:
        lines += ["*No relationships defined in this model.*", "", "---", ""]
        return "\n".join(lines)

    active   = [r for r in visible if r.is_active]
    inactive = [r for r in visible if not r.is_active]

    if active:
        lines += [
            "| From Table | From Column | To Table | To Column | Cardinality | Cross Filter | Security Filter |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in active:
            lines.append(
                _md_row(f"`{r.from_table}`", f"`{r.from_column}`", f"`{r.to_table}`", f"`{r.to_column}`", r.cardinality or "-", r.cross_filtering_behavior, r.security_filtering_behavior)
            )
        lines.append("")

    if inactive:
        lines += [
            "**Inactive Relationships**", "",
            "| From Table | From Column | To Table | To Column | Cross Filter | Security Filter |",
            "|---|---|---|---|---|---|",
        ]
        for r in inactive:
            lines.append(
                _md_row(f"`{r.from_table}`", f"`{r.from_column}`", f"`{r.to_table}`", f"`{r.to_column}`", r.cross_filtering_behavior, r.security_filtering_behavior)
            )
        lines.append("")

    lines += ["---", ""]
    return "\n".join(lines)


def _build_param_usage_map(model: SemanticModel) -> dict[str, list[str]]:
    usage: dict[str, list[str]] = {p.name: [] for p in model.m_parameters}
    param_names = set(usage.keys())
    for expr in model.source_expressions:
        for field_val in (expr.server, expr.database, expr.url, expr.file_name, expr.sharepoint_url, expr.dsn):
            if not field_val:
                continue
            for pname in param_names:
                if f"[param:{pname}]" in field_val:
                    if expr.name not in usage[pname]:
                        usage[pname].append(expr.name)
    return usage


# ---------------------------------------------------------------------------
# Stage 4b - hidden cross-reference detection
# ---------------------------------------------------------------------------

def _build_hidden_reference_map(model: SemanticModel) -> tuple[dict, dict, dict]:
    """Build lookup dicts for hidden-object detection from DAX expressions.

    Returns (tables_by_name, hidden_measures, hidden_columns):
      tables_by_name  - {table_name: Table} for every table in the model.
      hidden_measures - {measure_name: table_name_or_list} - for each measure
                        whose own is_hidden is True or whose owning table is
                        hidden.  If the same measure name appears on multiple
                        tables the value is a list of all owning tables (the
                        ambiguity case).
      hidden_columns  - {(table_name, column_name): True} - for each column
                        whose own is_hidden is True or whose owning table is
                        hidden.
    """
    tables_by_name: dict[str, Table] = {}
    hidden_measures: dict = {}
    hidden_columns: dict[tuple[str, str], bool] = {}

    for table in model.tables:
        tables_by_name[table.name] = table
        table_hidden = table.is_hidden

        for m in table.measures:
            if m.is_hidden or table_hidden:
                if m.name in hidden_measures:
                    existing = hidden_measures[m.name]
                    if isinstance(existing, list):
                        if table.name not in existing:
                            existing.append(table.name)
                    else:
                        if existing != table.name:
                            hidden_measures[m.name] = [existing, table.name]
                    # if same table appears twice, no change needed
                else:
                    hidden_measures[m.name] = table.name

        for c in table.columns:
            if c.is_hidden or table_hidden:
                hidden_columns[(table.name, c.name)] = True

    return tables_by_name, hidden_measures, hidden_columns


def _find_hidden_references(
    dax_expression: str,
    tables_by_name: dict,
    hidden_measures: dict,
    hidden_columns: dict,
) -> list[tuple[str, str]]:
    """Scan a single DAX expression for references to hidden objects.

    Returns a list of (display_name, owning_table) tuples, de-duplicated,
    in encounter order.  Skips references that are ambiguous (same bare
    measure name on multiple tables) rather than guessing.
    """
    dax = dax_expression

    # Strip content inside double-quoted string literals to avoid false
    # matches on bracket characters inside literal strings.
    # Replace string contents with spaces (preserving length) so positions
    # of non-string tokens are unchanged relative to the original.
    cleaned = []
    i = 0
    while i < len(dax):
        if dax[i] == '"':
            j = i + 1
            while j < len(dax):
                if dax[j] == '"':
                    j += 1
                    break
                j += 1
            # Replace string content (including quotes) with spaces
            cleaned.append(" " * (j - i))
            i = j
        else:
            cleaned.append(dax[i])
            i += 1
    stripped = "".join(cleaned)

    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # Pattern 1: Column references - 'TableName'[ColumnName] or TableName[ColumnName]
    # Matches optional single-quoted or bare table name, then [ColumnName]
    col_pattern = re.compile(
        r"(?:'([^']+)'|([A-Za-z_]\w*)) \[ ([A-Za-z_][A-Za-z0-9_. ]*) \]",
        re.VERBOSE,
    )
    for m in col_pattern.finditer(stripped):
        table_name = m.group(1) if m.group(1) else m.group(2)
        col_name = m.group(3).strip()
        # Verify the reference points to a real hidden object
        tbl = tables_by_name.get(table_name)
        if tbl is None:
            continue
        is_hidden_ref = False
        if tbl.is_hidden:
            is_hidden_ref = True
        elif (table_name, col_name) in hidden_columns:
            is_hidden_ref = True
        if is_hidden_ref:
            display = f"{table_name}[{col_name}]"
            key = (display, table_name)
            if key not in seen:
                seen.add(key)
                results.append(key)

    # Pattern 2: Bare measure references - [MeasureName]
    # Must NOT be preceded by a table name (closing quote, letter, or ])
    # Find all [MeasureName] tokens via regex
    meas_pattern = re.compile(r"\[ ([A-Za-z_][A-Za-z0-9_. ()+-]*) \]", re.VERBOSE)
    for m in meas_pattern.finditer(stripped):
        start = m.start()
        # Check that this is a bare reference - not preceded by a closing
        # single-quote, closing double-quote, or alphanumeric character
        # (which would indicate a table-qualified column reference).
        if start > 0:
            prev_char = stripped[start - 1]
            if prev_char not in (" ", "\t", "\n", "\r", "(", ",", "=", "+", "-", "*", "/", ">", "<", "!", "&", "|", "~", "^", "%"):
                # This bracket is attached to something - could be table[col]
                # already caught by Pattern 1, or part of another syntax.
                # Skip it.
                continue
        meas_name = m.group(1).strip()
        if meas_name not in hidden_measures:
            continue
        entry = hidden_measures[meas_name]
        if isinstance(entry, list):
            # Ambiguous - multiple tables have a hidden measure with this name.
            # Skip rather than guessing.
            continue
        table_name = entry
        display = f"[{meas_name}]"
        key = (display, table_name)
        if key not in seen:
            seen.add(key)
            results.append(key)

    return results


def _hidden_reference_note(refs: list[tuple[str, str]]) -> str:
    """Render the hidden-reference warning line for a list of refs.

    Returns a single Markdown line starting with ⚠, or "" if empty.
    """
    if not refs:
        return ""
    parts = []
    for display_name, owning_table in refs:
        parts.append(f"`{display_name}` (in `{owning_table}`)")
    return "⚠ References hidden: " + ", ".join(parts)


def _security_roles_section(model: SemanticModel) -> str:
    lines = ["## 6. Security Roles", ""]

    if not model.security_roles:
        lines += ["*No security roles defined.*", "", "---", ""]
        return "\n".join(lines)

    lines += ["| Role | Table | Filter | Dynamic |", "|---|---|---|---|"]
    for role in model.security_roles:
        if not role.table_filters:
            dynamic_label = f"Yes ({role.dynamic_function})" if role.is_dynamic else "No"
            lines.append(_md_row(f"`{role.name}`", "-", "-", dynamic_label))
        else:
            for i, tf in enumerate(role.table_filters):
                role_cell     = f"`{role.name}`" if i == 0 else ""
                dynamic_label = (f"Yes ({role.dynamic_function})" if role.is_dynamic else "No") if i == 0 else ""
                lines.append(_md_row(role_cell, f"`{tf.table}`", f"`{tf.dax_filter}`", dynamic_label))

    lines += ["", "---", ""]
    return "\n".join(lines)


def _m_parameters_section(model: SemanticModel) -> str:
    lines = ["## 7. M Parameters", ""]

    if not model.m_parameters:
        lines += ["*No M parameters defined.*", "", "---", ""]
        return "\n".join(lines)

    usage_map = _build_param_usage_map(model)
    lines += ["| Parameter | Type | Value | Used By |", "|---|---|---|---|"]
    for p in model.m_parameters:
        used_by   = usage_map.get(p.name, [])
        used_cell = ", ".join(f"`{e}`" for e in used_by) if used_by else "-"
        val_cell  = f"`{p.value}`" if p.value.strip() else "-"
        lines.append(_md_row(f"`{p.name}`", p.param_type, val_cell, used_cell))

    lines += [
        "",
        "> *Only direct parameter references in connector calls are shown.",
        "> Parameters used in conditional logic or computed expressions may not appear here.*",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _unresolved_section(resolved: dict[str, ResolvedSource]) -> str:
    unresolved = [rs for rs in resolved.values() if rs.unresolved]
    if not unresolved:
        return ""
    lines = [
        "## ⚠ Unresolved Sources",
        "",
        "The following sources could not be resolved statically.",
        "Use tmdl-lens to provide a manual label for each.",
        "",
        "| Expression | Reason |",
        "|---|---|",
    ]
    for rs in unresolved:
        lines.append(_md_row(f"`{rs.expression_name}`", rs.unresolved_reason))
    lines += ["", "---", ""]
    return "\n".join(lines)


def _statistics_section(
    model: SemanticModel,
    loaded_tables: list[Table],
    support_tables: list[Table],
    staging_tables: list[Table],
    hidden_tables: list[Table],
) -> str:
    calc      = [t for t in support_tables if t.table_type == "calculated"]
    fp        = [t for t in support_tables if t.table_type == "field_parameter"]
    mo        = [t for t in support_tables if t.table_type == "measures_only"]
    cg        = [t for t in support_tables if t.table_type == "calc_group"]
    all_meas  = [m for t in model.tables for m in t.measures]
    calc_cols = [c for t in model.tables for c in t.columns if c.is_calculated]
    visible_rels = [
        r for r in model.relationships
        if not _is_auto_date_table(r.from_table) and not _is_auto_date_table(r.to_table)
    ]

    def names(lst):
        return ", ".join(f"`{t.name}`" for t in lst) if lst else "-"

    lines = [
        "## 8. Model Statistics",
        "",
        "| Category | Count | Items |",
        "|---|---|---|",
        _md_row("Loaded Tables", len(loaded_tables), names(loaded_tables)),
        _md_row("Hidden Tables", len(hidden_tables), names(hidden_tables)),
        _md_row("Calculated Tables", len(calc), names(calc)),
        _md_row("Field Parameters", len(fp), names(fp)),
        _md_row("Measures-Only Tables", len(mo), names(mo)),
        _md_row("Calculation Groups", len(cg), names(cg)),
        _md_row("Not Loaded", len(staging_tables), names(staging_tables)),
        _md_row("Relationships", len(visible_rels), "-"),
        _md_row("Measures", len(all_meas), "-"),
        _md_row("Calculated Columns", len(calc_cols), "-"),
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

_HTML_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px; line-height: 1.6;
    background: #f8f9fb; color: #1e2330;
    padding: 32px 24px;
}
.container { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 26px; font-weight: 700; color: #0f1520; margin-bottom: 6px; }
.subtitle { font-size: 13px; color: #7b8499; margin-bottom: 32px; }
h2 { font-size: 17px; font-weight: 700; color: #1e2330; margin: 36px 0 14px;
     padding-bottom: 6px; border-bottom: 2px solid #e2e6f0; }
h3 { font-size: 14px; font-weight: 600; color: #2e3548; margin: 20px 0 8px; }
h4 { font-size: 13px; font-weight: 600; color: #4a5068; margin: 14px 0 6px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 13px; }
th { background: #eef0f7; color: #3d4464; font-weight: 600;
     padding: 8px 12px; text-align: left; border: 1px solid #dde1ee; }
td { padding: 7px 12px; border: 1px solid #e8eaf2; vertical-align: top; }
tr:nth-child(even) td { background: #f4f5fb; }
code { font-family: 'Cascadia Code', 'Consolas', monospace;
       font-size: 12px; background: #eef0f7; color: #2e3548;
       padding: 1px 5px; border-radius: 3px; }
pre { background: #1e2330; color: #c8d0e8;
      font-family: 'Cascadia Code', 'Consolas', monospace;
      font-size: 12px; padding: 14px 16px; border-radius: 6px;
      overflow-x: auto; margin: 8px 0 14px; white-space: pre-wrap; }
pre code { background: none; color: inherit; padding: 0; }
.overview-table td:first-child { font-weight: 600; width: 180px; color: #3d4464; }
.section-note { font-size: 12px; color: #7b8499; margin-bottom: 10px;
                padding: 8px 12px; background: #f0f2fa;
                border-left: 3px solid #c5cae0; border-radius: 0 4px 4px 0; }
.footer { margin-top: 40px; font-size: 12px; color: #9aa3b8;
          border-top: 1px solid #e2e6f0; padding-top: 12px; }
.empty { color: #9aa3b8; font-style: italic; font-size: 13px; }
"""


class _RawHtml(str):
    """A string that is already safe, fully-built HTML. _html_table and
    _html_fmt_inventory_table skip escaping for cells of this type."""
    pass


def _esc(text) -> _RawHtml:
    if isinstance(text, _RawHtml):
        return text
    a = chr(38)  # &
    return _RawHtml(
        str(text)
        .replace(chr(38), a + "amp;")
        .replace(chr(60), a + "lt;")
        .replace(chr(62), a + "gt;")
        .replace(chr(34), a + "quot;")
    )


def _html_table(headers: list[str], rows: list[list[str]], css_class: str = "") -> str:
    cls = f' class="{css_class}"' if css_class else ""
    th_cells = "".join(f"<th>{_esc(h)}</th>" for h in headers)

    def render_cell(cell) -> str:
        if isinstance(cell, _RawHtml):
            return cell
        return _esc(cell)

    body_rows = "".join(
        f"<tr>{''.join(f'<td>{render_cell(cell)}</td>' for cell in row)}</tr>"
        for row in rows
    )
    return f"<table{cls}><thead><tr>{th_cells}</tr></thead><tbody>{body_rows}</tbody></table>"


def _html_fmt_inventory_table(
    title: str,
    groups: list[tuple[str, list[tuple[str, str]]]],
    total: int,
    unique: int,
    col_header: str,
) -> str:
    """Render a format string inventory as an HTML table."""
    parts = [
        f"<h4>{_esc(title)} ({total} total, {unique} unique)</h4>",
        _html_table(
            ["Format String", "Count", col_header],
            [
                (
                    _RawHtml(f"<code>{_esc(fmt)}</code>") if fmt != "(none)" else "(none)",
                    str(len(items)),
                    _RawHtml(", ".join(f"<code>{_esc(name)}</code> ({_esc(tbl)})" for name, tbl in items)),
                )
                for fmt, items in groups
            ],
        ),
    ]
    return "\n".join(parts)


def _code(text: str) -> _RawHtml:
    return _RawHtml(f"<code>{_esc(text)}</code>")


def _pre(text: str) -> _RawHtml:
    return _RawHtml(f"<pre><code>{_esc(text)}</code></pre>")


def _md_value_html(value: str) -> _RawHtml:
    return _RawHtml(re.sub(r"`([^`]*)`", r"<code>\1</code>", _esc(value)))


def generate_html(
    model: SemanticModel,
    resolved: dict[str, ResolvedSource],
    config: dict,
) -> str:
    report_name = config.get("report_name", model.report_name)
    include_dax = config.get("include_dax", True)
    show_hidden = config.get("show_hidden", True)

    collected = _collect(model, show_hidden)
    model = collected["model"]
    loaded = collected["loaded"]
    support = collected["support"]
    staging = collected["staging"]
    loaded_visible = collected["loaded_visible"]
    hidden_tables = collected["hidden_tables"]
    all_measures = collected["measures"]

    ref_tables, ref_measures, ref_columns = _build_hidden_reference_map(model)

    body = [f'<div class="container">',
            f'<h1>{_esc(report_name)}</h1>',
            '<div class="subtitle">Generated by tmdl-lens</div>']

    overview_rows = []
    if config.get("owner"):
        overview_rows.append(["Owner", _esc(config["owner"])])
    if config.get("team"):
        overview_rows.append(["Team", _esc(config["team"])])
    if config.get("refresh_schedule"):
        overview_rows.append(["Refresh Schedule", _esc(config["refresh_schedule"])])
    overview_rows.extend([
        ["Culture",             _esc(model.model_culture or "-")],
        ["Compatibility Level", _esc(model.database_compatibility_level or "-")],
        ["Data Source Version", _esc(model.model_data_source_version or "-")],
    ])
    body.append('<h2>Overview</h2>')
    body.append(_html_table(["Property", "Value"], overview_rows, "overview-table"))

    body.append('<h2>1. Data Sources</h2>')
    body.append(f'<p>{_esc(_model_summary(loaded, staging, support, model))}</p>')
    if loaded:
        rows = []
        for t in loaded:
            rs = get_table_source(t, resolved)
            src_type = _connector_type_label(rs) if rs else "-"
            label    = _source_label(rs) if rs else "-"
            name_cell = _RawHtml(f"{_code(t.name)} (hidden)") if t.is_hidden else _code(t.name)
            rows.append([name_cell, _esc(src_type), _esc(label)])
        body.append(_html_table(["Table", "Source Type", "Source"], rows))
    if support:
        body.append('<h3>Support Tables</h3>')
        body.append(_html_table(["Table", "Type"],
            [[_code(t.name), _esc(_table_type_label(t.table_type))] for t in support]))
    body.append('<h3>Not Loaded</h3>')
    if staging:
        rows = []
        for t in staging:
            rs = get_table_source(t, resolved)
            src_type = _connector_type_label(rs) if rs else "-"
            label    = _source_label(rs) if rs else "-"
            rows.append([_code(t.name), _esc(src_type), _esc(label)])
        body.append(_html_table(["Table", "Source Type", "Source"], rows))
        # Staging column format string inventory (HTML)
        staging_col_groups: dict[str, list[tuple[str, str]]] = {}
        for t in staging:
            for c in t.columns:
                key = c.format_string.strip() if c.format_string.strip() else "(none)"
                staging_col_groups.setdefault(key, []).append((c.name, t.name))
        if staging_col_groups:
            staging_col_sorted = sorted(staging_col_groups.items(), key=lambda x: -len(x[1]))
            staging_col_total = sum(len(v) for v in staging_col_groups.values())
            staging_col_unique = len(staging_col_groups)
            body.append(_html_fmt_inventory_table(
                "Not Loaded Column Format Strings", staging_col_sorted, staging_col_total, staging_col_unique, "Columns"
            ))
    else:
        body.append('<p class="empty">None.</p>')

    body.append('<h2>2. Table Details</h2>')
    detail_support = [
        t for t in support
        if t.table_type in ("calc_group", "calculated", "field_parameter")
    ]
    if show_hidden:
        table_detail_tables = loaded + detail_support
    else:
        table_detail_tables = loaded_visible + detail_support
    for t in table_detail_tables:
        body.append(f'<h3>{_code(t.name)}</h3>')
        rs = get_table_source(t, resolved)
        if rs:
            for label, value in _source_detail_fields(rs):
                body.append(f'<p><strong>{_esc(label)}:</strong> {_md_value_html(value)}</p>')
        elif t.table_type == "calculated":
            body.append('<p><strong>Source:</strong> Calculated (DAX)</p>')
            if include_dax and t.dax_partition:
                body.append(_pre(t.dax_partition))
        elif t.table_type == "field_parameter":
            body.append('<p><strong>Source:</strong> Field Parameter</p>')
        elif t.table_type == "measures_only":
            body.append('<p><strong>Source:</strong> Measures only - no data source</p>')
        if t.is_hidden:
            body.append('<p><strong>Hidden:</strong> Yes</p>')
        # Columns
        if show_hidden:
            display_cols = [c for c in t.columns if not c.is_calculated]
        else:
            display_cols = [c for c in t.columns if not c.is_calculated and not c.is_hidden]
        if display_cols:
            body.append('<h4>Columns</h4>')
            body.append(_html_table(
                ["Column", "Type", "Format", "Summarize By", "Source Column", "Sort By", "Description", "Hidden"],
                [[_code(c.name),
                  _esc(_dtype(c.data_type)),
                  _code(c.format_string) if c.format_string else "-",
                  _esc(c.summarize_by) if c.summarize_by else "-",
                  _code(c.source_column) if c.source_column else "-",
                  _code(c.sort_by_column) if c.sort_by_column else "-",
                  _esc(c.description) if c.description else "-",
                  _esc("Hidden" if c.is_hidden else "")]
                 for c in display_cols]))
            key_cols = [c.name for c in display_cols if c.is_key]
            if key_cols:
                body.append('<p><strong>Key Column:</strong> '
                            + ", ".join(_code(k) for k in key_cols) + '</p>')
            cat_cols = [(c.name, c.data_category) for c in display_cols if c.data_category]
            if cat_cols:
                body.append('<p><strong>Data Categories:</strong> '
                            + ", ".join(f"{_code(n)} = {_esc(cat)}" for n, cat in cat_cols)
                            + '</p>')
        # Calculated columns
        calc_cols = [c for c in t.columns if c.is_calculated]
        if calc_cols:
            body.append('<h4>Calculated Columns</h4>')
            for col in calc_cols:
                if include_dax and col.dax_expression:
                    body.append(f'<p><strong>{_code(col.name)}</strong></p>')
                    body.append(_pre(col.dax_expression))
                    refs = _find_hidden_references(
                        col.dax_expression, ref_tables, ref_measures, ref_columns
                    )
                    if refs:
                        parts = [f"{_code(display)} (in {_code(tbl)})" for display, tbl in refs]
                        body.append(f"<p>\u26a0 References hidden: {', '.join(parts)}</p>")
        # Calculation items
        if t.calculation_items:
            body.append('<h4>Calculation Items</h4>')
            rows = [[_code(i.name), str(i.ordinal),
                     _code(i.format_string_expression) if i.format_string_expression else "-"]
                    for i in t.calculation_items]
            body.append(_html_table(["Item", "Ordinal", "Format String"], rows))
            body.append('<p class="section-note">Calculation items can be applied to any measure at report-build time (via <code>SELECTEDMEASURE()</code>). TMDL has no static record of which measures a given item is actually used with.</p>')
            if include_dax:
                for item in t.calculation_items:
                    body.append(f'<h4>{_code(item.name)}</h4>')
                    body.append(_pre(item.dax_expression))
        # Measures
        if show_hidden:
            display_measures = t.measures[:]
        else:
            display_measures = [m for m in t.measures if not m.is_hidden]
        if display_measures:
            body.append('<h4>Measures</h4>')
            rows = [[_code(m.name),
                     _code(m.format_string) if m.format_string else "-",
                     _esc(m.description) if m.description else "-",
                     _esc("Hidden" if m.is_hidden else "")]
                    for m in display_measures]
            body.append(_html_table(["Measure", "Format", "Description", "Hidden"], rows))
            if include_dax:
                for m in display_measures:
                    if not m.dax_expression.strip():
                        continue
                    body.append(f'<h4>{_code(m.name)}</h4>')
                    body.append(_pre(m.dax_expression))
                    refs = _find_hidden_references(
                        m.dax_expression, ref_tables, ref_measures, ref_columns
                    )
                    if refs:
                        parts = [f"{_code(display)} (in {_code(tbl)})" for display, tbl in refs]
                        body.append(f"<p>\u26a0 References hidden: {', '.join(parts)}</p>")

    body.append('<h2>3. Measures</h2>')
    if not all_measures:
        body.append('<p class="empty">No measures defined in this model.</p>')
    else:
        folders: dict[str, list] = {}
        for table_name, m in all_measures:
            folders.setdefault(m.display_folder or "General", []).append((table_name, m))
        for folder in sorted(folders.keys()):
            body.append(f'<h3>{_esc(folder)}</h3>')
            rows = [[_code(m.name), _code(tn),
                     _code(m.format_string) if m.format_string else "-",
                     _esc(m.description) if m.description else "-"]
                    for tn, m in folders[folder]]
            body.append(_html_table(["Measure", "Table", "Format", "Description"], rows))
            if include_dax:
                for _, m in folders[folder]:
                    if not m.dax_expression.strip():
                        continue
                    body.append(f'<h4>{_code(m.name)}</h4>')
                    body.append(_pre(m.dax_expression))

    # Measure format string inventory (HTML)
    if all_measures:
        meas_groups: dict[str, list[tuple[str, str]]] = {}
        for tn, m in all_measures:
            key = m.format_string.strip() if m.format_string.strip() else "(none)"
            meas_groups.setdefault(key, []).append((m.name, tn))
        if meas_groups:
            meas_sorted = sorted(meas_groups.items(), key=lambda x: -len(x[1]))
            meas_total = sum(len(v) for v in meas_groups.values())
            meas_unique = len(meas_groups)
            body.append(_html_fmt_inventory_table(
                "Measure Format Strings", meas_sorted, meas_total, meas_unique, "Measures"
            ))

    # Column format string inventory (HTML)
    col_groups: dict[str, list[tuple[str, str]]] = {}
    for t in loaded + support:
        for c in t.columns:
            key = c.format_string.strip() if c.format_string.strip() else "(none)"
            col_groups.setdefault(key, []).append((c.name, t.name))
    if col_groups:
        col_sorted = sorted(col_groups.items(), key=lambda x: -len(x[1]))
        col_total = sum(len(v) for v in col_groups.values())
        col_unique = len(col_groups)
        body.append(_html_fmt_inventory_table(
            "Column Format Strings", col_sorted, col_total, col_unique, "Columns"
        ))

    body.append('<h2>4. Functions</h2>')
    if not model.functions:
        body.append('<p class="empty">No user-defined functions defined.</p>')
    else:
        fn_usage = _build_function_usage_map(model)
        fn_rows = []
        for fn in model.functions:
            used_by = fn_usage.get(fn.name)
            used_cell = (
                _RawHtml(", ".join(_code(mname) + " (" + _esc(tbl) + ")" for mname, tbl in used_by))
                if used_by else "-"
            )
            fn_rows.append([_code(fn.name), used_cell, _esc(fn.description) if fn.description else "-"])
        body.append(_html_table(["Function", "Used By", "Description"], fn_rows))
        if include_dax:
            for fn in model.functions:
                if not fn.expression.strip():
                    continue
                body.append(f'<h4>{_code(fn.name)}</h4>')
                body.append(_pre(fn.expression))

    body.append('<h2>5. Relationships</h2>')
    visible_rels = [
        r for r in model.relationships
        if not _is_auto_date_table(r.from_table) and not _is_auto_date_table(r.to_table)
    ]
    if not visible_rels:
        body.append('<p class="empty">No relationships defined in this model.</p>')
    else:
        active   = [r for r in visible_rels if r.is_active]
        inactive = [r for r in visible_rels if not r.is_active]
        if active:
            body.append(_html_table(
                ["From Table", "From Column", "To Table", "To Column", "Cardinality", "Cross Filter", "Security Filter"],
                [[_code(r.from_table), _code(r.from_column),
                  _code(r.to_table),   _code(r.to_column), _esc(r.cardinality or "-"),
                  _esc(r.cross_filtering_behavior), _esc(r.security_filtering_behavior)]
                 for r in active]))
        if inactive:
            body.append('<h3>Inactive Relationships</h3>')
            body.append(_html_table(
                ["From Table", "From Column", "To Table", "To Column", "Cross Filter", "Security Filter"],
                [[_code(r.from_table), _code(r.from_column),
                  _code(r.to_table),   _code(r.to_column),
                  _esc(r.cross_filtering_behavior), _esc(r.security_filtering_behavior)]
                 for r in inactive]))

    body.append('<h2>6. Security Roles</h2>')
    if not model.security_roles:
        body.append('<p class="empty">No security roles defined.</p>')
    else:
        rows = []
        for role in model.security_roles:
            if not role.table_filters:
                dyn = _RawHtml(f"Yes ({_esc(role.dynamic_function)})") if role.is_dynamic else "No"
                rows.append([_code(role.name), "-", "-", dyn])
            else:
                for i, tf in enumerate(role.table_filters):
                    role_cell = _code(role.name) if i == 0 else ""
                    dyn = (_RawHtml(f"Yes ({_esc(role.dynamic_function)})") if role.is_dynamic else "No") if i == 0 else ""
                    rows.append([role_cell, _code(tf.table), _code(tf.dax_filter), dyn])
        body.append(_html_table(["Role", "Table", "Filter", "Dynamic"], rows))

    body.append('<h2>7. M Parameters</h2>')
    if not model.m_parameters:
        body.append('<p class="empty">No M parameters defined.</p>')
    else:
        usage_map = _build_param_usage_map(model)
        rows = [[_code(p.name), _esc(p.param_type), _code(p.value),
                 _RawHtml(", ".join(_code(e) for e in usage_map.get(p.name, []))) or "-"]
                for p in model.m_parameters]
        body.append(_html_table(["Parameter", "Type", "Value", "Used By"], rows))
        body.append('<p class="section-note">Only direct parameter references in connector calls are shown.</p>')

    unresolved = [rs for rs in resolved.values() if rs.unresolved]
    if unresolved:
        body.append('<h2>&#9888; Unresolved Sources</h2>')
        body.append('<p>The following sources could not be resolved statically.</p>')
        body.append(_html_table(["Expression", "Reason"],
            [[_code(rs.expression_name), _esc(rs.unresolved_reason)] for rs in unresolved]))

    body.append('<h2>8. Model Statistics</h2>')
    calc      = [t for t in support if t.table_type == "calculated"]
    fp        = [t for t in support if t.table_type == "field_parameter"]
    mo        = [t for t in support if t.table_type == "measures_only"]
    cg        = [t for t in support if t.table_type == "calc_group"]
    all_meas  = [m for t in model.tables for m in t.measures]
    calc_cols = [c for t in model.tables for c in t.columns if c.is_calculated]
    def _names(lst): return _RawHtml(", ".join(_code(t.name) for t in lst)) if lst else "-"
    body.append(_html_table(["Category", "Count", "Items"], [
        ["Loaded Tables",        str(len(loaded_visible)),       _names(loaded_visible)],
        ["Hidden Tables",        str(len(hidden_tables)),        _names(hidden_tables)],
        ["Calculated Tables",    str(len(calc)),                 _names(calc)],
        ["Field Parameters",     str(len(fp)),                   _names(fp)],
        ["Measures-Only Tables", str(len(mo)),                   _names(mo)],
        ["Calculation Groups",   str(len(cg)),                   _names(cg)],
        ["Not Loaded",           str(len(staging)),              _names(staging)],
        ["Relationships",        str(len(visible_rels)),         "-"],
        ["Measures",             str(len(all_meas)),             "-"],
        ["Calculated Columns",   str(len(calc_cols)),            "-"],
    ]))

    body.append('<div class="footer">Generated by tmdl-lens</div>')
    body.append('</div>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(report_name)}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
{chr(10).join(body)}
</body>
</html>
"""


def generate_readme(
    model: SemanticModel,
    resolved: dict[str, ResolvedSource],
    config: dict,
) -> str:
    report_name = config.get("report_name", model.report_name)
    include_dax = config.get("include_dax", True)
    show_hidden = config.get("show_hidden", True)

    collected = _collect(model, show_hidden)
    model = collected["model"]
    loaded = collected["loaded"]
    support = collected["support"]
    staging = collected["staging"]
    loaded_visible = collected["loaded_visible"]

    ref_tables, ref_measures, ref_columns = _build_hidden_reference_map(model)

    sections = [
        f"# {report_name}\n",
        _overview_section(config, model),
        _data_sources_section(loaded, staging, support, resolved, model),
        _table_details_section(loaded, support, resolved, include_dax, ref_tables, ref_measures, ref_columns, show_hidden),
        _measures_section(collected["measures"], include_dax),
        _functions_section(model, include_dax),
        _relationships_section(model),
        _security_roles_section(model),
        _m_parameters_section(model),
    ]

    unresolved = _unresolved_section(resolved)
    if unresolved:
        sections.append(unresolved)

    sections.append(_statistics_section(model, loaded_visible, support, staging, collected["hidden_tables"]))

    sections.append("*Generated by tmdl-lens*\n")

    return "\n".join(sections)
