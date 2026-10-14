"""Fragment-level tests for the TMDL parser text-processing functions."""

from tmdl_lens.tmdl_parser import (
    SourceExpression,
    _classify_expression,
    _classify_m_content,
    _dedent,
    _extract_blocks,
    _extract_connector_details,
    _parse_calculation_items,
    _parse_column,
    _parse_expressions,
    _parse_functions,
    _parse_measure,
    _parse_relationships,
    _parse_roles,
    _parse_table_file,
    _parse_tree,
    _strip_m_comments,
    parse_semantic_model,
)


def test_strip_line_comments():
    content = "let\n    x = 1, // trailing comment\nin\n    x"
    result = _strip_m_comments(content)
    assert "comment" not in result
    assert "x = 1," in result


def test_strip_preserves_urls_in_strings():
    content = 'let\n    url = "https://example.com/api",\n    x = 1\nin\n    x'
    result = _strip_m_comments(content)
    assert "https://example.com/api" in result


def test_strip_block_comments():
    content = "let\n    /* multi\n       line */\n    x = 1\nin x"
    result = _strip_m_comments(content)
    assert "multi" not in result
    assert "x = 1" in result


def test_dedent_common_indent():
    assert _dedent("  line1\n    line2\n  line3") == "line1\n  line2\nline3"


def test_dedent_blank_lines():
    assert _dedent("\n  a\n\n  b\n") == "a\n\nb"


def test_dedent_empty():
    assert _dedent("") == ""


def test_extract_blocks_multiple():
    text = "table Sales\n\tdataType: int64\n\tisHidden\ntable Other\n\tdataType: string"
    blocks = _extract_blocks(text, "table ")
    assert len(blocks) == 2
    assert blocks[0].startswith("table Sales")
    assert "dataType: int64" in blocks[0]
    assert "table Other" not in blocks[0]


def test_extract_blocks_column_keyword():
    text = "table Sales\n\tcolumn 'A'\n\t\tdataType: int64\n\tcolumn 'B'\n\t\tisHidden"
    blocks = _extract_blocks(text, "column ")
    assert len(blocks) == 2
    assert "'A'" in blocks[0]
    assert "'B'" in blocks[1]
    assert "dataType: int64" in blocks[0]


def test_parse_tree_flat_properties():
    lines = ["table Sales", "\tdataType: int64", "\tisHidden"]
    nodes, next_i = _parse_tree(lines, 1, 0)
    assert len(nodes) == 2
    assert nodes[0].key == "dataType"
    assert nodes[0].value == "int64"
    assert nodes[1].key == "isHidden"
    assert nodes[1].value == ""
    assert next_i == 3


def test_parse_tree_nested_children():
    lines = ["table Sales", "\tcolumns", "\t\tcol A", "\t\tcol B", "\tmeasures", "\t\tm1"]
    nodes, next_i = _parse_tree(lines, 1, 0)
    assert len(nodes) == 2
    assert [c.key for c in nodes[0].children] == ["col A", "col B"]
    assert [c.key for c in nodes[1].children] == ["m1"]


def test_parse_tree_backtick_value():
    lines = ["table Sales", "\texpression = ```", "\t\tSUM(1)", "\t```", "\tdataType: int64"]
    nodes, next_i = _parse_tree(lines, 1, 0)
    assert nodes[0].key == "expression"
    assert nodes[0].value == "SUM(1)"
    assert nodes[1].key == "dataType"


def test_classify_scalar_helper():
    expr = _classify_m_content("let x = 1 in x", "t", result_type="Number")
    assert expr.source_type == "scalar_helper"


def test_classify_table_combine():
    expr = _classify_m_content('let s = Table.Combine({#"a", #"b"}) in s', "t")
    assert expr.source_type == "table_combine"
    assert expr.combine_sources == ["a", "b"]


def test_classify_hardcoded():
    expr = _classify_m_content('#table({"a", "b"}, {1, 2})', "t")
    assert expr.source_type == "hardcoded"


def test_classify_embedded():
    expr = _classify_m_content("Table.FromRows({1, 2})", "t")
    assert expr.source_type == "embedded"


def test_classify_sql_connector():
    expr = _classify_m_content('let src = Sql.Database("srv", "db") in src', "t")
    assert expr.source_type == "connector"
    assert expr.connector_namespace == "Sql"
    assert expr.connector_function == "Database"
    assert expr.server == "srv"
    assert expr.database == "db"


def test_classify_ignores_m_stdlib():
    expr = _classify_m_content("let t = Table.SelectRows(x, each true) in t", "t")
    assert expr.source_type != "connector"


