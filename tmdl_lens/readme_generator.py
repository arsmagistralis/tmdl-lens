"""
readme_generator.py - Markdown README generator for tmdl-lens.

Takes a parsed SemanticModel and resolved sources dict and produces
a structured README.md for each Power BI report.
"""

import re
from dataclasses import dataclass, replace

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
    Uses rs.label which already contains the full chain (e.g. 'orders-source -> Web API').
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


_SECTIONS = [
    ("overview",       "Overview"),
    ("data_sources",   "1. Data Sources"),
    ("table_details",  "2. Table Details"),
    ("measures",       "3. Measures"),
    ("functions",      "4. Functions"),
    ("relationships",  "5. Relationships"),
    ("security_roles", "6. Security Roles"),
    ("m_parameters",   "7. M Parameters"),
    ("unresolved",     "Unresolved Sources"),
    ("statistics",     "8. Model Statistics"),
]

_SECTION_TITLE = dict(_SECTIONS)


@dataclass(frozen=True)
class _Code:
    text: str
    suffix: str = ""


@dataclass(frozen=True)
class _CodeList:
    names: tuple


@dataclass(frozen=True)
class _CodeRefs:
    pairs: tuple


def _code_or_dash(text: str):
    return _Code(text) if text else "-"


def _visible_relationships(model: SemanticModel) -> list:
    return [
        r for r in model.relationships
        if not _is_auto_date_table(r.from_table) and not _is_auto_date_table(r.to_table)
    ]


def _support_split(support_tables: list[Table]) -> tuple[list, list, list, list]:
    return (
        [t for t in support_tables if t.table_type == "calculated"],
        [t for t in support_tables if t.table_type == "field_parameter"],
        [t for t in support_tables if t.table_type == "measures_only"],
        [t for t in support_tables if t.table_type == "calc_group"],
    )


def _overview_rows(config: dict, model: SemanticModel) -> list:
    rows = []
    if config.get("owner"):
        rows.append(("Owner", config["owner"]))
    if config.get("team"):
        rows.append(("Team", config["team"]))
    if config.get("refresh_schedule"):
        rows.append(("Refresh Schedule", config["refresh_schedule"]))
    rows.extend([
        ("Culture", model.model_culture or "-"),
        ("Compatibility Level", model.database_compatibility_level or "-"),
        ("Data Source Version", model.model_data_source_version or "-"),
    ])
    return rows


def _source_rows(tables: list[Table], resolved: dict[str, ResolvedSource], mark_hidden: bool) -> list:
    rows = []
    for t in tables:
        rs = get_table_source(t, resolved)
        src_type = _connector_type_label(rs) if rs else "-"
        label = _source_label(rs) if rs else "-"
        name = _Code(t.name, " (hidden)") if mark_hidden and t.is_hidden else _Code(t.name)
        rows.append((name, src_type, label))
    return rows


def _support_rows(support_tables: list[Table]) -> list:
    return [(_Code(t.name), _table_type_label(t.table_type)) for t in support_tables]


def _column_rows(columns: list) -> list:
    return [
        (
            _Code(c.name),
            _dtype(c.data_type),
            _code_or_dash(c.format_string),
            c.summarize_by or "-",
            _code_or_dash(c.source_column),
            _code_or_dash(c.sort_by_column),
            c.description or "-",
            "Hidden" if c.is_hidden else "",
        )
        for c in columns
    ]


def _table_measure_rows(measures: list) -> list:
    return [
        (
            _Code(m.name),
            _code_or_dash(m.format_string),
            m.description or "-",
            "Hidden" if m.is_hidden else "",
        )
        for m in measures
    ]


def _calc_item_rows(items: list) -> list:
    return [
        (_Code(i.name), str(i.ordinal), _code_or_dash(i.format_string_expression))
        for i in items
    ]


def _format_groups(pairs: list) -> tuple[list, int, int]:
    groups: dict[str, list[tuple[str, str]]] = {}
    for fmt, name, table_name in pairs:
        key = fmt.strip() if fmt.strip() else "(none)"
        groups.setdefault(key, []).append((name, table_name))
    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    return sorted_groups, len(pairs), len(groups)


def _format_rows(groups: list) -> list:
    return [
        (
            _Code(fmt) if fmt != "(none)" else "(none)",
            str(len(items)),
            _CodeRefs(tuple(items)),
        )
        for fmt, items in groups
    ]


def _column_format_pairs(tables: list[Table]) -> list:
    return [(c.format_string, c.name, t.name) for t in tables for c in t.columns]


def _measure_format_pairs(measures: list) -> list:
    return [(m.format_string, m.name, table_name) for table_name, m in measures]


def _measure_folders(measures: list) -> list:
    folders: dict[str, list[tuple]] = {}
    for table_name, m in measures:
        folders.setdefault(m.display_folder or "General", []).append((table_name, m))
    return [(folder, folders[folder]) for folder in sorted(folders.keys())]


def _folder_measure_rows(items: list) -> list:
    return [
        (
            _Code(m.name),
            _Code(table_name),
            _code_or_dash(m.format_string),
            m.description or "-",
        )
        for table_name, m in items
    ]


