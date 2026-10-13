"""Fragment-level tests for the source resolver helpers."""

from tmdl_lens.source_resolver import (
    _build_chain_label,
    _build_label,
    _copy_resolved,
    _from_expr,
    _resolve_param,
    _terminal_label,
    _unresolved,
    get_table_source,
    list_unresolved,
    resolve_sources,
)
from tmdl_lens.tmdl_parser import MParameter, SourceExpression, Table, _classify_m_content


def test_label_native_query_sql():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="Sql", connector_function="Database",
        is_native_query=True, server="srv", database="db",
    )
    assert _build_label(expr, {}) == "SQL (native query) -> srv -> db"


def test_label_sql_with_table():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="Sql", connector_function="Database",
        server="srv", database="db", schema="dbo", table_or_view="orders",
    )
    assert _build_label(expr, {}) == "SQL -> srv -> db -> dbo.orders"


def test_label_parameter_resolution():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="Sql", connector_function="Database",
        server="[param:ServerName]", database="[param:DatabaseName]",
    )
    label = _build_label(expr, {"ServerName": "prod-server", "DatabaseName": "SalesDB"})
    assert label == "SQL -> prod-server -> SalesDB"


def test_label_unknown_connector_generic():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="CloudMart", connector_function="Warehouses",
    )
    assert _build_label(expr, {}) == "CloudMart -> Warehouses"


def test_label_unknown_connector_with_detail():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="CloudMart", connector_function="Warehouses",
        url="https://x",
    )
    assert _build_label(expr, {}) == "CloudMart -> Warehouses -> https://x"


def test_label_non_connector_types():
    assert _build_label(SourceExpression(name="t", source_type="hardcoded"), {}) == "Hardcoded (inline M)"
    assert _build_label(SourceExpression(name="t", source_type="embedded"), {}) == "Embedded data"
    assert _build_label(
        SourceExpression(name="t", source_type="table_combine", combine_sources=["a", "b"]), {}
    ) == "Combines: a, b"
    assert _build_label(SourceExpression(name="t", source_type="scalar_helper"), {}) == "Scalar Helper"
    assert _build_label(SourceExpression(name="t", source_type="function_def"), {}) == "Function Def"


def test_resolve_param_substitutes():
    assert _resolve_param("[param:ServerName]", {"ServerName": "srv"}) == "srv"


def test_resolve_param_unknown_keeps_marker():
    assert _resolve_param("[param:Missing]", {"ServerName": "srv"}) == "[param:Missing]"


def test_resolve_param_plain_passthrough():
    assert _resolve_param("literal", {}) == "literal"


def test_build_chain_label():
    assert _build_chain_label(["parent"], "SQL -> srv") == "parent -> SQL -> srv"
    assert _build_chain_label([], "SQL -> srv") == "SQL -> srv"


def test_terminal_label():
    rs = _from_expr(SourceExpression(name="t", source_type="hardcoded"), {}, tier=1)
    assert _terminal_label(rs) == "Hardcoded (inline M)"


def test_from_expr_builds_resolved():
    expr = SourceExpression(
        name="q", source_type="connector",
        connector_namespace="Sql", connector_function="Database",
        server="[param:ServerName]", database="db",
    )
    rs = _from_expr(expr, {"ServerName": "srv"}, tier=1)
    assert rs.expression_name == "q"
    assert rs.resolution_tier == 1
    assert rs.server == "srv"
    assert rs.label == "SQL -> srv -> db"


def test_copy_resolved_preserves_details():
    parent = _from_expr(
        SourceExpression(
            name="p", source_type="connector",
            connector_namespace="Sql", connector_function="Database",
            server="srv", database="db",
        ),
        {}, tier=1,
    )
    rs = _copy_resolved("child", parent, tier=2)
    assert rs.expression_name == "child"
    assert rs.resolution_tier == 2
    assert rs.server == "srv"
    assert rs.database == "db"
    assert rs.label == parent.label


def test_unresolved_marker():
    rs = _unresolved("q", "no such source")
    assert rs.unresolved is True
    assert rs.resolution_tier == 3
    assert rs.source_type == "unresolved"
    assert rs.unresolved_reason == "no such source"
    assert rs.label == "Unresolved - no such source"