def test_classify_derived_quoted():
    expr = _classify_m_content('let Source = #"source-sql-direct" in Source', "t")
    assert expr.source_type == "derived"
    assert expr.derived_from == "source-sql-direct"


def test_classify_derived_bare_table():
    expr = _classify_m_content("let\n    Source = myTable\nin\n    Source", "t")
    assert expr.source_type == "derived_table"
    assert expr.derived_from == "myTable"


def test_classify_unresolved():
    expr = _classify_m_content("let x = SomeUnknownThing(y) in x", "t")
    assert expr.source_type == "unknown"


def test_connector_details_sql_native_query():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="Sql", connector_function="Database",
    )
    _extract_connector_details(
        expr, 'Sql.Database("srv", "db", [Query = "select 1"])', "Sql", "Database"
    )
    assert expr.server == "srv"
    assert expr.database == "db"
    assert expr.is_native_query is True
    assert expr.native_query == "select 1"


def test_connector_details_dataflow():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="PowerBI", connector_function="Dataflows",
    )
    _extract_connector_details(
        expr,
        'PowerBI.Dataflows(workspaceId = "ws", dataflowId = "df", entity = "e")',
        "PowerBI", "Dataflows",
    )
    assert expr.workspace_id == "ws"
    assert expr.dataflow_id == "df"
    assert expr.entity == "e"


def test_connector_details_odbc():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="Odbc", connector_function="DataSource",
    )
    _extract_connector_details(expr, 'Odbc.DataSource("dsn=MyDSN")', "Odbc", "DataSource")
    assert expr.dsn == "dsn=MyDSN"


def test_connector_details_sharepoint_contents():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="SharePoint", connector_function="Contents",
    )
    _extract_connector_details(
        expr,
        'SharePoint.Contents("https://contoso.sharepoint.com/sites/examples", [ApiVersion = 15])',
        "SharePoint", "Contents",
    )
    assert expr.sharepoint_url == "https://contoso.sharepoint.com/sites/examples"
    assert expr.table_or_view == ""
    assert expr.file_name == ""
    assert expr.sheet_name == ""


def test_connector_details_sharepoint_contents_bare_param():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="SharePoint", connector_function="Contents",
    )
    _extract_connector_details(expr, "SharePoint.Contents(SiteUrl)", "SharePoint", "Contents")
    assert expr.sharepoint_url == "[param:SiteUrl]"


def test_connector_details_navigation_fallback():
    expr = SourceExpression(
        name="t", source_type="connector",
        connector_namespace="Something", connector_function="Else",
    )
    _extract_connector_details(expr, '{[Schema = "dbo", Item = "orders"]}[Data]', "Something", "Else")
    assert len(expr.physical_tables) == 1
    assert expr.physical_tables[0].schema == "dbo"
    assert expr.physical_tables[0].table == "orders"
    assert expr.physical_tables[0].source == "navigation"


def test_calc_items_inline_fenced_expression():
    content = (
        "table 'Time Intelligence'\n"
        "\tcalculationGroup\n"
        "\n"
        "\t\tcalculationItem MTD = ```\n"
        "\t\t\tCALCULATE(\n"
        "\t\t\t\tSELECTEDMEASURE(),\n"
        "\t\t\t\tDATESMTD('Date'[date])\n"
        "\t\t\t)\n"
        "\t\t\t```\n"
        "\n"
        "\t\tcalculationItem 'Rolling 12M' = ```\n"
        "\t\t\tDIVIDE(\n"
        "\t\t\t\tSELECTEDMEASURE() - CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[date])),\n"
        "\t\t\t\tCALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Date'[date]))\n"
        "\t\t\t)\n"
        "\t\t\t```\n"
    )
    items = _parse_calculation_items(content)
    assert [it.name for it in items] == ["MTD", "Rolling 12M"]
    mtd = items[0]
    assert mtd.ordinal == 0
    assert mtd.dax_expression.startswith("CALCULATE(")
    assert "DATESMTD('Date'[date])" in mtd.dax_expression
    assert mtd.format_string_expression == ""
    assert "SAMEPERIODLASTYEAR" in items[1].dax_expression