def _function_rows(model: SemanticModel) -> list:
    usage_map = _build_function_usage_map(model)
    return [
        (
            _Code(fn.name),
            _CodeRefs(tuple(usage_map.get(fn.name, ()))),
            fn.description or "-",
        )
        for fn in model.functions
    ]


def _relationship_rows(relationships: list, with_cardinality: bool) -> list:
    rows = []
    for r in relationships:
        row = [_Code(r.from_table), _Code(r.from_column), _Code(r.to_table), _Code(r.to_column)]
        if with_cardinality:
            row.append(r.cardinality or "-")
        row += [r.cross_filtering_behavior, r.security_filtering_behavior]
        rows.append(tuple(row))
    return rows


def _role_rows(model: SemanticModel) -> list:
    rows = []
    for role in model.security_roles:
        dynamic = f"Yes ({role.dynamic_function})" if role.is_dynamic else "No"
        if not role.table_filters:
            rows.append((_Code(role.name), "-", "-", dynamic))
            continue
        for i, tf in enumerate(role.table_filters):
            rows.append((
                _Code(role.name) if i == 0 else "",
                _Code(tf.table),
                _Code(tf.dax_filter),
                dynamic if i == 0 else "",
            ))
    return rows


def _parameter_rows(model: SemanticModel, dash_blank_value: bool) -> list:
    usage_map = _build_param_usage_map(model)
    rows = []
    for p in model.m_parameters:
        value = _Code(p.value) if p.value.strip() or not dash_blank_value else "-"
        rows.append((
            _Code(p.name),
            p.param_type,
            value,
            _CodeList(tuple(usage_map.get(p.name, []))),
        ))
    return rows


def _unresolved_rows(resolved: dict[str, ResolvedSource]) -> list:
    return [
        (_Code(rs.expression_name), rs.unresolved_reason)
        for rs in resolved.values() if rs.unresolved
    ]


def _statistics_rows(
    model: SemanticModel,
    loaded_tables: list[Table],
    support_tables: list[Table],
    staging_tables: list[Table],
    hidden_tables: list[Table],
) -> list:
    calc, fp, mo, cg = _support_split(support_tables)
    measure_count = sum(len(t.measures) for t in model.tables)
    calc_col_count = sum(1 for t in model.tables for c in t.columns if c.is_calculated)

    def names(tables):
        return _CodeList(tuple(t.name for t in tables))

    return [
        ("Loaded Tables",        str(len(loaded_tables)),  names(loaded_tables)),
        ("Hidden Tables",        str(len(hidden_tables)),  names(hidden_tables)),
        ("Calculated Tables",    str(len(calc)),           names(calc)),
        ("Field Parameters",     str(len(fp)),             names(fp)),
        ("Measures-Only Tables", str(len(mo)),             names(mo)),
        ("Calculation Groups",   str(len(cg)),             names(cg)),
        ("Not Loaded",           str(len(staging_tables)), names(staging_tables)),
        ("Relationships",        str(len(_visible_relationships(model))), "-"),
        ("Measures",             str(measure_count),       "-"),
        ("Calculated Columns",   str(calc_col_count),      "-"),
    ]


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
    n_rels     = len(_visible_relationships(model))

    parts = [f"{n_loaded} loaded {'table' if n_loaded == 1 else 'tables'}"]
    if support_tables:
        labels = []
        calc, fp, mo, cg = _support_split(support_tables)
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


def _md_text(cell) -> str:
    if isinstance(cell, _Code):
        return f"`{cell.text}`{cell.suffix}"
    if isinstance(cell, _CodeList):
        return ", ".join(f"`{n}`" for n in cell.names) if cell.names else "-"
    if isinstance(cell, _CodeRefs):
        return ", ".join(f"`{c}` ({p})" for c, p in cell.pairs) if cell.pairs else "-"
    return str(cell)


def _md_table_rows(rows: list) -> list[str]:
    return [_md_row(*(_md_text(cell) for cell in row)) for row in rows]


def _section_anchor(key: str) -> str:
    return key.replace("_", "-")


def _rendered_sections(resolved: dict[str, ResolvedSource]) -> list:
    has_unresolved = any(rs.unresolved for rs in resolved.values())
    return [(key, title) for key, title in _SECTIONS if key != "unresolved" or has_unresolved]


def _md_title(key: str) -> str:
    if key == "unresolved":
        return f"⚠ {_SECTION_TITLE[key]}"
    return _SECTION_TITLE[key]


def _md_heading(key: str) -> str:
    return f'<a id="{_section_anchor(key)}"></a>\n## {_md_title(key)}'


def _md_contents(resolved: dict[str, ResolvedSource]) -> str:
    lines = ["**Contents**", ""]
    lines += [f"- [{_md_title(key)}](#{_section_anchor(key)})" for key, _ in _rendered_sections(resolved)]
    lines += ["", "---", ""]
    return "\n".join(lines)