def test_get_table_source_by_ref():
    resolved = {"q": _unresolved("q", "x")}
    table = Table(name="t", table_type="fact", source_ref="q")
    assert get_table_source(table, resolved) is resolved["q"]


def test_get_table_source_none():
    table = Table(name="t", table_type="fact")
    assert get_table_source(table, {}) is None


def test_list_unresolved():
    resolved = {
        "a": _unresolved("a", "x"),
        "b": _from_expr(SourceExpression(name="b", source_type="hardcoded"), {}, tier=1),
    }
    names = [rs.expression_name for rs in list_unresolved(resolved)]
    assert names == ["a"]

def test_resolve_expression_referencing_inline_table():
    fact_load = Table(
        name="fact-load",
        table_type="fact",
        partition_type="m",
        inline_source=_classify_m_content(
            'let\n'
            '    Source = SharePoint.Files("https://contoso.sharepoint.com/sites/examples")\n'
            'in\n'
            '    Source',
            "fact-load",
        ),
    )
    derived = _classify_m_content(
        'let\n'
        '    Source = #"fact-load"\n'
        'in\n'
        '    Source',
        "fact-load-derived-source",
    )
    resolved = resolve_sources([derived], [], tables=[fact_load])
    rs = resolved["fact-load-derived-source"]
    assert rs.unresolved is False
    assert rs.derived_from == "fact-load"
    assert rs.chain[0] == "fact-load"
    assert rs.sharepoint_url == "https://contoso.sharepoint.com/sites/examples"


def test_resolve_inline_alias_from_parser():
    shared = SourceExpression(
        name="shared-mapping-source",
        source_type="connector",
        connector_namespace="SharePoint",
        connector_function="Files",
        sharepoint_url="https://contoso.sharepoint.com/sites/examples",
    )
    capacity_table = Table(
        name="capacity-table",
        table_type="fact",
        partition_type="m",
        inline_source=_classify_m_content(
            'let\n'
            '    wb = #"shared-mapping-source"\n'
            'in\n'
            '    wb',
            "capacity-table",
        ),
    )
    resolved = resolve_sources([shared], [], tables=[capacity_table])
    rs = resolved["capacity-table"]
    assert rs.unresolved is False
    assert rs.derived_from == "shared-mapping-source"
    assert rs.connector_namespace == "SharePoint"


def test_resolve_inline_reference_to_source_ref_table():
    direct = SourceExpression(
        name="source-sql-direct",
        source_type="connector",
        connector_namespace="Sql",
        connector_function="Database",
        server="srv",
        database="db",
        schema="dbo",
        table_or_view="orders",
    )
    alias_tbl = Table(
        name="fact-load",
        table_type="fact",
        partition_type="m",
        source_ref="source-sql-direct",
    )
    dep_tbl = Table(
        name="fact-load-derived",
        table_type="fact",
        partition_type="m",
        inline_source=_classify_m_content(
            'let\n'
            '    Source = #"fact-load"\n'
            'in\n'
            '    Source',
            "fact-load-derived",
        ),
    )
    resolved = resolve_sources([direct], [], tables=[alias_tbl, dep_tbl])
    rs = resolved["fact-load-derived"]
    assert rs.unresolved is False
    assert rs.derived_from == "fact-load"
    assert rs.server == "srv"


def test_resolve_expression_referencing_missing_target():
    expr = _classify_m_content(
        'let\n'
        '    Source = #"ghost"\n'
        'in\n'
        '    Source',
        "x",
    )
    resolved = resolve_sources([expr], [], tables=[])
    rs = resolved["x"]
    assert rs.unresolved is True
    assert "ghost" in rs.unresolved_reason


def test_resolve_combine_expression_is_terminal_and_chains():
    combined = _classify_m_content(
        'let\n'
        '    Combined = Table.Combine({#"q-a", #"q-b"})\n'
        'in\n'
        '    Combined',
        "combined",
    )
    child = _classify_m_content(
        'let\n'
        '    Source = #"combined"\n'
        'in\n'
        '    Source',
        "child",
    )
    resolved = resolve_sources([combined, child], [], tables=[])
    assert resolved["combined"].unresolved is False
    assert resolved["combined"].label == "Combines: q-a, q-b"
    assert resolved["child"].unresolved is False
    assert resolved["child"].derived_from == "combined"
    assert resolved["child"].label == "combined -> Combines: q-a, q-b"