def test_calc_items_property_style():
    content = (
        "table 'Time Intelligence'\n"
        "\tcalculationGroup\n"
        "\t\tcalculationItem 'Rolling 12M'\n"
        "\t\t\tordinal: 2\n"
        "\t\t\texpression = ```\n"
        "\t\t\t\tCALCULATE(SELECTEDMEASURE(), DATESINPERIOD('Date'[date], LASTDATE('Date'[date]), -12, MONTH))\n"
        "\t\t\t\t```\n"
        "\t\t\tformatStringExpression = \"0.00%\"\n"
    )
    items = _parse_calculation_items(content)
    assert len(items) == 1
    it = items[0]
    assert it.name == "Rolling 12M"
    assert it.ordinal == 2
    assert "DATESINPERIOD" in it.dax_expression
    assert it.format_string_expression == "0.00%"


def test_calc_items_inline_with_ordinal_and_format_children():
    content = (
        "table 'Time Intelligence'\n"
        "\tcalculationGroup\n"
        "\t\tcalculationItem MTD = ```\n"
        "\t\t\tCALCULATE(SELECTEDMEASURE(), DATESMTD('Date'[date]))\n"
        "\t\t\t```\n"
        "\t\t\tordinal: 3\n"
        "\t\t\tformatStringExpression = ```\n"
        "\t\t\t\tSELECTEDMEASUREFORMATSTRING()\n"
        "\t\t\t\t```\n"
    )
    items = _parse_calculation_items(content)
    assert len(items) == 1
    it = items[0]
    assert it.ordinal == 3
    assert "DATESMTD" in it.dax_expression
    assert it.format_string_expression == "SELECTEDMEASUREFORMATSTRING()"


def test_parse_column_calc_bare_name_inline():
    col = _parse_column('column QuarterName = "Q" & FORMAT([Quarter], "0")')
    assert col is not None
    assert col.name == "QuarterName"
    assert col.is_calculated is True
    assert col.data_type == "calculated"
    assert 'FORMAT([Quarter], "0")' in col.dax_expression


def test_parse_column_calc_bare_name_multiline():
    block = (
        "column NetRevenue =\n"
        "\t\tSUM(\n"
        "\t\t\t[amount]\n"
        "\t\t)\n"
        "\tisHidden\n"
        "\tdataType: double"
    )
    col = _parse_column(block)
    assert col is not None
    assert col.name == "NetRevenue"
    assert col.is_calculated is True
    assert "SUM(" in col.dax_expression
    assert "[amount]" in col.dax_expression
    assert col.is_hidden is True


def test_parse_measure_bare_name_inline():
    m = _parse_measure(
        'measure Produced = CALCULATE(SUM(batch[Quantity]), batch[Prod Ship] = "Produced")'
    )
    assert m is not None
    assert m.name == "Produced"
    assert "CALCULATE(" in m.dax_expression


def test_parse_measure_bare_numeric_name():
    m = _parse_measure("measure 107 = CALCULATE(SUM(batch[Quantity]))")
    assert m is not None
    assert m.name == "107"
    assert "CALCULATE(" in m.dax_expression


def test_parse_measure_bare_name_multiline_with_properties():
    block = (
        "measure Revenues =\n"
        "\tSUM('fact-sales'[Sales Amount]) + SUM('fact-sales'[Management Fee])\n"
        "\tformatString: #,0\n"
        "\tlineageTag: abc-123"
    )
    m = _parse_measure(block)
    assert m is not None
    assert m.name == "Revenues"
    assert "SUM('fact-sales'[Sales Amount])" in m.dax_expression
    assert m.format_string == "#,0"
    assert m.lineage_tag == "abc-123"


def test_parse_measure_bare_name_fenced_header():
    block = (
        "measure Fee = ```\n"
        "\tSUM('fact-sales'[Management Fee])\n"
        "\t```"
    )
    m = _parse_measure(block)
    assert m is not None
    assert m.name == "Fee"
    assert "Management Fee" in m.dax_expression


def test_parse_measure_quoted_name_unchanged():
    block = (
        "measure 'Total Sales Amount' = SUM('fact-sales'[amount])\n"
        "\tformatString: #,0"
    )
    m = _parse_measure(block)
    assert m is not None
    assert m.name == "Total Sales Amount"
    assert "SUM('fact-sales'[amount])" in m.dax_expression
    assert m.format_string == "#,0"


def test_classify_first_binding_alias_quoted():
    expr = _classify_m_content(
        'let\n'
        '    wb = #"shared-mapping-source"\n'
        'in\n'
        '    wb',
        "capacity-table",
    )
    assert expr.source_type == "derived"
    assert expr.derived_from == "shared-mapping-source"


