"""
json_writer.py - Typed JSON output for tmdl-lens.

Builds a deterministic JSON document from the parsed SemanticModel and the
resolved sources, not from the rendered text. Every list of named items is
sorted by name and no timestamp or tool version is written, so the same
model gives the same bytes on every machine. The layout is described by
docs/tmdl-lens-output.schema.json and versioned by schema_version.
"""

import json

from tmdl_lens.readme_generator import (
    _build_function_usage_map,
    _build_hidden_reference_map,
    _build_param_usage_map,
    _collect,
    _find_hidden_references,
    _visible_relationships,
)
from tmdl_lens.source_resolver import ResolvedSource, get_table_source
from tmdl_lens.tmdl_parser import SemanticModel

SCHEMA_VERSION = "1.0"

SOURCE_TYPES = (
    "connector", "table_combine", "hardcoded", "embedded",
    "generated", "dynamic", "function_def", "scalar_helper",
)

_SUPPORT_KIND = {
    "calculated":      "calculated",
    "field_parameter": "field_parameter",
    "measures_only":   "measures_only",
    "calc_group":      "calculation_group",
}

_CARDINALITY = {
    "One-to-Many":  "one_to_many",
    "Many-to-One":  "many_to_one",
    "Many-to-Many": "many_to_many",
    "One-to-One":   "one_to_one",
}

_CROSS_FILTER = {
    "onedirection":   "one_direction",
    "bothdirections": "both_directions",
    "automatic":      "automatic",
}

_SECURITY_FILTER = {
    "onedirection":   "one_direction",
    "bothdirections": "both_directions",
    "none":           "none",
}

_DETAIL_FIELDS = (
    ("server", "server"),
    ("database", "database"),
    ("schema", "schema"),
    ("table", "table_or_view"),
    ("dsn", "dsn"),
    ("sharepoint_url", "sharepoint_url"),
    ("file", "file_name"),
    ("sheet", "sheet_name"),
    ("url", "url"),
    ("account", "account"),
    ("container", "container"),
    ("entity", "entity"),
    ("workspace_id", "workspace_id"),
    ("dataflow_id", "dataflow_id"),
    ("native_query", "native_query"),
)


def _text(value):
    if value is None:
        return None
    value = str(value)
    return value if value.strip() else None


def _int_or_none(value):
    value = str(value or "").strip()
    return int(value) if value.isdigit() else None


def _by_name(items: list) -> list:
    return sorted(items, key=lambda item: item["name"])


def _combine_lookup(model: SemanticModel) -> dict:
    lookup = {e.name: list(e.combine_sources) for e in model.source_expressions}
    for t in model.tables:
        if t.inline_source is not None:
            lookup[t.name] = list(t.inline_source.combine_sources)
    return lookup


def _source(rs: ResolvedSource, combine_lookup: dict):
    if rs is None:
        return None
    if rs.unresolved or rs.source_type not in SOURCE_TYPES:
        reason = rs.unresolved_reason if rs.unresolved else f"unsupported source type: {rs.source_type}"
        return {"resolved": False, "reason": reason}
    source = {
        "resolved": True,
        "type": rs.source_type,
        "connector": (
            {"namespace": rs.connector_namespace, "function": rs.connector_function}
            if rs.source_type == "connector" else None
        ),
        "details": {
            key: getattr(rs, attr) for key, attr in _DETAIL_FIELDS if getattr(rs, attr)
        },
        "physical_tables": sorted(
            (
                {"schema": _text(ref.schema), "table": ref.table, "via": ref.source}
                for ref in rs.physical_tables
            ),
            key=lambda ref: (ref["schema"] or "", ref["table"], ref["via"]),
        ),
        "chain": list(rs.chain),
    }
    if rs.source_type == "table_combine":
        terminal = rs.chain[-1] if rs.chain else rs.expression_name
        source["combine_sources"] = sorted(set(combine_lookup.get(terminal, [])))
    return source


def _columns(table, include_dax: bool) -> list:
    return _by_name([
        {
            "name": c.name,
            "data_type": c.data_type,
            "is_calculated": c.is_calculated,
            "is_hidden": c.is_hidden,
            "is_key": c.is_key,
            "format_string": _text(c.format_string),
            "summarize_by": _text(c.summarize_by),
            "source_column": _text(c.source_column),
            "sort_by_column": _text(c.sort_by_column),
            "data_category": _text(c.data_category),
            "description": _text(c.description),
            "expression": _text(c.dax_expression) if include_dax and c.is_calculated else None,
        }
        for c in table.columns
    ])


def _measures(table, include_dax: bool) -> list:
    return _by_name([
        {
            "name": m.name,
            "display_folder": _text(m.display_folder),
            "format_string": _text(m.format_string),
            "description": _text(m.description),
            "is_hidden": m.is_hidden,
            "expression": _text(m.dax_expression) if include_dax else None,
        }
        for m in table.measures
    ])


def _calculation_items(table, include_dax: bool) -> list:
    return _by_name([
        {
            "name": i.name,
            "ordinal": i.ordinal,
            "format_string_expression": _text(i.format_string_expression),
            "expression": _text(i.dax_expression) if include_dax else None,
        }
        for i in table.calculation_items
    ])