def _overview_section(config: dict, model: SemanticModel) -> str:
    rows = [_md_row(f"**{label}**", value) for label, value in _overview_rows(config, model)]

    lines = [
        _md_heading("overview"),
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
    lines = [_md_heading("data_sources"), ""]
    lines += [_model_summary(loaded_tables, staging_tables, support_tables, model), ""]

    if loaded_tables:
        lines += [
            "| Table | Source Type | Source |",
            "|---|---|---|",
        ]
        lines += _md_table_rows(_source_rows(loaded_tables, resolved, mark_hidden=True))
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
        lines += _md_table_rows(_support_rows(support_tables))
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
        lines += _md_table_rows(_source_rows(staging_tables, resolved, mark_hidden=False))
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
        lines += _md_table_rows(_column_rows(display_cols))
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
        lines += _md_table_rows(_calc_item_rows(table.calculation_items))
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
        lines += _md_table_rows(_table_measure_rows(display_measures))
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
    lines = [_md_heading("table_details"), ""]
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


def _md_format_inventory(pairs: list, heading: str, items_header: str) -> str:
    if not pairs:
        return ""
    groups, total, unique = _format_groups(pairs)
    lines = [
        "",
        f"**{heading} ({total} total, {unique} unique)**",
        "",
        f"| Format String | Count | {items_header} |",
        "|---|---|---|",
        *_md_table_rows(_format_rows(groups)),
        "",
    ]
    return "\n".join(lines)


def _column_format_string_inventory(tables: list[Table], heading: str = "Format Strings Used") -> str:
    return _md_format_inventory(_column_format_pairs(tables), heading, "Columns")


def _measure_format_string_inventory(measures: list) -> str:
    return _md_format_inventory(_measure_format_pairs(measures), "Format Strings Used", "Measures")


def _measures_section(measures: list, include_dax: bool) -> str:
    lines = [_md_heading("measures"), ""]

    if not measures:
        lines += ["*No measures defined in this model.*", "", "---", ""]
        return "\n".join(lines)

    for folder, items in _measure_folders(measures):
        lines += [f"### {folder.replace(chr(92), chr(92) * 2)}", "", "| Measure | Table | Format | Description |", "|---|---|---|---|"]
        lines += _md_table_rows(_folder_measure_rows(items))
        lines.append("")
        if include_dax:
            for _, m in items:
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
    lines = [_md_heading("functions"), ""]

    if not model.functions:
        lines += ["*No user-defined functions defined.*", "", "---", ""]
        return "\n".join(lines)

    lines += ["| Function | Used By | Description |", "|---|---|---|"]
    lines += _md_table_rows(_function_rows(model))
    lines.append("")
    if include_dax:
        for fn in model.functions:
            if not fn.expression.strip():
                continue
            lines += [f"**`{fn.name}`**", "```dax", fn.expression, "```", ""]

    lines += ["---", ""]
    return "\n".join(lines)


def _relationships_section(model: SemanticModel) -> str:
    lines = [_md_heading("relationships"), ""]

    visible = _visible_relationships(model)

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
        lines += _md_table_rows(_relationship_rows(active, with_cardinality=True))
        lines.append("")

    if inactive:
        lines += [
            "**Inactive Relationships**", "",
            "| From Table | From Column | To Table | To Column | Cross Filter | Security Filter |",
            "|---|---|---|---|---|---|",
        ]
        lines += _md_table_rows(_relationship_rows(inactive, with_cardinality=False))
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
    lines = [_md_heading("security_roles"), ""]

    if not model.security_roles:
        lines += ["*No security roles defined.*", "", "---", ""]
        return "\n".join(lines)

    lines += ["| Role | Table | Filter | Dynamic |", "|---|---|---|---|"]
    lines += _md_table_rows(_role_rows(model))

    lines += ["", "---", ""]
    return "\n".join(lines)


def _m_parameters_section(model: SemanticModel) -> str:
    lines = [_md_heading("m_parameters"), ""]

    if not model.m_parameters:
        lines += ["*No M parameters defined.*", "", "---", ""]
        return "\n".join(lines)

    lines += ["| Parameter | Type | Value | Used By |", "|---|---|---|---|"]
    lines += _md_table_rows(_parameter_rows(model, dash_blank_value=True))

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
    rows = _unresolved_rows(resolved)
    if not rows:
        return ""
    lines = [
        _md_heading("unresolved"),
        "",
        "The following sources could not be resolved statically.",
        "Use tmdl-lens to provide a manual label for each.",
        "",
        "| Expression | Reason |",
        "|---|---|",
    ]
    lines += _md_table_rows(rows)
    lines += ["", "---", ""]
    return "\n".join(lines)


def _statistics_section(
    model: SemanticModel,
    loaded_tables: list[Table],
    support_tables: list[Table],
    staging_tables: list[Table],
    hidden_tables: list[Table],
) -> str:
    lines = [
        _md_heading("statistics"),
        "",
        "| Category | Count | Items |",
        "|---|---|---|",
        *_md_table_rows(_statistics_rows(model, loaded_tables, support_tables, staging_tables, hidden_tables)),
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
.toc { margin-bottom: 24px; }
.toc-title { font-size: 12px; font-weight: 600; color: #7b8499; text-transform: uppercase; margin-bottom: 4px; }
.toc ul { list-style: none; columns: 2; font-size: 13px; }
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


def _code(text: str) -> _RawHtml:
    return _RawHtml(f"<code>{_esc(text)}</code>")


def _pre(text: str) -> _RawHtml:
    return _RawHtml(f"<pre><code>{_esc(text)}</code></pre>")


def _md_value_html(value: str) -> _RawHtml:
    return _RawHtml(re.sub(r"`([^`]*)`", r"<code>\1</code>", _esc(value)))


def _html_cell(cell):
    if isinstance(cell, _Code):
        return _RawHtml(_code(cell.text) + _esc(cell.suffix))
    if isinstance(cell, _CodeList):
        return _RawHtml(", ".join(_code(n) for n in cell.names)) if cell.names else "-"
    if isinstance(cell, _CodeRefs):
        if not cell.pairs:
            return "-"
        return _RawHtml(", ".join(f"{_code(c)} ({_esc(p)})" for c, p in cell.pairs))
    return cell


def _html_rows(rows: list) -> list[list]:
    return [[_html_cell(cell) for cell in row] for row in rows]


def _html_title(key: str) -> str:
    if key == "unresolved":
        return f"&#9888; {_esc(_SECTION_TITLE[key])}"
    return _esc(_SECTION_TITLE[key])


def _html_heading(key: str) -> str:
    return f'<h2 id="{_section_anchor(key)}">{_html_title(key)}</h2>'


def _html_contents(resolved: dict[str, ResolvedSource]) -> str:
    items = "".join(
        f'<li><a href="#{_section_anchor(key)}">{_html_title(key)}</a></li>'
        for key, _ in _rendered_sections(resolved)
    )
    return f'<nav class="toc"><p class="toc-title">Contents</p><ul>{items}</ul></nav>'


def _html_fmt_inventory_table(title: str, pairs: list, col_header: str) -> str:
    """Render a format string inventory as an HTML table."""
    groups, total, unique = _format_groups(pairs)
    parts = [
        f"<h4>{_esc(title)} ({total} total, {unique} unique)</h4>",
        _html_table(["Format String", "Count", col_header], _html_rows(_format_rows(groups))),
    ]
    return "\n".join(parts)


@dataclass
class _HtmlContext:
    model: SemanticModel
    resolved: dict
    config: dict
    include_dax: bool
    show_hidden: bool
    collected: dict
    refs: tuple


def _html_hidden_note(dax_expression: str, refs: tuple) -> list[str]:
    found = _find_hidden_references(dax_expression, *refs)
    if not found:
        return []
    parts = [f"{_code(display)} (in {_code(tbl)})" for display, tbl in found]
    return [f"<p>⚠ References hidden: {', '.join(parts)}</p>"]


def _html_overview(ctx: _HtmlContext) -> list[str]:
    return [
        _html_heading("overview"),
        _html_table(["Property", "Value"], _html_rows(_overview_rows(ctx.config, ctx.model)), "overview-table"),
    ]


def _html_data_sources(ctx: _HtmlContext) -> list[str]:
    loaded = ctx.collected["loaded"]
    support = ctx.collected["support"]
    staging = ctx.collected["staging"]
    body = [
        _html_heading("data_sources"),
        f'<p>{_esc(_model_summary(loaded, staging, support, ctx.model))}</p>',
    ]
    if loaded:
        body.append(_html_table(["Table", "Source Type", "Source"],
                                _html_rows(_source_rows(loaded, ctx.resolved, mark_hidden=True))))
    if support:
        body.append('<h3>Support Tables</h3>')
        body.append(_html_table(["Table", "Type"], _html_rows(_support_rows(support))))
    body.append('<h3>Not Loaded</h3>')
    if staging:
        body.append(_html_table(["Table", "Source Type", "Source"],
                                _html_rows(_source_rows(staging, ctx.resolved, mark_hidden=False))))
        staging_pairs = _column_format_pairs(staging)
        if staging_pairs:
            body.append(_html_fmt_inventory_table("Not Loaded Column Format Strings", staging_pairs, "Columns"))
    else:
        body.append('<p class="empty">None.</p>')
    return body


def _html_table_details(ctx: _HtmlContext) -> list[str]:
    body = [_html_heading("table_details")]
    detail_support = [
        t for t in ctx.collected["support"]
        if t.table_type in ("calc_group", "calculated", "field_parameter")
    ]
    if ctx.show_hidden:
        table_detail_tables = ctx.collected["loaded"] + detail_support
    else:
        table_detail_tables = ctx.collected["loaded_visible"] + detail_support
    for t in table_detail_tables:
        body.append(f'<h3>{_code(t.name)}</h3>')
        rs = get_table_source(t, ctx.resolved)
        if rs:
            for label, value in _source_detail_fields(rs):
                body.append(f'<p><strong>{_esc(label)}:</strong> {_md_value_html(value)}</p>')
        elif t.table_type == "calculated":
            body.append('<p><strong>Source:</strong> Calculated (DAX)</p>')
            if ctx.include_dax and t.dax_partition:
                body.append(_pre(t.dax_partition))
        elif t.table_type == "field_parameter":
            body.append('<p><strong>Source:</strong> Field Parameter</p>')
        elif t.table_type == "measures_only":
            body.append('<p><strong>Source:</strong> Measures only - no data source</p>')
        if t.is_hidden:
            body.append('<p><strong>Hidden:</strong> Yes</p>')
        if ctx.show_hidden:
            display_cols = [c for c in t.columns if not c.is_calculated]
        else:
            display_cols = [c for c in t.columns if not c.is_calculated and not c.is_hidden]
        if display_cols:
            body.append('<h4>Columns</h4>')
            body.append(_html_table(
                ["Column", "Type", "Format", "Summarize By", "Source Column", "Sort By", "Description", "Hidden"],
                _html_rows(_column_rows(display_cols))))
            key_cols = [c.name for c in display_cols if c.is_key]
            if key_cols:
                body.append('<p><strong>Key Column:</strong> '
                            + ", ".join(_code(k) for k in key_cols) + '</p>')
            cat_cols = [(c.name, c.data_category) for c in display_cols if c.data_category]
            if cat_cols:
                body.append('<p><strong>Data Categories:</strong> '
                            + ", ".join(f"{_code(n)} = {_esc(cat)}" for n, cat in cat_cols)
                            + '</p>')
        calc_cols = [c for c in t.columns if c.is_calculated]
        if calc_cols:
            body.append('<h4>Calculated Columns</h4>')
            for col in calc_cols:
                if ctx.include_dax and col.dax_expression:
                    body.append(f'<p><strong>{_code(col.name)}</strong></p>')
                    body.append(_pre(col.dax_expression))
                    body += _html_hidden_note(col.dax_expression, ctx.refs)
        if t.calculation_items:
            body.append('<h4>Calculation Items</h4>')
            body.append(_html_table(["Item", "Ordinal", "Format String"],
                                    _html_rows(_calc_item_rows(t.calculation_items))))
            body.append('<p class="section-note">Calculation items can be applied to any measure at report-build time (via <code>SELECTEDMEASURE()</code>). TMDL has no static record of which measures a given item is actually used with.</p>')
            if ctx.include_dax:
                for item in t.calculation_items:
                    body.append(f'<h4>{_code(item.name)}</h4>')
                    body.append(_pre(item.dax_expression))
        if ctx.show_hidden:
            display_measures = t.measures[:]
        else:
            display_measures = [m for m in t.measures if not m.is_hidden]
        if display_measures:
            body.append('<h4>Measures</h4>')
            body.append(_html_table(["Measure", "Format", "Description", "Hidden"],
                                    _html_rows(_table_measure_rows(display_measures))))
            if ctx.include_dax:
                for m in display_measures:
                    if not m.dax_expression.strip():
                        continue
                    body.append(f'<h4>{_code(m.name)}</h4>')
                    body.append(_pre(m.dax_expression))
                    body += _html_hidden_note(m.dax_expression, ctx.refs)
    return body


def _html_measures(ctx: _HtmlContext) -> list[str]:
    all_measures = ctx.collected["measures"]
    body = [_html_heading("measures")]
    if not all_measures:
        body.append('<p class="empty">No measures defined in this model.</p>')
    else:
        for folder, items in _measure_folders(all_measures):
            body.append(f'<h3>{_esc(folder)}</h3>')
            body.append(_html_table(["Measure", "Table", "Format", "Description"],
                                    _html_rows(_folder_measure_rows(items))))
            if ctx.include_dax:
                for _, m in items:
                    if not m.dax_expression.strip():
                        continue
                    body.append(f'<h4>{_code(m.name)}</h4>')
                    body.append(_pre(m.dax_expression))
        body.append(_html_fmt_inventory_table(
            "Measure Format Strings", _measure_format_pairs(all_measures), "Measures"
        ))
    column_pairs = _column_format_pairs(ctx.collected["loaded"] + ctx.collected["support"])
    if column_pairs:
        body.append(_html_fmt_inventory_table("Column Format Strings", column_pairs, "Columns"))
    return body


def _html_functions(ctx: _HtmlContext) -> list[str]:
    body = [_html_heading("functions")]
    if not ctx.model.functions:
        body.append('<p class="empty">No user-defined functions defined.</p>')
        return body
    body.append(_html_table(["Function", "Used By", "Description"], _html_rows(_function_rows(ctx.model))))
    if ctx.include_dax:
        for fn in ctx.model.functions:
            if not fn.expression.strip():
                continue
            body.append(f'<h4>{_code(fn.name)}</h4>')
            body.append(_pre(fn.expression))
    return body


def _html_relationships(ctx: _HtmlContext) -> list[str]:
    body = [_html_heading("relationships")]
    visible_rels = _visible_relationships(ctx.model)
    if not visible_rels:
        body.append('<p class="empty">No relationships defined in this model.</p>')
        return body
    active   = [r for r in visible_rels if r.is_active]
    inactive = [r for r in visible_rels if not r.is_active]
    if active:
        body.append(_html_table(
            ["From Table", "From Column", "To Table", "To Column", "Cardinality", "Cross Filter", "Security Filter"],
            _html_rows(_relationship_rows(active, with_cardinality=True))))
    if inactive:
        body.append('<h3>Inactive Relationships</h3>')
        body.append(_html_table(
            ["From Table", "From Column", "To Table", "To Column", "Cross Filter", "Security Filter"],
            _html_rows(_relationship_rows(inactive, with_cardinality=False))))
    return body


def _html_security_roles(ctx: _HtmlContext) -> list[str]:
    body = [_html_heading("security_roles")]
    if not ctx.model.security_roles:
        body.append('<p class="empty">No security roles defined.</p>')
        return body
    body.append(_html_table(["Role", "Table", "Filter", "Dynamic"], _html_rows(_role_rows(ctx.model))))
    return body


def _html_m_parameters(ctx: _HtmlContext) -> list[str]:
    body = [_html_heading("m_parameters")]
    if not ctx.model.m_parameters:
        body.append('<p class="empty">No M parameters defined.</p>')
        return body
    body.append(_html_table(["Parameter", "Type", "Value", "Used By"],
                            _html_rows(_parameter_rows(ctx.model, dash_blank_value=False))))
    body.append('<p class="section-note">Only direct parameter references in connector calls are shown.</p>')
    return body


def _html_unresolved(ctx: _HtmlContext) -> list[str]:
    rows = _unresolved_rows(ctx.resolved)
    if not rows:
        return []
    return [
        _html_heading("unresolved"),
        '<p>The following sources could not be resolved statically.</p>',
        _html_table(["Expression", "Reason"], _html_rows(rows)),
    ]


def _html_statistics(ctx: _HtmlContext) -> list[str]:
    c = ctx.collected
    rows = _statistics_rows(ctx.model, c["loaded_visible"], c["support"], c["staging"], c["hidden_tables"])
    return [
        _html_heading("statistics"),
        _html_table(["Category", "Count", "Items"], _html_rows(rows)),
    ]


_HTML_SECTION_RENDERERS = {
    "overview":       _html_overview,
    "data_sources":   _html_data_sources,
    "table_details":  _html_table_details,
    "measures":       _html_measures,
    "functions":      _html_functions,
    "relationships":  _html_relationships,
    "security_roles": _html_security_roles,
    "m_parameters":   _html_m_parameters,
    "unresolved":     _html_unresolved,
    "statistics":     _html_statistics,
}


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
    ctx = _HtmlContext(
        model=model,
        resolved=resolved,
        config=config,
        include_dax=include_dax,
        show_hidden=show_hidden,
        collected=collected,
        refs=_build_hidden_reference_map(model),
    )

    body = [f'<div class="container">',
            f'<h1>{_esc(report_name)}</h1>',
            '<div class="subtitle">Generated by tmdl-lens</div>',
            _html_contents(resolved)]
    for key, _ in _rendered_sections(resolved):
        body += _HTML_SECTION_RENDERERS[key](ctx)
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

    renderers = {
        "overview":       lambda: _overview_section(config, model),
        "data_sources":   lambda: _data_sources_section(loaded, staging, support, resolved, model),
        "table_details":  lambda: _table_details_section(loaded, support, resolved, include_dax, ref_tables, ref_measures, ref_columns, show_hidden),
        "measures":       lambda: _measures_section(collected["measures"], include_dax),
        "functions":      lambda: _functions_section(model, include_dax),
        "relationships":  lambda: _relationships_section(model),
        "security_roles": lambda: _security_roles_section(model),
        "m_parameters":   lambda: _m_parameters_section(model),
        "unresolved":     lambda: _unresolved_section(resolved),
        "statistics":     lambda: _statistics_section(model, loaded_visible, support, staging, collected["hidden_tables"]),
    }

    sections = [f"# {report_name}\n", _md_contents(resolved)]
    for key, _ in _rendered_sections(resolved):
        sections.append(renderers[key]())

    sections.append("*Generated by tmdl-lens*\n")

    return "\n".join(sections)


@dataclass
class _TextContext:
    model: SemanticModel
    resolved: dict
    config: dict
    include_dax: bool
    show_hidden: bool
    collected: dict
    refs: tuple


def _text_flat(value) -> str:
    return str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _text_plain(value: str) -> str:
    return re.sub(r"`([^`]*)`", r"\1", str(value)).replace("⚠", "!")


def _text_cell(cell) -> str:
    if isinstance(cell, _Code):
        return _text_flat(f"{cell.text}{cell.suffix}")
    if isinstance(cell, _CodeList):
        return _text_flat(", ".join(cell.names)) if cell.names else "-"
    if isinstance(cell, _CodeRefs):
        if not cell.pairs:
            return "-"
        return _text_flat(", ".join(f"{c} ({p})" for c, p in cell.pairs))
    return _text_flat(cell)


def _text_table(headers: list[str], rows: list) -> list[str]:
    cells = [[_text_cell(cell) for cell in row] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]

    def line(values):
        return "  ".join(v.ljust(w) for v, w in zip(values, widths)).rstrip()

    return [line(headers), line(["-" * w for w in widths]), *(line(r) for r in cells)]


def _text_underlined(title: str, char: str) -> list[str]:
    return [title, char * len(title)]


def _text_heading(key: str) -> list[str]:
    title = _SECTION_TITLE[key]
    if key == "unresolved":
        title = f"! {title}"
    return _text_underlined(title, "-")


def _text_dax(expression: str) -> list[str]:
    return [("    " + line).rstrip() for line in expression.split("\n")]


def _text_hidden_note(dax_expression: str, refs: tuple) -> list[list[str]]:
    note = _hidden_reference_note(_find_hidden_references(dax_expression, *refs))
    return [[_text_plain(note)]] if note else []


def _text_inventory(pairs: list, heading: str, items_header: str) -> list[list[str]]:
    if not pairs:
        return []
    groups, total, unique = _format_groups(pairs)
    return [
        [f"{heading} ({total} total, {unique} unique)"],
        _text_table(["Format String", "Count", items_header], _format_rows(groups)),
    ]


def _text_overview(ctx: _TextContext) -> list[list[str]]:
    return [
        _text_heading("overview"),
        _text_table(["Property", "Value"], _overview_rows(ctx.config, ctx.model)),
    ]


def _text_data_sources(ctx: _TextContext) -> list[list[str]]:
    loaded = ctx.collected["loaded"]
    support = ctx.collected["support"]
    staging = ctx.collected["staging"]
    paras = [
        _text_heading("data_sources"),
        [_model_summary(loaded, staging, support, ctx.model)],
    ]
    if loaded:
        paras.append(_text_table(["Table", "Source Type", "Source"],
                                 _source_rows(loaded, ctx.resolved, mark_hidden=True)))
    else:
        paras.append(["No loaded tables found."])
    if support:
        paras.append(_text_underlined("Support Tables", "~"))
        paras.append(_text_table(["Table", "Type"], _support_rows(support)))
    paras.append(_text_underlined("Not Loaded", "~"))
    if staging:
        paras.append([
            "These tables have enableLoad = false and are not visible in the report.",
            "They are typically used as intermediate query steps.",
        ])
        paras.append(_text_table(["Table", "Source Type", "Source"],
                                 _source_rows(staging, ctx.resolved, mark_hidden=False)))
        paras += _text_inventory(_column_format_pairs(staging), "Not Loaded Table Format Strings Used", "Columns")
    else:
        paras.append(["None."])
    return paras


def _text_table_block(table: Table, ctx: _TextContext) -> list[list[str]]:
    paras = [_text_underlined(table.name, "~")]
    rs = get_table_source(table, ctx.resolved)
    source_lines = []
    dax_partition = ""
    if rs:
        source_lines = [f"{_text_plain(label)}: {_text_plain(value)}" for label, value in _source_detail_fields(rs)]
    elif table.table_type == "calculated":
        source_lines = ["Source: Calculated (DAX)"]
        if ctx.include_dax and table.dax_partition:
            dax_partition = table.dax_partition
    elif table.table_type == "field_parameter":
        source_lines = ["Source: Field Parameter"]
    elif table.table_type == "measures_only":
        source_lines = ["Source: Measures only - no data source"]
    paras.append(source_lines)
    if dax_partition:
        paras.append(_text_dax(dax_partition))
    flags = []
    if not table.is_loaded:
        flags.append("! Not loaded (enableLoad = false).")
    if table.is_hidden:
        flags.append("Hidden: Yes")
    paras.append(flags)

    all_cols = [c for c in table.columns if not c.is_calculated]
    display_cols = all_cols if ctx.show_hidden else [c for c in all_cols if not c.is_hidden]
    if display_cols:
        paras.append(["Columns"])
        paras.append(_text_table(
            ["Column", "Type", "Format", "Summarize By", "Source Column", "Sort By", "Description", "Hidden"],
            _column_rows(display_cols)))
        extra = []
        key_cols = [c.name for c in display_cols if c.is_key]
        if key_cols:
            extra.append("Key Column: " + ", ".join(key_cols))
        cat_cols = [(c.name, c.data_category) for c in display_cols if c.data_category]
        if cat_cols:
            extra.append("Data Categories: " + ", ".join(f"{name} = {cat}" for name, cat in cat_cols))
        paras.append(extra)

    calc_cols = [c for c in table.columns if c.is_calculated]
    if calc_cols:
        paras.append(["Calculated Columns"])
        for col in calc_cols:
            paras.append([f"- {col.name}"])
            if ctx.include_dax and col.dax_expression:
                paras.append(_text_dax(col.dax_expression))
                paras += _text_hidden_note(col.dax_expression, ctx.refs)

    if table.calculation_items:
        paras.append(["Calculation Items"])
        paras.append(_text_table(["Item", "Ordinal", "Format String"], _calc_item_rows(table.calculation_items)))
        paras.append([
            "Calculation items can be applied to any measure at report-build time "
            "(via SELECTEDMEASURE()). TMDL has no static record of which measures "
            "a given item is actually used with."
        ])
        if ctx.include_dax:
            paras.append(["Item DAX"])
            for item in table.calculation_items:
                paras.append([item.name])
                paras.append(_text_dax(item.dax_expression))

    display_measures = table.measures[:] if ctx.show_hidden else [m for m in table.measures if not m.is_hidden]
    if display_measures:
        paras.append(["Measures"])
        paras.append(_text_table(["Measure", "Format", "Description", "Hidden"], _table_measure_rows(display_measures)))
        if ctx.include_dax:
            paras.append(["Measure DAX"])
            for m in display_measures:
                if not m.dax_expression.strip():
                    continue
                paras.append([m.name])
                paras.append(_text_dax(m.dax_expression))
                paras += _text_hidden_note(m.dax_expression, ctx.refs)
    return paras


def _text_table_details(ctx: _TextContext) -> list[list[str]]:
    loaded = ctx.collected["loaded"]
    support = ctx.collected["support"]
    detail_support = [
        t for t in support
        if t.table_type in ("calc_group", "calculated", "field_parameter")
    ]
    if ctx.show_hidden:
        tables = loaded + detail_support
    else:
        tables = ctx.collected["loaded_visible"] + detail_support
    paras = [_text_heading("table_details")]
    if not tables:
        paras.append(["No loaded tables."])
    for t in tables:
        paras += _text_table_block(t, ctx)
    paras += _text_inventory(_column_format_pairs(loaded + support), "Format Strings Used", "Columns")
    return paras


def _text_measures(ctx: _TextContext) -> list[list[str]]:
    measures = ctx.collected["measures"]
    paras = [_text_heading("measures")]
    if not measures:
        paras.append(["No measures defined in this model."])
        return paras
    for folder, items in _measure_folders(measures):
        paras.append(_text_underlined(folder, "~"))
        paras.append(_text_table(["Measure", "Table", "Format", "Description"], _folder_measure_rows(items)))
        if ctx.include_dax:
            for _, m in items:
                if not m.dax_expression.strip():
                    continue
                paras.append([m.name])
                paras.append(_text_dax(m.dax_expression))
    paras += _text_inventory(_measure_format_pairs(measures), "Format Strings Used", "Measures")
    return paras


def _text_functions(ctx: _TextContext) -> list[list[str]]:
    paras = [_text_heading("functions")]
    if not ctx.model.functions:
        paras.append(["No user-defined functions defined."])
        return paras
    paras.append(_text_table(["Function", "Used By", "Description"], _function_rows(ctx.model)))
    if ctx.include_dax:
        for fn in ctx.model.functions:
            if not fn.expression.strip():
                continue
            paras.append([fn.name])
            paras.append(_text_dax(fn.expression))
    return paras


def _text_relationships(ctx: _TextContext) -> list[list[str]]:
    paras = [_text_heading("relationships")]
    visible = _visible_relationships(ctx.model)
    if not visible:
        paras.append(["No relationships defined in this model."])
        return paras
    active = [r for r in visible if r.is_active]
    inactive = [r for r in visible if not r.is_active]
    if active:
        paras.append(_text_table(
            ["From Table", "From Column", "To Table", "To Column", "Cardinality", "Cross Filter", "Security Filter"],
            _relationship_rows(active, with_cardinality=True)))
    if inactive:
        paras.append(_text_underlined("Inactive Relationships", "~"))
        paras.append(_text_table(
            ["From Table", "From Column", "To Table", "To Column", "Cross Filter", "Security Filter"],
            _relationship_rows(inactive, with_cardinality=False)))
    return paras


def _text_security_roles(ctx: _TextContext) -> list[list[str]]:
    paras = [_text_heading("security_roles")]
    if not ctx.model.security_roles:
        paras.append(["No security roles defined."])
        return paras
    paras.append(_text_table(["Role", "Table", "Filter", "Dynamic"], _role_rows(ctx.model)))
    return paras


def _text_m_parameters(ctx: _TextContext) -> list[list[str]]:
    paras = [_text_heading("m_parameters")]
    if not ctx.model.m_parameters:
        paras.append(["No M parameters defined."])
        return paras
    paras.append(_text_table(["Parameter", "Type", "Value", "Used By"],
                             _parameter_rows(ctx.model, dash_blank_value=True)))
    paras.append([
        "Only direct parameter references in connector calls are shown.",
        "Parameters used in conditional logic or computed expressions may not appear here.",
    ])
    return paras


def _text_unresolved(ctx: _TextContext) -> list[list[str]]:
    rows = _unresolved_rows(ctx.resolved)
    if not rows:
        return []
    return [
        _text_heading("unresolved"),
        [
            "The following sources could not be resolved statically.",
            "Use tmdl-lens to provide a manual label for each.",
        ],
        _text_table(["Expression", "Reason"], rows),
    ]


def _text_statistics(ctx: _TextContext) -> list[list[str]]:
    c = ctx.collected
    rows = _statistics_rows(ctx.model, c["loaded_visible"], c["support"], c["staging"], c["hidden_tables"])
    return [_text_heading("statistics"), _text_table(["Category", "Count", "Items"], rows)]


_TEXT_SECTION_RENDERERS = {
    "overview":       _text_overview,
    "data_sources":   _text_data_sources,
    "table_details":  _text_table_details,
    "measures":       _text_measures,
    "functions":      _text_functions,
    "relationships":  _text_relationships,
    "security_roles": _text_security_roles,
    "m_parameters":   _text_m_parameters,
    "unresolved":     _text_unresolved,
    "statistics":     _text_statistics,
}


def generate_text(
    model: SemanticModel,
    resolved: dict[str, ResolvedSource],
    config: dict,
) -> str:
    report_name = config.get("report_name", model.report_name)
    include_dax = config.get("include_dax", True)
    show_hidden = config.get("show_hidden", True)

    collected = _collect(model, show_hidden)
    model = collected["model"]
    ctx = _TextContext(
        model=model,
        resolved=resolved,
        config=config,
        include_dax=include_dax,
        show_hidden=show_hidden,
        collected=collected,
        refs=_build_hidden_reference_map(model),
    )

    paras = [_text_underlined(report_name, "=")]
    for key, _ in _SECTIONS:
        paras += _TEXT_SECTION_RENDERERS[key](ctx)
    paras.append(["Generated by tmdl-lens"])
    paras = [p for p in paras if any(p)]
    return "\n\n".join("\n".join(p) for p in paras) + "\n"