def test_classify_first_binding_alias_bare():
    expr = _classify_m_content(
        "let\n"
        "    t = loadTable\n"
        "in\n"
        "    t",
        "x",
    )
    assert expr.source_type == "derived_table"
    assert expr.derived_from == "loadTable"


def test_relationship_defaults_minimal(tmp_path):
    content = (
        "relationship r1\n"
        "\tfromColumn: fact-sales.order_id\n"
        "\ttoColumn: 'dim-product'.product_id\n"
    )
    path = tmp_path / "relationships.tmdl"
    path.write_text(content, encoding="utf-8")
    rels = _parse_relationships(str(path))
    assert len(rels) == 1
    rel = rels[0]
    assert rel.from_table == "fact-sales"
    assert rel.from_column == "order_id"
    assert rel.to_table == "dim-product"
    assert rel.to_column == "product_id"
    assert rel.cardinality == "Many-to-One"
    assert rel.cross_filtering_behavior == "oneDirection"
    assert rel.security_filtering_behavior == "oneDirection"
    assert rel.is_active is True


def test_classify_nested_lambda_not_function():
    block = (
        "source-nested-lambda =\n"
        "\tlet\n"
        "\t    Accumulate = List.Accumulate({1, 2, 3}, 0, (state, current) => state + current),\n"
        "\t    Source = #\"source-sql-direct\"\n"
        "\tin\n"
        "\t    Source\n"
        "\tannotation PBI_ResultType = Table"
    )
    expr = _classify_expression(block, "source-nested-lambda")
    assert expr.source_type == "derived"
    assert expr.derived_from == "source-sql-direct"


def test_classify_typed_function_annotation():
    block = (
        "fnConvert =\n"
        "\t(x as text) as number =>\n"
        "\tNumber.From(x)\n"
        "\tannotation PBI_ResultType = Function"
    )
    expr = _classify_expression(block, "fnConvert")
    assert expr.source_type == "function_def"


def test_classify_typed_function_no_annotation():
    block = (
        "fnToTable =\n"
        "\t(x as text) as table =>\n"
        "\tlet\n"
        "\t    Source = #table({\"x\"}, {{x}})\n"
        "\tin\n"
        "\t    Source"
    )
    expr = _classify_expression(block, "fnToTable")
    assert expr.source_type == "function_def"


def test_classify_function_no_return_type_no_annotation():
    block = (
        "fnSimple =\n"
        "\t(x as text) =>\n"
        "\tText.Lower(x)"
    )
    expr = _classify_expression(block, "fnSimple")
    assert expr.source_type == "function_def"


def test_classify_fenced_function():
    block = (
        "fnFenced = ```\n"
        "\t(a as number) as number => a + 1\n"
        "\t```"
    )
    expr = _classify_expression(block, "fnFenced")
    assert expr.source_type == "function_def"


def test_classify_exception_falls_through():
    block = (
        "source-exception =\n"
        "\tlet\n"
        "\t    Source = Sql.Database(\"srv\", \"db\")\n"
        "\tin\n"
        "\t    Source\n"
        "\tannotation PBI_ResultType = Exception"
    )
    expr = _classify_expression(block, "source-exception")
    assert expr.source_type == "connector"
    assert expr.connector_namespace == "Sql"
    assert expr.connector_function == "Database"


def test_classify_date_annotation_scalar():
    block = (
        "scalar-date =\n"
        "\tlet\n"
        "\t    d = Date.From(DateTime.LocalNow())\n"
        "\tin\n"
        "\t    d\n"
        "\tannotation PBI_ResultType = Date"
    )
    expr = _classify_expression(block, "scalar-date")
    assert expr.source_type == "scalar_helper"


def test_classify_quoted_name_with_equals():
    block = "'Weird=Name' = (x as text) => Text.Lower(x)"
    expr = _classify_expression(block, "Weird=Name")
    assert expr.source_type == "function_def"


def test_relationship_quoted_dotted_column(tmp_path):
    content = (
        "relationship r1\n"
        "\tfromColumn: fact-sales.order_id\n"
        "\ttoColumn: dim-product.'product.name.full'\n"
    )
    path = tmp_path / "relationships.tmdl"
    path.write_text(content, encoding="utf-8")
    rels = _parse_relationships(str(path))
    assert len(rels) == 1
    rel = rels[0]
    assert rel.from_table == "fact-sales"
    assert rel.from_column == "order_id"
    assert rel.to_table == "dim-product"
    assert rel.to_column == "product.name.full"