def test_label_excel_local_and_sharepoint():
    local = _classify_m_content('let s = Excel.Workbook(File.Contents("D:\\Data\\x.xlsx"), true) in s', "t")
    assert _build_label(local, {}) == "Excel (local) -> D:\\Data\\x.xlsx"
    web = _classify_m_content('let s = Excel.Workbook(Web.Contents("https://example.com/x.xlsx"), true) in s', "t")
    assert _build_label(web, {}) == "Excel (SharePoint) -> https://example.com/x.xlsx"


def test_resolve_generated_calendar_table():
    helper = SourceExpression(name="first-day-helper", source_type="scalar_helper")
    calendar = Table(
        name="Calendar",
        table_type="dim",
        partition_type="m",
        inline_source=_classify_m_content(
            'let\n'
            '    #"seed-day" = #"first-day-helper",\n'
            '    Dates = List.Generate(() => #"seed-day", each _ < #date(2030, 1, 1), each Date.AddDays(_, 1)),\n'
            '    Calendar = Table.FromList(Dates, Splitter.SplitByNothing())\n'
            'in\n'
            '    Calendar',
            "Calendar",
        ),
    )
    resolved = resolve_sources([helper], [], tables=[calendar])
    rs = resolved["Calendar"]
    assert rs.source_type == "generated"
    assert rs.unresolved is False
    assert rs.chain == []


def test_resolve_derived_with_scratch_builder_keeps_real_lineage():
    parent = _classify_m_content('let s = Sql.Database("srv", "db") in s', "real-query")
    builders = [
        "Table.FromRecords({[a = 1]})",
        "List.Numbers(1, 3)",
        "List.Generate(() => 0, each _ < 3, each _ + 1)",
    ]
    for builder in builders:
        child = Table(
            name="child",
            table_type="fact",
            partition_type="m",
            inline_source=_classify_m_content(
                'let\n'
                '    Source = #"real-query",\n'
                f'    Extra = {builder},\n'
                '    Result = Table.SelectRows(Source, each true)\n'
                'in\n'
                '    Result',
                "child",
            ),
        )
        resolved = resolve_sources([parent], [], tables=[child])
        rs = resolved["child"]
        assert rs.source_type == "connector", builder
        assert rs.unresolved is False, builder
        assert rs.derived_from == "real-query", builder
        assert rs.label == "real-query -> SQL -> srv -> db", builder


def test_resolve_derived_from_parameter_with_scratch_builder_is_generated():
    expr = _classify_m_content(
        'let\n'
        '    Start = #"StartYear",\n'
        '    Years = List.Numbers(Start, 5),\n'
        '    T = Table.FromList(Years, Splitter.SplitByNothing())\n'
        'in\n'
        '    T',
        "years",
    )
    resolved = resolve_sources([expr], [MParameter(name="StartYear", value="2030")], tables=[])
    assert resolved["years"].source_type == "generated"
    assert resolved["years"].unresolved is False


def test_resolve_derived_from_scalar_helper_is_unresolved():
    helper = SourceExpression(name="cutoff", source_type="scalar_helper")
    expr = _classify_m_content(
        'let\n'
        '    Source = #"cutoff"\n'
        'in\n'
        '    Source',
        "x",
    )
    resolved = resolve_sources([helper, expr], [], tables=[])
    assert resolved["x"].unresolved is True
    assert resolved["x"].unresolved_reason == "first step references scalar helper 'cutoff'"


def test_resolve_derived_from_parameter_is_unresolved():
    expr = _classify_m_content(
        'let\n'
        '    Source = #"ServerName"\n'
        'in\n'
        '    Source',
        "x",
    )
    resolved = resolve_sources([expr], [MParameter(name="ServerName", value="srv")], tables=[])
    assert resolved["x"].unresolved is True
    assert resolved["x"].unresolved_reason == "first step references parameter 'ServerName'"


def test_resolve_unknown_uses_classification_reason():
    expr = _classify_m_content("let x = SomeUnknownThing(y) in x", "x")
    resolved = resolve_sources([expr], [], tables=[])
    assert resolved["x"].unresolved is True
    assert resolved["x"].unresolved_reason == "no connector, combine or query reference found"