def _tables(collected: dict, resolved: dict, combine_lookup: dict, include_dax: bool) -> list:
    kinds = {}
    for t in collected["loaded"]:
        kinds[t.name] = "loaded"
    for t in collected["support"]:
        kinds[t.name] = _SUPPORT_KIND[t.table_type]
    for t in collected["staging"]:
        kinds[t.name] = "not_loaded"
    return _by_name([
        {
            "name": t.name,
            "kind": kinds[t.name],
            "is_hidden": t.is_hidden,
            "description": _text(t.description),
            "source": _source(get_table_source(t, resolved), combine_lookup),
            "expression": _text(t.dax_partition) if include_dax else None,
            "columns": _columns(t, include_dax),
            "measures": _measures(t, include_dax),
            "calculation_items": _calculation_items(t, include_dax),
        }
        for t in collected["tables"]
    ])


def _relationships(model: SemanticModel) -> list:
    rows = [
        {
            "from_table": r.from_table,
            "from_column": r.from_column,
            "to_table": r.to_table,
            "to_column": r.to_column,
            "is_active": r.is_active,
            "cardinality": _CARDINALITY.get(r.cardinality),
            "cross_filter": _CROSS_FILTER.get(str(r.cross_filtering_behavior).lower()),
            "security_filter": _SECURITY_FILTER.get(str(r.security_filtering_behavior).lower()),
        }
        for r in _visible_relationships(model)
    ]
    return sorted(rows, key=lambda r: (r["from_table"], r["from_column"], r["to_table"], r["to_column"], r["is_active"]))


def _expressions(model: SemanticModel, resolved: dict, combine_lookup: dict) -> list:
    return _by_name([
        {
            "name": e.name,
            "query_group": _text(e.query_group),
            "source": _source(resolved.get(e.name), combine_lookup),
        }
        for e in model.source_expressions
    ])


def _parameters(model: SemanticModel) -> list:
    usage = _build_param_usage_map(model)
    return _by_name([
        {
            "name": p.name,
            "type": p.param_type,
            "value": _text(p.value),
            "used_by": sorted(usage.get(p.name, [])),
        }
        for p in model.m_parameters
    ])


def _functions(model: SemanticModel, include_dax: bool) -> list:
    usage = _build_function_usage_map(model)
    return _by_name([
        {
            "name": fn.name,
            "description": _text(fn.description),
            "expression": _text(fn.expression) if include_dax else None,
            "used_by": sorted(
                ({"measure": measure, "table": table} for measure, table in usage.get(fn.name, [])),
                key=lambda ref: (ref["measure"], ref["table"]),
            ),
        }
        for fn in model.functions
    ])


def _roles(model: SemanticModel) -> list:
    return _by_name([
        {
            "name": role.name,
            "dynamic_function": _text(role.dynamic_function) if role.is_dynamic else None,
            "filters": sorted(
                ({"table": tf.table, "expression": tf.dax_filter} for tf in role.table_filters),
                key=lambda f: (f["table"], f["expression"]),
            ),
        }
        for role in model.security_roles
    ])


def _warnings(model: SemanticModel, resolved: dict) -> list:
    warnings = [
        {"code": "unresolved_source", "object": rs.expression_name, "table": None, "detail": rs.unresolved_reason}
        for rs in resolved.values() if rs.unresolved
    ]
    refs = _build_hidden_reference_map(model)
    for t in model.tables:
        objects = [(m.name, m.dax_expression) for m in t.measures]
        objects += [(c.name, c.dax_expression) for c in t.columns if c.is_calculated]
        for name, dax in objects:
            for display, _ in _find_hidden_references(dax, *refs):
                warnings.append({"code": "hidden_reference", "object": name, "table": t.name, "detail": display})
    return sorted(warnings, key=lambda w: (w["code"], w["table"] or "", w["object"], w["detail"]))


def generate_json(
    model: SemanticModel,
    resolved: dict[str, ResolvedSource],
    config: dict,
) -> str:
    include_dax = config.get("include_dax", True)
    collected = _collect(model, True)
    filtered = collected["model"]
    combine_lookup = _combine_lookup(model)

    document = {
        "schema_version": SCHEMA_VERSION,
        "report": {
            "name": config.get("report_name", model.report_name),
            "owner": _text(config.get("owner")),
            "team": _text(config.get("team")),
            "refresh_schedule": _text(config.get("refresh_schedule")),
        },
        "model": {
            "culture": _text(model.model_culture),
            "compatibility_level": _int_or_none(model.database_compatibility_level),
            "data_source_version": _text(model.model_data_source_version),
        },
        "tables": _tables(collected, resolved, combine_lookup, include_dax),
        "relationships": _relationships(filtered),
        "expressions": _expressions(model, resolved, combine_lookup),
        "parameters": _parameters(model),
        "functions": _functions(filtered, include_dax),
        "roles": _roles(model),
        "warnings": _warnings(filtered, resolved),
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