def test_relationship_both_sides_quoted(tmp_path):
    content = (
        "relationship r1\n"
        "\tfromColumn: 'fact table'.'order id'\n"
        "\ttoColumn: 'dim product'.'product id'\n"
    )
    path = tmp_path / "relationships.tmdl"
    path.write_text(content, encoding="utf-8")
    rels = _parse_relationships(str(path))
    assert len(rels) == 1
    rel = rels[0]
    assert rel.from_table == "fact table"
    assert rel.from_column == "order id"
    assert rel.to_table == "dim product"
    assert rel.to_column == "product id"


def test_parse_column_quoted_escaped_name_plain():
    block = (
        "column 'Rep''s Col'\n"
        "\tdataType: string"
    )
    col = _parse_column(block)
    assert col is not None
    assert col.name == "Rep's Col"
    assert col.is_calculated is False


def test_parse_column_quoted_escaped_name_calc():
    block = "column 'Rep''s Calc' = SUMX('fact-sales'[amount], 1)"
    col = _parse_column(block)
    assert col is not None
    assert col.name == "Rep's Calc"
    assert col.is_calculated is True
    assert "SUMX('fact-sales'[amount], 1)" in col.dax_expression


def test_parse_measure_quoted_escaped_name():
    block = "measure 'Rep''s Total' = SUM('fact-sales'[amount])"
    m = _parse_measure(block)
    assert m is not None
    assert m.name == "Rep's Total"
    assert "SUM('fact-sales'[amount])" in m.dax_expression


def test_parse_measure_expressionless():
    block = "measure Placeholder"
    m = _parse_measure(block)
    assert m is not None
    assert m.name == "Placeholder"
    assert m.dax_expression == ""


def test_parse_calc_item_quoted_escaped_name():
    content = (
        "table 'Time Intelligence'\n"
        "\tcalculationGroup\n"
        "\t\tcalculationItem 'Rep''s Item' = ```\n"
        "\t\t\tSELECTEDMEASURE()\n"
        "\t\t\t```\n"
    )
    items = _parse_calculation_items(content)
    assert len(items) == 1
    assert items[0].name == "Rep's Item"
    assert items[0].dax_expression == "SELECTEDMEASURE()"


def test_parse_table_quoted_escaped_name(tmp_path):
    content = (
        "table 'Rep''s Table'\n"
        "\tcolumn c\n"
        "\t\tdataType: string\n"
    )
    path = tmp_path / "table.tmdl"
    path.write_text(content, encoding="utf-8")
    table = _parse_table_file(str(path))
    assert table is not None
    assert table.name == "Rep's Table"


def test_parse_expression_quoted_escaped_name(tmp_path):
    content = "expression 'Weird''Name' = let x = 1 in x\n"
    path = tmp_path / "expressions.tmdl"
    path.write_text(content, encoding="utf-8")
    source_expressions, _m_parameters = _parse_expressions(str(path))
    assert len(source_expressions) == 1
    assert source_expressions[0].name == "Weird'Name"


def test_parse_role_quoted_escaped_name(tmp_path):
    content = (
        "role 'Rep''s Role'\n"
        "\tmodelPermission: read\n"
        "\n"
        "\ttablePermission 'Rep''s Data' = [region] = \"North\"\n"
    )
    path = tmp_path / "roles.tmdl"
    path.write_text(content, encoding="utf-8")
    roles = _parse_roles(str(path))
    assert len(roles) == 1
    assert roles[0].name == "Rep's Role"
    assert len(roles[0].table_filters) == 1
    assert roles[0].table_filters[0].table == "Rep's Data"


def test_classify_connector_after_stdlib_calls():
    expr = _classify_m_content(
        'let\n'
        '    Start = Date.From(DateTime.LocalNow()),\n'
        '    Source = Sql.Database("srv", "db")\n'
        'in\n'
        '    Source',
        "t",
    )
    assert expr.source_type == "connector"
    assert expr.connector_namespace == "Sql"
    assert expr.connector_function == "Database"
    assert expr.server == "srv"
    assert expr.database == "db"


def test_classify_derived_after_stdlib_binding():
    expr = _classify_m_content(
        'let\n'
        '    D = Duration.Days(#duration(1, 0, 0, 0)),\n'
        '    Source = #"base"\n'
        'in\n'
        '    Source',
        "t",
    )
    assert expr.source_type == "derived"
    assert expr.derived_from == "base"


def test_classify_native_query_wrapped_connector():
    expr = _classify_m_content(
        'Value.NativeQuery(AmazonRedshift.Database("h", "db"), "select 1")',
        "t",
    )
    assert expr.source_type == "connector"
    assert expr.connector_namespace == "AmazonRedshift"
    assert expr.connector_function == "Database"
    assert expr.server == "h"
    assert expr.database == "db"
    assert expr.is_native_query is True
    assert expr.native_query == "select 1"


