"""
source_resolver.py - Source resolution for tmdl-lens.

Takes the raw SourceExpression list from tmdl_parser and resolves:
  Tier 1  Direct source connectors - already fully classified by the parser.
  Tier 2  Derived expressions, parameter references, custom function calls.
          These are followed one level and resolved to their root source.
  Tier 3  Dynamic M (string concatenation, runtime variables).
          Flagged as unresolvable; caller may offer manual override.

Also resolves inline_source on Table objects, building full -> chains.

Produces a flat dict  { table_name_or_expression_name: ResolvedSource }
used by the README generator.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from tmdl_lens.tmdl_parser import SourceExpression, MParameter


# ---------------------------------------------------------------------------
# ResolvedSource - the final output of resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolvedSource:
    expression_name: str
    source_type: str
    resolution_tier: int = 1
    label: str = ""

    # Connector identity (populated when source_type == "connector")
    connector_namespace: str = ""
    connector_function: str = ""
    is_native_query: bool = False

    # Dataflow
    workspace_id: str = ""
    dataflow_id: str = ""
    entity: str = ""

    # SQL
    server: str = ""
    database: str = ""
    schema: str = ""
    table_or_view: str = ""
    native_query: str = ""

    # ODBC
    dsn: str = ""

    # File / SharePoint
    sharepoint_url: str = ""
    file_name: str = ""
    sheet_name: str = ""

    # Web / OData
    url: str = ""

    # Azure Storage
    account: str = ""
    container: str = ""

    physical_tables: list = field(default_factory=list)

    # Derivation chain
    derived_from: str = ""
    chain: list = field(default_factory=list)

    # Unresolved
    unresolved: bool = False
    unresolved_reason: str = ""

    # Manual override label
    manual_label: str = ""


# ---------------------------------------------------------------------------
# Terminal source types - chain walking stops here
# ---------------------------------------------------------------------------

_TERMINAL_TYPES = {
    "connector",
    "hardcoded", "embedded",
    "dynamic", "unresolved",
    "function_def", "scalar_helper",
    "table_combine", "generated",
}

# (namespace, function) -> short display label for the Source Type column
# and for the resolver label builder. Single shared source of truth used by
# both source_resolver and readme_generator. Unknown connectors fall back to
# "{namespace} -> {function}" (resolver) / "{namespace} {function}" (renderer)
# with whatever detail fields were captured.
CONNECTOR_TYPE_LABEL = {
    ("PowerBI", "Dataflows"):             "Power BI Dataflow",
    ("PowerPlatform", "Dataflows"):        "Power Platform Dataflow",
    ("Sql", "Database"):                  "SQL",
    ("AzureSQL", "Database"):             "SQL",
    ("AmazonRedshift", "Database"):       "SQL",
    ("Odbc", "DataSource"):               "ODBC",
    ("SharePoint", "Files"):              "SharePoint Files",
    ("SharePoint", "Tables"):             "SharePoint List",
    ("SharePoint", "Contents"):           "SharePoint Contents",
    ("Excel", "Workbook"):                "Excel",
    ("Csv", "Document"):                  "CSV (local)",
    ("Web", "Contents"):                  "Web API",
    ("OData", "Feed"):                    "OData",
    ("SmartsheetGlobal", "Contents"):     "Smartsheet",
    ("Smartsheet", "Tables"):             "Smartsheet",
    ("Dataverse", "Feed"):                "Dataverse",
    ("AzureDevOps", "Contents"):          "Azure DevOps",
    ("Dynamics365", "FinanceAndOperations"): "Dynamics 365 F&O",
    ("GoogleSheets", "Contents"):         "Google Sheets",
    ("QuickBooks", "Contents"):           "QuickBooks",
    ("GitHub", "Contents"):               "GitHub",
    ("Oracle", "Database"):               "Oracle",
    ("MySql", "Database"):                "MySQL",
    ("PostgreSQL", "Database"):           "PostgreSQL",
    ("DB2", "Database"):                  "IBM Db2",
    ("SapHana", "Database"):              "SAP HANA",
    ("Snowflake", "Databases"):           "Snowflake",
    ("Teradata", "Database"):             "Teradata",
    ("Databricks", "Catalogs"):           "Databricks",
    ("Databricks", "Contents"):           "Databricks",
    ("Salesforce", "Data"):               "Salesforce",
    ("Salesforce", "Reports"):            "Salesforce",
    ("AzureStorage", "Blobs"):            "Azure Blob Storage",
    ("AzureStorage", "BlobContents"):     "Azure Blob Storage",
    ("AzureStorage", "Table"):            "Azure Table Storage",
    ("AzureStorage", "DataLake"):         "Azure Data Lake Storage",
    ("AzureStorage", "DataLakeContents"): "Azure Data Lake Storage",
}


# ---------------------------------------------------------------------------
# Label builders
# ---------------------------------------------------------------------------

def _build_label(expr: SourceExpression, params: dict[str, str]) -> str:
    t = expr.source_type

    # ── All connectors (single branch) ──────────────────────────────────
    if t == "connector":
        ns   = expr.connector_namespace
        func = expr.connector_function

        # 1. Native query SQL (must be checked before generic SQL)
        if expr.is_native_query and (ns, func) in (
            ("Sql", "Database"), ("AzureSQL", "Database"), ("AmazonRedshift", "Database"),
        ):
            server = _resolve_param(expr.server, params)
            db     = _resolve_param(expr.database, params)
            return f"SQL (native query) -> {server} -> {db}"

        # 2. Dataflows
        if (ns, func) in (("PowerBI", "Dataflows"), ("PowerPlatform", "Dataflows")):
            connector = "Power BI Dataflow" if (ns, func) == ("PowerBI", "Dataflows") else "Power Platform Dataflow"
            entity = expr.entity or "?"
            return f"{connector} -> {entity}"

        # 3. SQL (generic)
        if (ns, func) in (("Sql", "Database"), ("AzureSQL", "Database"), ("AmazonRedshift", "Database")):
            server = _resolve_param(expr.server, params)
            db     = _resolve_param(expr.database, params)
            if expr.schema and expr.table_or_view:
                return f"SQL -> {server} -> {db} -> {expr.schema}.{expr.table_or_view}"
            return f"SQL -> {server} -> {db}"

        # 4. ODBC
        if (ns, func) == ("Odbc", "DataSource"):
            dsn = expr.dsn or "?"
            tbl = f" -> {expr.schema}.{expr.table_or_view}" if expr.table_or_view else ""
            return f"ODBC -> {dsn}{tbl}"

        # 5. SharePoint Files
        if (ns, func) == ("SharePoint", "Files"):
            fn = f" -> {expr.file_name}" if expr.file_name else ""
            return f"SharePoint Files -> {expr.sharepoint_url}{fn}"

        # 6. SharePoint List
        if (ns, func) == ("SharePoint", "Tables"):
            lst = f" -> {expr.table_or_view}" if expr.table_or_view else ""
            return f"SharePoint List -> {expr.sharepoint_url}{lst}"

        if (ns, func) == ("SharePoint", "Contents"):
            return f"SharePoint Contents -> {expr.sharepoint_url}"

        # 7. Excel (SharePoint)
        if (ns, func) == ("Excel", "Workbook"):
            sheet = f" -> {expr.sheet_name}" if expr.sheet_name else ""
            if expr.file_name:
                return f"Excel (local) -> {expr.file_name}{sheet}"
            elif expr.url:
                return f"Excel (SharePoint) -> {expr.url}{sheet}"
            elif expr.sheet_name:
                return f"Excel (SharePoint) -> [dynamic] -> {expr.sheet_name}"
            else:
                return "Excel (SharePoint) -> [dynamic]"

        # 8. CSV (local)
        if (ns, func) == ("Csv", "Document"):
            return f"CSV (local) -> {expr.file_name}"

        # 9. Web API
        if (ns, func) == ("Web", "Contents"):
            return f"Web API -> {expr.url}"

        # 10. OData
        if (ns, func) == ("OData", "Feed"):
            tbl = f" -> {expr.table_or_view}" if expr.table_or_view else ""
            return f"OData -> {expr.url}{tbl}"

        # 11. Smartsheet
        if (ns, func) in (("SmartsheetGlobal", "Contents"), ("Smartsheet", "Tables")):
            region = f" ({expr.url})" if expr.url else ""
            return f"Smartsheet{region}"

        # 12. Dataverse
        if (ns, func) == ("Dataverse", "Feed"):
            return f"Dataverse -> {expr.url or '?'}"

        # 13. Named platform connectors with populated detail
        friendly = CONNECTOR_TYPE_LABEL.get((ns, func))
        if friendly:
            if expr.url:
                return f"{friendly} -> {expr.url}"
            if expr.server and expr.database:
                return f"{friendly} -> {expr.server} -> {expr.database}"
            if expr.account and expr.container:
                return f"{friendly} -> {expr.account} -> {expr.container}"
            if expr.account:
                return f"{friendly} -> {expr.account}"
            if expr.entity:
                return f"{friendly} -> {expr.entity}"
            return friendly

        # 14. Unknown / new connector - show whatever detail we have
        #     with a generic "{namespace} -> {function}" fallback
        generic_name = f"{ns} -> {func}"
        if expr.server and expr.database:
            return f"{generic_name} -> {expr.server} -> {expr.database}"
        if expr.account and expr.container:
            return f"{generic_name} -> {expr.account} -> {expr.container}"
        if expr.account:
            return f"{generic_name} -> {expr.account}"
        if expr.url:
            return f"{generic_name} -> {expr.url}"
        if expr.entity:
            return f"{generic_name} -> {expr.entity}"
        if expr.sharepoint_url:
            return f"{generic_name} -> {expr.sharepoint_url}"
        if expr.dsn:
            return f"{generic_name} -> {expr.dsn}"
        return generic_name

    # ── Non-connector branches (unchanged) ─────────────────────────────

    if t == "embedded":
        return "Embedded data"

    if t == "table_combine":
        sources = ", ".join(expr.combine_sources) if expr.combine_sources else "?"
        return f"Combines: {sources}"

    if t == "hardcoded":
        return "Hardcoded (inline M)"

    if t == "dynamic":
        return "Dynamic M (runtime)"

    if t in ("function_def", "scalar_helper"):
        return t.replace("_", " ").title()

    return t.replace("_", " ").title()


def _resolve_param(value: str, params: dict[str, str]) -> str:
    if value.startswith("[param:") and value.endswith("]"):
        param_name = value[7:-1]
        return params.get(param_name, value)
    return value


# ---------------------------------------------------------------------------
# Chain label builder
# ---------------------------------------------------------------------------

def _build_chain_label(chain: list[str], terminal_label: str) -> str:
    if not chain:
        return terminal_label
    return " -> ".join(chain) + " -> " + terminal_label


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------

def resolve_sources(
    source_expressions: list[SourceExpression],
    m_parameters: list[MParameter],
    tables: list = None,
    manual_overrides: Optional[dict[str, str]] = None,
) -> dict[str, ResolvedSource]:
    manual_overrides = manual_overrides or {}
    tables = tables or []
    params: dict[str, str] = {p.name: p.value for p in m_parameters}
    expr_map: dict[str, SourceExpression] = {e.name: e for e in source_expressions}

    inline_map: dict[str, SourceExpression] = {}
    for tbl in tables:
        if tbl.inline_source is not None:
            inline_map[tbl.name] = tbl.inline_source
    table_ref = {t.name: t.source_ref for t in tables if t.source_ref}
    model_table_names = {t.name for t in tables}

    resolved: dict[str, ResolvedSource] = {}

    # Pass 1: resolve all terminal expressions from expressions.tmdl
    for expr in source_expressions:
        if expr.source_type in _TERMINAL_TYPES:
            rs = _from_expr(expr, params, tier=1)
            if expr.name in manual_overrides:
                rs.manual_label = manual_overrides[expr.name]
                rs.label        = manual_overrides[expr.name]
            resolved[expr.name] = rs

    # Pass 2: resolve derived / custom_function from expressions.tmdl
    max_passes = 10
    deferred: dict[str, SourceExpression] = {}
    for _ in range(max_passes):
        unresolved_tier2 = [
            e for e in source_expressions
            if e.name not in resolved and e.source_type in ("derived", "custom_function")
        ]
        if not unresolved_tier2:
            break
        for expr in unresolved_tier2:
            if expr.source_type == "derived":
                parent_name = expr.derived_from
                scalar_rs = _scalar_parent_resolution(expr.name, expr, resolved, params)
                if scalar_rs is not None:
                    resolved[expr.name] = scalar_rs
                elif parent_name in resolved:
                    resolved[expr.name] = _derived_copy(expr.name, parent_name, resolved[parent_name])
                elif parent_name not in expr_map:
                    if parent_name in model_table_names:
                        deferred.setdefault(expr.name, expr)
                    else:
                        resolved[expr.name] = _unresolved(
                            expr.name, f"references '{parent_name}' which does not exist"
                        )

            elif expr.source_type == "custom_function":
                fn_name = expr.function_name
                if fn_name in resolved:
                    parent = resolved[fn_name]
                    rs = _copy_resolved(expr.name, parent, tier=2)
                    entity = expr.function_args.strip('"').split(",")[-1].strip().strip('"')
                    if entity and rs.source_type == "connector" and rs.connector_namespace in ("PowerBI", "PowerPlatform"):
                        rs.entity = entity
                        connector = "Power BI Dataflow" if rs.connector_namespace == "PowerBI" else "Power Platform Dataflow"
                        rs.label = f"{connector} -> {entity}"
                    rs.derived_from = fn_name
                    rs.chain = [fn_name]
                    resolved[expr.name] = rs
                elif fn_name not in expr_map:
                    resolved[expr.name] = _unresolved(
                        expr.name, f"calls function '{fn_name}' which is not defined in this model"
                    )

    # Pass 3: resolve inline table sources and deferred expressions together,
    # so chains that cross between shared expressions and loaded tables settle.
    all_inline = list(inline_map.items())
    for _ in range(max_passes):
        pending_tables = [(name, expr) for name, expr in all_inline if name not in resolved]
        pending_deferred = [e for e in deferred.values() if e.name not in resolved]
        if not pending_tables and not pending_deferred:
            break
        made_progress = False

        for table_name, expr in pending_tables:
            rs = _resolve_inline(
                table_name, expr, resolved, expr_map, inline_map, params, table_ref=table_ref
            )
            if rs is not None:
                if table_name in manual_overrides:
                    rs.manual_label = manual_overrides[table_name]
                    rs.label        = manual_overrides[table_name]
                resolved[table_name] = rs
                made_progress = True

        for expr in pending_deferred:
            parent_name = expr.derived_from
            anchor = table_ref.get(parent_name)
            if parent_name in resolved:
                resolved[expr.name] = _derived_copy(expr.name, parent_name, resolved[parent_name])
                made_progress = True
            elif anchor and anchor in resolved:
                resolved[expr.name] = _derived_copy(expr.name, parent_name, resolved[anchor])
                made_progress = True
            elif parent_name in inline_map or (anchor and anchor in expr_map):
                pass
            else:
                resolved[expr.name] = _unresolved(
                    expr.name, f"references '{parent_name}' which does not exist"
                )
                made_progress = True

        if not made_progress:
            break

    for expr in deferred.values():
        if expr.name not in resolved:
            parent_name = expr.derived_from
            if parent_name in model_table_names:
                resolved[expr.name] = _unresolved(
                    expr.name, f"references '{parent_name}' which has no resolvable source"
                )
            else:
                resolved[expr.name] = _unresolved(
                    expr.name, f"references '{parent_name}' which does not exist"
                )

    # Pass 4: anything still unresolved
    for expr in source_expressions:
        if expr.name in resolved:
            continue
        if expr.source_type == "dynamic":
            rs = _unresolved(expr.name, "Dynamic M - built at runtime")
            rs.source_type = "dynamic"
            rs.label       = "Dynamic M (runtime)"
            if expr.name in manual_overrides:
                rs.unresolved   = False
                rs.manual_label = manual_overrides[expr.name]
                rs.label        = manual_overrides[expr.name]
            resolved[expr.name] = rs
        elif expr.source_type in ("function_def", "scalar_helper"):
            resolved[expr.name] = _from_expr(expr, params, tier=1)
        else:
            reason = expr.classification_reason if expr.source_type == "unknown" else ""
            resolved[expr.name] = _unresolved(
                expr.name, reason or f"Unclassified source type: {expr.source_type}"
            )

    for table_name in inline_map:
        if table_name not in resolved:
            resolved[table_name] = _unresolved(table_name, "Inline source could not be resolved")

    return resolved


# ---------------------------------------------------------------------------
# Inline source resolver
# ---------------------------------------------------------------------------

def _resolve_inline(
    table_name: str,
    expr: SourceExpression,
    resolved: dict[str, ResolvedSource],
    expr_map: dict[str, SourceExpression],
    inline_map: dict[str, SourceExpression],
    params: dict[str, str],
    table_ref: Optional[dict[str, str]] = None,
) -> Optional[ResolvedSource]:
    table_ref = table_ref or {}
    t = expr.source_type

    if t in _TERMINAL_TYPES:
        return _from_expr(expr, params, tier=1)

    if t in ("derived", "derived_table"):
        parent_name = expr.derived_from
        scalar_rs = _scalar_parent_resolution(table_name, expr, resolved, params)
        if scalar_rs is not None:
            return scalar_rs
        if parent_name in resolved:
            return _derived_copy(table_name, parent_name, resolved[parent_name])
        anchor = table_ref.get(parent_name)
        if anchor:
            if anchor in resolved:
                return _derived_copy(table_name, parent_name, resolved[anchor])
            if anchor in expr_map or anchor in inline_map:
                return None
        if parent_name not in expr_map and parent_name not in inline_map:
            reason = (
                f"references '{parent_name}' which does not exist in this model"
                if t == "derived_table"
                else f"references '{parent_name}' which does not exist"
            )
            return _unresolved(table_name, reason)
        return None  # retry next pass

    return _unresolved(table_name, f"Unrecognised inline source type: {t}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scalar_parent_reason(
    parent_name: str,
    resolved: dict[str, ResolvedSource],
    params: dict[str, str],
) -> str:
    if parent_name in params:
        return f"first step references parameter '{parent_name}'"
    parent = resolved.get(parent_name)
    if parent is not None and parent.source_type == "scalar_helper":
        return f"first step references scalar helper '{parent_name}'"
    return ""


def _scalar_parent_resolution(
    name: str,
    expr: SourceExpression,
    resolved: dict[str, ResolvedSource],
    params: dict[str, str],
) -> Optional[ResolvedSource]:
    reason = _scalar_parent_reason(expr.derived_from, resolved, params)
    if not reason:
        return None
    if expr.builds_table:
        return ResolvedSource(
            expression_name=name,
            source_type="generated",
            resolution_tier=1,
            label=_build_label(SourceExpression(name=name, source_type="generated"), params),
        )
    return _unresolved(name, reason)


def _terminal_label(rs: ResolvedSource) -> str:
    return rs.label


def _from_expr(expr: SourceExpression, params: dict[str, str], tier: int) -> ResolvedSource:
    rs = ResolvedSource(
        expression_name=expr.name,
        source_type=expr.source_type,
        resolution_tier=tier,
        connector_namespace=expr.connector_namespace,
        connector_function=expr.connector_function,
        is_native_query=expr.is_native_query,
        workspace_id=expr.workspace_id,
        dataflow_id=expr.dataflow_id,
        entity=expr.entity,
        server=_resolve_param(expr.server, params),
        database=_resolve_param(expr.database, params),
        schema=expr.schema,
        table_or_view=expr.table_or_view,
        native_query=expr.native_query,
        dsn=expr.dsn,
        sharepoint_url=expr.sharepoint_url,
        file_name=expr.file_name,
        sheet_name=expr.sheet_name,
        url=expr.url,
        account=expr.account,
        container=expr.container,
        physical_tables=list(expr.physical_tables),
    )
    rs.label = _build_label(expr, params)
    return rs


def _copy_resolved(name: str, parent: ResolvedSource, tier: int) -> ResolvedSource:
    return ResolvedSource(
        expression_name=name,
        source_type=parent.source_type,
        resolution_tier=tier,
        connector_namespace=parent.connector_namespace,
        connector_function=parent.connector_function,
        is_native_query=parent.is_native_query,
        workspace_id=parent.workspace_id,
        dataflow_id=parent.dataflow_id,
        entity=parent.entity,
        server=parent.server,
        database=parent.database,
        schema=parent.schema,
        table_or_view=parent.table_or_view,
        native_query=parent.native_query,
        dsn=parent.dsn,
        sharepoint_url=parent.sharepoint_url,
        file_name=parent.file_name,
        sheet_name=parent.sheet_name,
        url=parent.url,
        account=parent.account,
        container=parent.container,
        physical_tables=list(parent.physical_tables),
        label=parent.label,
    )


def _derived_copy(name: str, parent_name: str, parent: ResolvedSource) -> ResolvedSource:
    rs = _copy_resolved(name, parent, tier=2)
    rs.derived_from = parent_name
    rs.chain = [parent_name] + parent.chain
    rs.label = _build_chain_label([parent_name], _terminal_label(parent))
    return rs


def _unresolved(name: str, reason: str) -> ResolvedSource:
    return ResolvedSource(
        expression_name=name,
        source_type="unresolved",
        resolution_tier=3,
        label=f"Unresolved - {reason}",
        unresolved=True,
        unresolved_reason=reason,
    )


# ---------------------------------------------------------------------------
# Convenience: get resolved source for a table
# ---------------------------------------------------------------------------

def get_table_source(
    table,
    resolved: dict[str, ResolvedSource],
) -> Optional[ResolvedSource]:
    if table.source_ref:
        return resolved.get(table.source_ref)
    if table.inline_source is not None:
        return resolved.get(table.name)
    return None


def list_unresolved(resolved: dict[str, ResolvedSource]) -> list[ResolvedSource]:
    return [rs for rs in resolved.values() if rs.unresolved]