def test_classify_native_query_wrapped_sql():
    expr = _classify_m_content(
        'Value.NativeQuery(Sql.Database("srv", "db"), "select 1")',
        "t",
    )
    assert expr.source_type == "connector"
    assert expr.connector_namespace == "Sql"
    assert expr.is_native_query is True
    assert expr.native_query == "select 1"


def test_classify_stdlib_only_stays_unresolved():
    expr = _classify_m_content(
        'let\n'
        '    D = Duration.Days(#duration(1, 0, 0, 0))\n'
        'in\n'
        '    D',
        "t",
    )
    assert expr.source_type != "connector"


def test_parse_roles_multiline_filter(tmp_path):
    content = (
        "role 'Multi Line'\n"
        "\tmodelPermission: read\n"
        "\n"
        "\ttablePermission 'fact-sales' =\n"
        "\t\t\t[region] = \"South\"\n"
        "\t\t\t\t&& [unit_price] > 0\n"
    )
    path = tmp_path / "roles.tmdl"
    path.write_text(content, encoding="utf-8")
    roles = _parse_roles(str(path))
    assert len(roles) == 1
    assert roles[0].name == "Multi Line"
    assert len(roles[0].table_filters) == 1
    assert roles[0].table_filters[0].table == "fact-sales"
    assert roles[0].table_filters[0].dax_filter == "[region] = \"South\"\n\t&& [unit_price] > 0"


def test_parse_roles_fenced_filter(tmp_path):
    content = (
        "role Fenced\n"
        "\tmodelPermission: read\n"
        "\n"
        "\ttablePermission 'dim-product' = ```\n"
        "\t\t[category] = \"Hardware\"\n"
        "\t\t```\n"
    )
    path = tmp_path / "roles.tmdl"
    path.write_text(content, encoding="utf-8")
    roles = _parse_roles(str(path))
    assert len(roles) == 1
    assert roles[0].name == "Fenced"
    assert roles[0].table_filters[0].dax_filter == "[category] = \"Hardware\""


def test_parse_semantic_model_roles_folder(tmp_path):
    definition = tmp_path / "definition"
    roles_dir = definition / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "Static.tmdl").write_text(
        "role Static\n"
        "\tmodelPermission: read\n"
        "\n"
        "\ttablePermission 'fact-sales' = [region] = \"North\"\n",
        encoding="utf-8",
    )
    (roles_dir / "Multi Line.tmdl").write_text(
        "role 'Multi Line'\n"
        "\tmodelPermission: read\n"
        "\n"
        "\ttablePermission 'fact-sales' =\n"
        "\t\t\t[region] = \"South\"\n"
        "\t\t\t\t&& [unit_price] > 0\n",
        encoding="utf-8",
    )
    model = parse_semantic_model(str(tmp_path), "Test")
    assert [r.name for r in model.security_roles] == ["Multi Line", "Static"]
    multi = model.security_roles[0]
    assert multi.table_filters[0].dax_filter == "[region] = \"South\"\n\t&& [unit_price] > 0"


def test_parse_semantic_model_roles_folder_and_legacy(tmp_path):
    definition = tmp_path / "definition"
    roles_dir = definition / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "Folder Role.tmdl").write_text(
        "role 'Folder Role'\n\tmodelPermission: read\n", encoding="utf-8"
    )
    (definition / "roles.tmdl").write_text(
        "role Legacy\n\tmodelPermission: read\n", encoding="utf-8"
    )
    model = parse_semantic_model(str(tmp_path), "Test")
    assert [r.name for r in model.security_roles] == ["Folder Role", "Legacy"]


def test_parse_semantic_model_roles_legacy_only(tmp_path):
    definition = tmp_path / "definition"
    definition.mkdir(parents=True)
    (definition / "roles.tmdl").write_text(
        "role Legacy\n\tmodelPermission: read\n", encoding="utf-8"
    )
    model = parse_semantic_model(str(tmp_path), "Test")
    assert [r.name for r in model.security_roles] == ["Legacy"]


def test_parse_semantic_model_roles_none(tmp_path):
    (tmp_path / "definition").mkdir()
    model = parse_semantic_model(str(tmp_path), "Test")
    assert model.security_roles == []


def test_parse_functions_inline(tmp_path):
    content = (
        "/// Adds sales tax to a net amount using the given rate.\n"
        "function AddTax = (amount: number, rate: number) => amount * (1 + rate)\n"
    )
    path = tmp_path / "functions.tmdl"
    path.write_text(content, encoding="utf-8")
    functions = _parse_functions(str(path))
    assert len(functions) == 1
    assert functions[0].name == "AddTax"
    assert functions[0].expression == "(amount: number, rate: number) => amount * (1 + rate)"
    assert functions[0].description == "Adds sales tax to a net amount using the given rate."


def test_parse_functions_multiline_with_properties(tmp_path):
    content = (
        "function SafeStock =\n"
        "\t\t(category: string) =>\n"
        "\t\tIF(category == \"Hardware\", 50, 20)\n"
        "\tlineageTag: abc-123\n"
    )
    path = tmp_path / "functions.tmdl"
    path.write_text(content, encoding="utf-8")
    functions = _parse_functions(str(path))
    assert len(functions) == 1
    assert functions[0].name == "SafeStock"
    assert functions[0].expression == "(category: string) =>\n\t\tIF(category == \"Hardware\", 50, 20)"


def test_parse_functions_fenced(tmp_path):
    content = (
        "function Fenced = ```\n"
        "\tVAR x = 1\n"
        "\tRETURN x\n"
        "\t```\n"
    )
    path = tmp_path / "functions.tmdl"
    path.write_text(content, encoding="utf-8")
    functions = _parse_functions(str(path))
    assert len(functions) == 1
    assert functions[0].name == "Fenced"
    assert functions[0].expression == "VAR x = 1\nRETURN x"


def test_parse_functions_quoted_escaped_name(tmp_path):
    content = "function 'Rep''s Func' = (x as any) => x\n"
    path = tmp_path / "functions.tmdl"
    path.write_text(content, encoding="utf-8")
    functions = _parse_functions(str(path))
    assert len(functions) == 1
    assert functions[0].name == "Rep's Func"
    assert functions[0].expression == "(x as any) => x"


def test_parse_functions_empty_file(tmp_path):
    content = "// no functions here\n"
    path = tmp_path / "functions.tmdl"
    path.write_text(content, encoding="utf-8")
    functions = _parse_functions(str(path))
    assert functions == []


def test_classify_connector_wins_over_combine_of_local_steps():
    m = (
        'let\n'
        '    Source = SharePoint.Files("https://example.com/sites/x", [ApiVersion = 15]),\n'
        '    StepOne = Table.SelectRows(Source, each [Extension] = ".csv"),\n'
        '    StepTwo = Table.SelectRows(Source, each [Extension] = ".txt"),\n'
        '    Combined = Table.Combine({StepOne, StepTwo})\n'
        'in\n'
        '    Combined'
    )
    expr = _classify_m_content(m, "t")
    assert expr.source_type == "connector"
    assert (expr.connector_namespace, expr.connector_function) == ("SharePoint", "Files")
    assert expr.sharepoint_url == "https://example.com/sites/x"
    assert expr.classification_reason == "connector call SharePoint.Files"


def test_classify_combine_maps_step_aliases_to_queries():
    m = (
        'let\n'
        '    Source = #"q-a",\n'
        '    other = #"q-b",\n'
        '    Combined = Table.Combine({Source, other})\n'
        'in\n'
        '    Combined'
    )
    expr = _classify_m_content(m, "t")
    assert expr.source_type == "table_combine"
    assert expr.combine_sources == ["q-a", "q-b"]
    assert expr.classification_reason == "combine of 2 queries"


def test_classify_combine_of_local_steps_only_is_not_a_combine():
    m = (
        'let\n'
        '    StepOne = Table.SelectRows(#"q-a", each [x] = 1),\n'
        '    StepTwo = Table.SelectRows(StepOne, each [x] = 2),\n'
        '    Combined = Table.Combine({StepOne, StepTwo})\n'
        'in\n'
        '    Combined'
    )
    expr = _classify_m_content(m, "t")
    assert expr.source_type != "table_combine"
    assert expr.combine_sources == []


def test_classify_native_query_over_redshift():
    m = 'let s = Value.NativeQuery(AmazonRedshift.Database("h", "db"), "select 1") in s'
    expr = _classify_m_content(m, "t")
    assert expr.source_type == "connector"
    assert (expr.connector_namespace, expr.connector_function) == ("AmazonRedshift", "Database")
    assert expr.is_native_query is True
    assert expr.native_query == "select 1"


def test_classify_excel_local_file():
    m = 'let s = Excel.Workbook(File.Contents("D:\\Data\\x.xlsx"), true) in s'
    expr = _classify_m_content(m, "t")
    assert (expr.connector_namespace, expr.connector_function) == ("Excel", "Workbook")
    assert expr.file_name == "D:\\Data\\x.xlsx"
    assert expr.url == ""


def test_classify_excel_web_url():
    m = 'let s = Excel.Workbook(Web.Contents("https://example.com/x.xlsx"), true) in s'
    expr = _classify_m_content(m, "t")
    assert (expr.connector_namespace, expr.connector_function) == ("Excel", "Workbook")
    assert expr.file_name == ""
    assert expr.url == "https://example.com/x.xlsx"


def test_classify_calendar_alias_keeps_reference_and_flags_builds_table():
    m = (
        'let\n'
        '    #"seed-day" = #"first-day-helper",\n'
        '    Dates = List.Generate(() => #"seed-day", each _ < #date(2030, 1, 1), each Date.AddDays(_, 1)),\n'
        '    Calendar = Table.FromList(Dates, Splitter.SplitByNothing())\n'
        'in\n'
        '    Calendar'
    )
    expr = _classify_m_content(m, "Calendar")
    assert expr.source_type == "derived"
    assert expr.derived_from == "first-day-helper"
    assert expr.builds_table is True


def test_classify_generated_without_query_reference():
    m = (
        'let\n'
        '    Dates = List.Dates(#date(2030, 1, 1), 31, #duration(1, 0, 0, 0)),\n'
        '    Calendar = Table.FromList(Dates, Splitter.SplitByNothing())\n'
        'in\n'
        '    Calendar'
    )
    expr = _classify_m_content(m, "Calendar")
    assert expr.source_type == "generated"
    assert expr.builds_table is True
    assert expr.classification_reason == "generated in M"


def test_classify_reference_wins_over_scratch_builders():
    builders = [
        "Table.FromRecords({[a = 1]})",
        "List.Numbers(1, 3)",
        "List.Generate(() => 0, each _ < 3, each _ + 1)",
    ]
    for builder in builders:
        m = (
            'let\n'
            '    Source = #"real-query",\n'
            f'    Extra = {builder},\n'
            '    Result = Table.SelectRows(Source, each true)\n'
            'in\n'
            '    Result'
        )
        expr = _classify_m_content(m, "t")
        assert expr.source_type == "derived", builder
        assert expr.derived_from == "real-query", builder
        assert expr.builds_table is True, builder


def test_classify_typed_function_expression():
    block = (
        'fnLoad = (x as text) as table =>\n'
        '\t\tlet\n'
        '\t\t    s = Sql.Database("srv", "db")\n'
        '\t\tin\n'
        '\t\t    s\n'
    )
    expr = _classify_expression(block, "fnLoad")
    assert expr.source_type == "function_def"
    assert expr.classification_reason == "function signature"


def test_classify_connector_namespace_with_digits():
    db2 = _classify_m_content('let s = DB2.Database("h", "db") in s', "t")
    assert (db2.source_type, db2.connector_namespace, db2.connector_function) == ("connector", "DB2", "Database")
    assert db2.server == "h"
    d365 = _classify_m_content('let s = Dynamics365.FinanceAndOperations("https://example.com") in s', "t")
    assert (d365.source_type, d365.connector_namespace) == ("connector", "Dynamics365")
    assert d365.url == "https://example.com"


def test_classify_every_exit_sets_a_reason():
    contents = [
        ("let x = 1 in x", "Number"),
        ('#table({"a"}, {{1}})', ""),
        ("Table.FromRows({{1}})", ""),
        ('let s = Sql.Database("srv", "db") in s', ""),
        ('let s = Table.Combine({#"a", #"b"}) in s', ""),
        ("let l = List.Numbers(1, 3), t = Table.FromList(l) in t", ""),
        ('let Source = #"base" in Source', ""),
        ("let x = SomeUnknownThing(y) in x", ""),
    ]
    for content, result_type in contents:
        assert _classify_m_content(content, "t", result_type).classification_reason != ""
    blocks = [
        ('p = "x" meta [IsParameterQuery=true, Type="Text"]', "p"),
        ("f = (x) => x\n\tannotation PBI_ResultType = Function", "f"),
        ("s = 1\n\tannotation PBI_ResultType = Number", "s"),
        ('q = let s = Sql.Database("srv", "db") in s', "q"),
    ]
    for block, name in blocks:
        assert _classify_expression(block, name).classification_reason != ""
