"""
tmdl_parser.py - Core TMDL semantic model parser for tmdl-lens.

Parses the /definition folder of a Power BI SemanticModel and produces
a SemanticModel dataclass containing tables, relationships, measures,
and raw source expressions ready for resolution.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Column:
    name: str
    data_type: str
    is_calculated: bool = False
    dax_expression: str = ""
    is_hidden: bool = False
    format_string: str = ""
    source_column: str = ""
    summarize_by: str = ""
    sort_by_column: str = ""
    data_category: str = ""
    is_key: bool = False
    lineage_tag: str = ""
    description: str = ""


@dataclass
class Measure:
    name: str
    dax_expression: str
    display_folder: str = ""
    format_string: str = ""
    description: str = ""
    is_hidden: bool = False
    lineage_tag: str = ""


@dataclass
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str = ""
    is_active: bool = True
    cross_filtering_behavior: str = "oneDirection"
    security_filtering_behavior: str = "oneDirection"


@dataclass
class TableFilter:
    table: str
    dax_filter: str


@dataclass
class SecurityRole:
    name: str
    table_filters: list = field(default_factory=list)
    is_dynamic: bool = False
    dynamic_function: str = ""  # "USERPRINCIPALNAME" | "USERNAME" | ""


@dataclass
class CalculationItem:
    name: str
    ordinal: int = 0
    dax_expression: str = ""
    format_string_expression: str = ""


@dataclass
class UserFunction:
    name: str
    expression: str = ""
    description: str = ""


@dataclass
class MParameter:
    """An M query parameter (IsParameterQuery = true)."""
    name: str
    value: str
    param_type: str = "Text"


@dataclass
class PhysicalTableRef:
    schema: str = ""
    table: str = ""
    source: str = "navigation"  # navigation | native_query


@dataclass
class SourceExpression:
    """
    One entry from expressions.tmdl - a shared M query or M parameter.
    Also used for inline M sources classified directly from table files.

    source_type values:
      connector           any external data connector (identity in
                          connector_namespace/connector_function)
      table_combine       Table.Combine({...}) - union of queries
      embedded            Table.FromRows() hardcoded data
      hardcoded           #table(...) inline data
      derived             references another expression via Source = #"name"
      derived_table       references another table inline
      parameter           IsParameterQuery = true
      function_def        custom function definition
      scalar_helper       returns a scalar value, not a table
      generated           table built from scratch in M (List.Generate etc.)
      unknown             could not be classified
    """
    name: str
    source_type: str = "unknown"
    query_group: str = ""
    raw_m: str = ""
    classification_reason: str = ""
    builds_table: bool = False

    # Connector identity (populated when source_type == "connector")
    connector_namespace: str = ""
    connector_function: str = ""
    is_native_query: bool = False

    # Dataflow fields
    workspace_id: str = ""
    dataflow_id: str = ""
    entity: str = ""

    # SQL fields
    server: str = ""
    database: str = ""
    schema: str = ""
    table_or_view: str = ""
    native_query: str = ""

    # ODBC fields
    dsn: str = ""

    # SharePoint / Excel / CSV fields
    sharepoint_url: str = ""
    file_name: str = ""
    sheet_name: str = ""

    # Web / OData fields
    url: str = ""

    # Azure Storage fields
    account: str = ""
    container: str = ""

    # Derived / combine fields
    derived_from: str = ""
    combine_sources: list = field(default_factory=list)
    physical_tables: list = field(default_factory=list)

    # Custom function / parameter fields
    function_name: str = ""
    function_args: str = ""
    param_value: str = ""
    param_type: str = ""


@dataclass
class Table:
    name: str
    table_type: str
    query_group: str = ""
    partition_type: str = ""
    source_ref: str = ""
    is_hidden: bool = False
    is_loaded: bool = True
    lineage_tag: str = ""
    description: str = ""
    columns: list = field(default_factory=list)
    measures: list = field(default_factory=list)
    calculation_items: list = field(default_factory=list)
    dax_partition: str = ""
    inline_source: Optional["SourceExpression"] = None


@dataclass
class SemanticModel:
    report_name: str
    tables: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    source_expressions: list = field(default_factory=list)
    m_parameters: list = field(default_factory=list)
    security_roles: list = field(default_factory=list)
    functions: list = field(default_factory=list)
    model_culture: str = ""
    model_data_source_version: str = ""
    database_compatibility_level: str = ""


# Transformation functions - these are NOT sources, ignore them
# when detecting `Table.Combine` specifically for appends/unions.
_TRANSFORM_FNS = {
    "Table.NestedJoin",
    "Table.MergeQueries",
    "Table.Join",
}

_STDLIB_NAMESPACES = frozenset({
    "Table", "List", "Text", "Number", "Date", "DateTime", "DateTimeZone", "Time",
    "Duration", "Record", "Json", "Binary", "BinaryFormat", "Splitter", "Combiner",
    "Replacer", "Value", "Type", "Uri", "Logical", "Character", "Expression",
    "Function", "Byte", "Single", "Double", "Decimal", "Currency", "Percentage",
    "Lines", "Comparer", "Culture", "Diagnostics", "Error", "Guid", "Order",
    "Occurrence", "RelativePosition", "Precision", "RoundingMode", "JoinKind",
    "JoinAlgorithm", "MissingField", "QuoteStyle", "ExtraValues", "Compression",
    "Cube", "Variable", "Action", "Embedded",
})



# ---------------------------------------------------------------------------
# Table classification
# ---------------------------------------------------------------------------

def _classify_table(name: str, partition_type: str, content: str) -> str:
    n = name.lower()
    if re.search(r"^\s*calculationGroup\s*$", content, re.MULTILINE):
        return "calc_group"
    if partition_type == "calculated":
        if re.search(r"NAMEOF\s*\(", content):
            return "field_parameter"
        return "calculated"
    if not partition_type or partition_type == "":
        if not re.search(r"\bpartition\b", content):
            return "measures_only"
    if n.startswith("fact") or n.startswith("fct"):
        return "fact"
    if n.startswith("dim") or n.startswith("d_") or n.startswith("d-"):
        return "dim"
    if n.startswith("param") or n.endswith("selector") or n.endswith("parameter"):
        return "field_parameter"
    if n.startswith("_") or n == "measures" or "measure" in n:
        return "measures_only"
    if n.startswith("source") or n.startswith("src"):
        return "staging"
    if n.startswith("helper") or n.startswith("hlp"):
        return "helper"
    if n.startswith("calc") or n.startswith("cg"):
        return "calc_group"
    return "other"


# ---------------------------------------------------------------------------
# Low-level block extractor
# ---------------------------------------------------------------------------

def _extract_blocks(text: str, keyword: str) -> list:
    results = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith(keyword):
            base_indent = len(lines[i]) - len(lines[i].lstrip("\t "))
            block = [lines[i]]
            i += 1
            while i < len(lines):
                if lines[i].strip() == "":
                    block.append(lines[i])
                    i += 1
                    continue
                current_indent = len(lines[i]) - len(lines[i].lstrip("\t "))
                if current_indent > base_indent:
                    block.append(lines[i])
                    i += 1
                else:
                    break
            results.append("\n".join(block))
        else:
            i += 1
    return results


# ---------------------------------------------------------------------------
# Leading /// comment extractor
# ---------------------------------------------------------------------------

def _extract_leading_comments(content: str) -> dict:
    """
    Pre-scan the full table file content for '///' doc-comment lines and
    associate each /// block with the column/measure header immediately
    following it (at the same indent, no blank lines between). Returns a
    dict mapping stripped header line -> joined description text.
    """
    mapping = {}
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Detect start of a /// comment block
        if stripped.startswith("///"):
            indent = len(line) - len(line.lstrip("\t "))
            comments = []
            # Collect all consecutive /// lines at the same indent
            while i < len(lines):
                s = lines[i].strip()
                cur_indent = len(lines[i]) - len(lines[i].lstrip("\t "))
                if s.startswith("///") and cur_indent == indent:
                    comments.append(s[len("///"):].lstrip())
                    i += 1
                else:
                    break
            # Skip blank lines (not expected in real TMDL, but tolerate them)
            while i < len(lines) and not lines[i].strip():
                i += 1
            # The next non-blank line at the same indent is the target header
            if i < len(lines):
                next_indent = len(lines[i]) - len(lines[i].lstrip("\t "))
                if next_indent == indent:
                    header = lines[i].strip()
                    mapping[header] = " ".join(comments)
                    continue  # do NOT advance i - let the outer loop handle it
            # If no header followed, don't advance - let outer loop continue
            continue
        else:
            i += 1
    return mapping


# ---------------------------------------------------------------------------
# Tree node parser - shared indentation-tree infrastructure
# ---------------------------------------------------------------------------

@dataclass
class TmdlNode:
    key: str
    value: str = ""
    children: list = field(default_factory=list)
    indent: int = 0


def _parse_tree(lines: list, start: int, parent_indent: int) -> tuple[list, int]:
    """
    Walk lines starting at `start`, treating each line's leading whitespace
    as its indent level. Returns (list_of_TmdlNode_siblings, next_line_index).

    A line becomes a sibling when its indent == parent_indent + 1.
    Key/value split: first `=` or `:` separates key (before) from value (after).
    Triple-backtick values are consumed as raw text (dedented), not recursed.
    Blank lines are skipped.
    """
    nodes = []
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines
        if not stripped:
            i += 1
            continue

        indent = len(line) - len(line.lstrip("\t "))

        # Stop if we've gone back to parent_indent or shallower
        if indent <= parent_indent:
            break

        # Only process lines exactly one level deeper than parent
        if indent != parent_indent + 1:
            i += 1
            continue

        # Split key/value on first = or :
        key = stripped
        value = ""
        sep_pos = -1
        eq_pos = stripped.find("=")
        colon_pos = stripped.find(":")
        if eq_pos >= 0 and colon_pos >= 0:
            sep_pos = eq_pos if eq_pos < colon_pos else colon_pos
        elif eq_pos >= 0:
            sep_pos = eq_pos
        elif colon_pos >= 0:
            sep_pos = colon_pos

        if sep_pos >= 0:
            key = stripped[:sep_pos].rstrip()
            value = stripped[sep_pos + 1:].strip()

        node = TmdlNode(key=key, value=value, indent=indent)

        # Triple-backtick multi-line value
        if value.startswith("```"):
            raw_lines = []
            i += 1
            while i < len(lines):
                if lines[i].strip() == "```":
                    i += 1
                    break
                raw_lines.append(lines[i])
                i += 1
            node.value = _dedent("\n".join(raw_lines))
            nodes.append(node)
            continue

        # If no value and deeper lines follow, recurse for children
        if not value:
            children, i = _parse_tree(lines, i + 1, indent)
            node.children = children
        else:
            i += 1

        nodes.append(node)

    return nodes, i


def _find_child(node: "TmdlNode", key: str) -> Optional["TmdlNode"]:
    for c in node.children:
        if c.key == key:
            return c
    return None


def _find_children(node: "TmdlNode", key: str) -> list:
    return [c for c in node.children if c.key == key]


_COL_PROP_STOP = re.compile(
    r"^(?:dataType|lineageTag|summarizeBy|sourceColumn|formatString|sortByColumn"
    r"|dataCategory|displayFolder|description|isHidden|isKey|isNullable|isUnique"
    r"|annotation|extendedProperty|changedProperty|relatedColumnDetails)\b"
)


# ---------------------------------------------------------------------------
# Column parser
# ---------------------------------------------------------------------------

def _parse_column(block: str, description: str = "") -> Optional[Column]:
    lines = block.split("\n")
    header = lines[0].strip()

    # Detect calculated column: column 'Name' = <dax>, column "Name" = <dax>
    # or a bare simple name - column Name = <dax>
    calc = re.match(
        r"column\s+'((?:[^']|'')+)'\s*=|column\s+\"([^\"]+)\"\s*=|column\s+([^\s'\"=]+?)\s*=",
        header,
    )

    if calc:
        name = (calc.group(1) or calc.group(2) or calc.group(3)).strip()
        name = name.replace("''", "'")
        # Parse children via tree parser
        base_indent = len(lines[0]) - len(lines[0].lstrip("\t "))
        children, _ = _parse_tree(lines, 1, base_indent)
        root = TmdlNode(key="", children=children)

        # DAX: inline from header, or accumulated from children before known properties
        dax = ""
        inline_dax_match = re.match(
            r"column\s+(?:'(?:[^']|'')+'|\"[^\"]+\"|[^\s'\"]+?)\s*=\s*(.+)$", header
        )

        if inline_dax_match:
            dax = inline_dax_match.group(1).strip().rstrip("`").strip()
        else:
            dax_lines = []
            for line in lines[1:]:
                s = line.strip()
                if _COL_PROP_STOP.match(s):
                    break
                dax_lines.append(line)
            dax = "\n".join(dax_lines).strip().lstrip("=").strip().rstrip("`").strip()

        is_hidden = _find_child(root, "isHidden") is not None
        fmt_node_calc = _find_child(root, "formatString")
        format_string_calc = fmt_node_calc.value.strip().strip("'\"") if fmt_node_calc else ""
        sc_node_calc = _find_child(root, "sourceColumn")
        source_column_calc = sc_node_calc.value.strip().strip("'\"") if sc_node_calc else ""
        sb_node_calc = _find_child(root, "summarizeBy")
        summarize_by_calc = sb_node_calc.value.strip().strip("'\"") if sb_node_calc else ""
        sort_node_calc = _find_child(root, "sortByColumn")
        sort_by_column_calc = sort_node_calc.value.strip().strip("'\"") if sort_node_calc else ""
        dc_node_calc = _find_child(root, "dataCategory")
        data_category_calc = dc_node_calc.value.strip().strip("'\"") if dc_node_calc else ""
        is_key_calc = _find_child(root, "isKey") is not None
        lt_node_calc = _find_child(root, "lineageTag")
        lineage_tag_calc = lt_node_calc.value.strip().strip("'\"") if lt_node_calc else ""
        return Column(name=name, data_type="calculated", is_calculated=True,
                      dax_expression=dax, is_hidden=is_hidden,
                      format_string=format_string_calc,
                      source_column=source_column_calc,
                      summarize_by=summarize_by_calc,
                      sort_by_column=sort_by_column_calc,
                      data_category=data_category_calc,
                      is_key=is_key_calc,
                      lineage_tag=lineage_tag_calc,
                      description=description)

    # Plain column: column 'Name' or column "Name" or column barename
    plain = re.match(
        r"column\s+'((?:[^']|'')+)'\s*$|column\s+\"([^\"]+)\"\s*$|column\s+(\S+)\s*$",
        header,
    )
    if plain:
        name = (plain.group(1) or plain.group(2) or plain.group(3)).strip()
        name = name.replace("''", "'")
        # Parse children via tree parser
        base_indent = len(lines[0]) - len(lines[0].lstrip("\t "))
        children, _ = _parse_tree(lines, 1, base_indent)
        root = TmdlNode(key="", children=children)

        dt_node = _find_child(root, "dataType")
        data_type = dt_node.value if dt_node else "unknown"
        is_hidden = _find_child(root, "isHidden") is not None
        fmt_node_plain = _find_child(root, "formatString")
        format_string_plain = fmt_node_plain.value.strip().strip("'\"") if fmt_node_plain else ""
        sc_node_plain = _find_child(root, "sourceColumn")
        source_column_plain = sc_node_plain.value.strip().strip("'\"") if sc_node_plain else ""
        sb_node_plain = _find_child(root, "summarizeBy")
        summarize_by_plain = sb_node_plain.value.strip().strip("'\"") if sb_node_plain else ""
        sort_node_plain = _find_child(root, "sortByColumn")
        sort_by_column_plain = sort_node_plain.value.strip().strip("'\"") if sort_node_plain else ""
        dc_node_plain = _find_child(root, "dataCategory")
        data_category_plain = dc_node_plain.value.strip().strip("'\"") if dc_node_plain else ""
        is_key_plain = _find_child(root, "isKey") is not None
        lt_node_plain = _find_child(root, "lineageTag")
        lineage_tag_plain = lt_node_plain.value.strip().strip("'\"") if lt_node_plain else ""
        return Column(
            name=name,
            data_type=data_type,
            is_hidden=is_hidden,
            format_string=format_string_plain,
            source_column=source_column_plain,
            summarize_by=summarize_by_plain,
            sort_by_column=sort_by_column_plain,
            data_category=data_category_plain,
            is_key=is_key_plain,
            lineage_tag=lineage_tag_plain,
            description=description,
        )
    return None


# ---------------------------------------------------------------------------
# Measure parser
# ---------------------------------------------------------------------------

def _parse_measure(block: str, leading_description: str = "") -> Optional[Measure]:
    lines = block.split("\n")
    header = lines[0].strip()
    m = re.match(
        r"measure\s+(?:'((?:[^']|'')+)'|\"([^\"]+)\"|([^\s'\"=]+))(?:\s*=|$)",
        header,
    )
    if not m:
        return None
    name = (m.group(1) or m.group(2) or m.group(3)).strip()
    name = name.replace("''", "'")

    # Inline DAX from header
    inline = re.match(
        r"measure\s+(?:'(?:[^']|'')+'|\"[^\"]+\"|[^\s'\"=]+?)\s*=\s*(.+)$",
        header,
    )
    inline_dax = inline.group(1).strip() if inline else ""

    # Parse children via tree parser
    base_indent = len(lines[0]) - len(lines[0].lstrip("\t "))
    children, _ = _parse_tree(lines, 1, base_indent)
    root = TmdlNode(key="", children=children)

    # Multi-line DAX: lines before the first known property key
    # NOTE: isHidden is a bare flag node (no colon value), but it appears
    # as a child line in the TMDL block before property-key lines like
    # lineageTag or formatString. Without isHidden in the stop-list, the
    # line "isHidden" would leak into multiline_dax. Since the tree parser
    # already captures it as a child node, we only need to stop DAX collection
    # from the raw lines at property names that start with known keywords.
    dax_lines, in_dax = [], True
    for line in lines[1:]:
        s = line.strip()
        if re.match(r"(formatString|displayFolder|lineageTag|isHidden|annotation|description):", s) or s == "isHidden":
            in_dax = False
        if in_dax:
            dax_lines.append(line)
    multiline_dax = "\n".join(dax_lines).strip().rstrip("`").strip()

    # Look up properties from tree
    folder_node = _find_child(root, "displayFolder")
    fmt_node = _find_child(root, "formatString")
    desc_node = _find_child(root, "description")
    hidden_node = _find_child(root, "isHidden")
    lineage_node = _find_child(root, "lineageTag")

    display_folder = folder_node.value.strip().strip("'\"") if folder_node else ""
    format_string = fmt_node.value.strip().strip("'\"") if fmt_node else ""
    # Precedence: /// comment wins over description: property
    prop_description = desc_node.value.strip().strip("'\"") if desc_node else ""
    description = leading_description if leading_description else prop_description
    is_hidden = hidden_node is not None
    lineage_tag = lineage_node.value.strip().strip("'\"") if lineage_node else ""

    return Measure(
        name=name,
        dax_expression=multiline_dax if multiline_dax else inline_dax,
        display_folder=display_folder,
        format_string=format_string,
        description=description,
        is_hidden=is_hidden,
        lineage_tag=lineage_tag,
    )


# ---------------------------------------------------------------------------
# Calculation items parser
# ---------------------------------------------------------------------------

def _dedent(text: str) -> str:
    lines = text.split("\n")
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    min_indent = min(indents) if indents else 0
    return "\n".join(l[min_indent:] if len(l) >= min_indent else l for l in lines).strip()


def _split_prop_value(stripped: str) -> str:
    """Return the inline value after the first '=' or ':' on a property line."""
    for sep in ("=", ":"):
        if sep in stripped:
            return stripped.split(sep, 1)[1].strip()
    return ""


def _read_fenced_value(lines: list, start: int) -> tuple[str, int]:
    """Read a triple-backtick value whose content starts at line index `start`
    (right after the opening fence). Returns (value, next_line_index); the
    closing ``` line is consumed when present, a missing fence reads to EOF.
    """
    raw = []
    i = start
    while i < len(lines) and lines[i].strip() != "```":
        raw.append(lines[i])
        i += 1
    i += 1  # skip the closing fence (or run just past EOF)
    return _dedent("\n".join(raw)), i


# Property lines that can appear under a calculationItem - the fallback DAX
# scan stops at the first one (mirrors _parse_measure's property stop-list).
_PROP_START_RE = re.compile(
    r"^(?:ordinal|expression|formatStringExpression|formatString|"
    r"displayFolder|lineageTag|isHidden|annotation|description)\b"
)


def _parse_calculation_items(content: str) -> list:
    items = []
    blocks = _extract_blocks(content, "calculationItem ")
    for position, block in enumerate(blocks):
        lines = block.split("\n")
        header = lines[0].strip()
        header_indent = len(lines[0]) - len(lines[0].lstrip("\t "))

        name_m = (
            re.match(r"calculationItem\s+'((?:[^']|'')+)'", header) or
            re.match(r'calculationItem\s+"([^"]+)"', header) or
            re.match(r"calculationItem\s+(\S+)", header)
        )
        if not name_m:
            continue
        name = name_m.group(1).strip()
        name = name.replace("''", "'")

        # Inline expression on the header line: calculationItem NAME = <dax>
        rest = header[name_m.end():].strip()
        inline_rhs = rest[1:].strip() if rest.startswith("=") else ""

        dax = ""
        ordinal = position
        fmt_expr = ""

        # Style A: calculationItem NAME = ``` <DAX> ``` (DAX fenced on header)
        child_start = 1
        if inline_rhs.startswith("```"):
            dax, child_start = _read_fenced_value(lines, 1)
        elif inline_rhs:
            dax = inline_rhs

        # Style B: DAX lives under an `expression` child property.
        expr_prop = ""

        # Walk the remaining child lines for ordinal / expression /
        # formatStringExpression, stopping at a sibling line.
        i = child_start
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            indent = len(line) - len(line.lstrip("\t "))
            if indent <= header_indent:
                break
            if stripped == "```":
                i += 1
                continue
            if stripped.startswith("ordinal"):
                try:
                    ordinal = int(_split_prop_value(stripped))
                except ValueError:
                    pass
                i += 1
            elif stripped.startswith("expression"):
                val = _split_prop_value(stripped)
                if val.startswith("```"):
                    expr_prop, i = _read_fenced_value(lines, i + 1)
                else:
                    expr_prop = val
                    i += 1
            elif stripped.startswith("formatStringExpression"):
                val = _split_prop_value(stripped)
                if val.startswith("```"):
                    fmt_expr, i = _read_fenced_value(lines, i + 1)
                else:
                    fmt_expr = val.strip().strip("'\"")
                    i += 1
            else:
                i += 1

        if not dax and expr_prop:
            dax = expr_prop

        # Fallback: DAX written directly under the item header without an
        # inline = or expression property (measure-like multiline layout).
        if not dax:
            raw = []
            for line in lines[1:]:
                stripped = line.strip()
                if not stripped:
                    continue
                indent = len(line) - len(line.lstrip("\t "))
                if indent <= header_indent:
                    break
                if _PROP_START_RE.match(stripped):
                    break
                if stripped == "```":
                    continue
                raw.append(line)
            if raw:
                dax = _dedent("\n".join(raw)).rstrip("`").strip()

        items.append(CalculationItem(
            name=name,
            ordinal=ordinal,
            dax_expression=dax,
            format_string_expression=fmt_expr,
        ))

    items.sort(key=lambda x: x.ordinal)
    return items


# ---------------------------------------------------------------------------
# M comment stripping
# ---------------------------------------------------------------------------

def _strip_m_comments(content: str) -> str:
    """Remove /* ... */ block comments and // line comments.
    Preserves // inside quoted strings (e.g., "https://...").
    """
    # Remove block comments first
    content = re.sub(r"/\*[\s\S]*?\*/", "", content)

    # Remove line comments: // not inside double quotes
    lines = content.split("\n")
    result_lines = []
    for line in lines:
        in_string = False
        new_line = []
        i = 0
        while i < len(line):
            char = line[i]
            if char == '"' and (i == 0 or line[i-1] != '\\'):
                in_string = not in_string
                new_line.append(char)
                i += 1
                continue
            if not in_string and char == '/' and i + 1 < len(line) and line[i+1] == '/':
                break
            new_line.append(char)
            i += 1
        result_lines.append(''.join(new_line))
    return "\n".join(result_lines)


_SCALAR_RESULT_TYPES = ("Text", "Number", "Date", "DateTime", "Boolean")

_CONNECTOR_CALL_RE = re.compile(r'\b([A-Z][A-Za-z0-9]+)\.([A-Z][A-Za-z0-9]+)\s*\(')

_COMBINE_RE = re.compile(r'\bTable\.(?:Combine|Append)\s*\(\s*\{')

_SCRATCH_BUILDER_RE = re.compile(
    r'\b(?:List\.(?:Generate|Dates|DateTimes|Numbers)|Table\.(?:FromList|FromRecords|FromColumns))\s*\('
)

_STEP_NAME = r'(?:#"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)'

_STEP_ASSIGN_RE = re.compile(r'(?:\blet\b|,)\s*(' + _STEP_NAME + r')\s*=(?![=>])')

_STEP_ALIAS_RE = re.compile(
    r'(?:\blet\b|,)\s*(' + _STEP_NAME + r')\s*=\s*#"([^"]+)"\s*(?=,|\bin\b|$)'
)

_REFERENCE_EXCLUDED = frozenset({
    "let", "in", "each", "true", "false", "null",
    "Table", "List", "Record", "Json", "Xml", "Csv",
    "Excel", "File", "Text", "Date", "DateTime", "Binary",
    "Number", "Duration", "Time", "Splitter", "Combiner",
    "Lines", "Type", "Function", "Uri", "Compression",
    "Value", "Expression", "Metadata", "Error",
})


def _step_key(token: str) -> str:
    return token[2:-1] if token.startswith('#"') else token


def _split_top_level(text: str) -> list:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    for ch in text:
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                items.append("".join(current))
                current = []
                continue
        current.append(ch)
    items.append("".join(current))
    return [item.strip() for item in items if item.strip()]


def _combine_items(clean: str) -> list:
    match = _COMBINE_RE.search(clean)
    if not match:
        return []
    start = match.end() - 1
    depth = 1
    end = start + 1
    while depth > 0 and end < len(clean):
        if clean[end] == "{":
            depth += 1
        elif clean[end] == "}":
            depth -= 1
        end += 1
    if depth != 0:
        return []
    return _split_top_level(clean[start + 1:end - 1])


def _combine_sources(clean: str, items: list) -> list:
    aliases = {_step_key(m.group(1)): m.group(2) for m in _STEP_ALIAS_RE.finditer(clean)}
    steps = {_step_key(m.group(1)) for m in _STEP_ASSIGN_RE.finditer(clean)}
    sources: list[str] = []
    for item in items:
        if not re.fullmatch(_STEP_NAME, item):
            continue
        key = _step_key(item)
        if key in aliases:
            name = aliases[key]
        elif key in steps:
            continue
        elif not item.startswith('#"') and key in _REFERENCE_EXCLUDED:
            continue
        else:
            name = key
        if name not in sources:
            sources.append(name)
    return sources


def _first_step_reference(clean: str) -> Optional[tuple]:
    ref_quoted = re.search(r'\bSource\s*=\s*#"([^"]+)"', clean)
    if ref_quoted:
        return "derived", ref_quoted.group(1)

    ref_bare = re.search(
        r'\bSource\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?=,|\n|$)',
        clean, re.MULTILINE
    )
    if ref_bare:
        ref = ref_bare.group(1).strip()
        after = clean[ref_bare.end():].lstrip()
        if not after.startswith("(") and ref not in _REFERENCE_EXCLUDED:
            return "derived_table", ref

    alias_quoted = re.search(
        r'\blet\s+(?:[A-Za-z_][A-Za-z0-9_]*|#"[^"]+")\s*=\s*#"([^"]+)"',
        clean,
    )
    if alias_quoted:
        return "derived", alias_quoted.group(1)

    alias_bare = re.search(
        r'\blet\s+(?:[A-Za-z_][A-Za-z0-9_]*|#"[^"]+")\s*=\s*([A-Za-z_][A-Za-z0-9_]*)(?=\s*(?:,|in\b)|$)',
        clean,
    )
    if alias_bare:
        ref = alias_bare.group(1).strip()
        if ref not in _REFERENCE_EXCLUDED:
            return "derived_table", ref

    return None


def _classify_m_content(content: str, table_name: str, result_type: str = "") -> SourceExpression:
    """
    Classify the data source of an M partition by scanning the full content
    (with comments stripped). The precedence order is documented in
    docs/parser-internals.md. Returns a populated SourceExpression.
    """
    expr = SourceExpression(name=table_name, raw_m=content)
    clean = _strip_m_comments(content)
    expr.builds_table = _SCRATCH_BUILDER_RE.search(clean) is not None

    if result_type in _SCALAR_RESULT_TYPES:
        expr.source_type = "scalar_helper"
        expr.classification_reason = f"annotation PBI_ResultType = {result_type}"
        return expr

    if "#table(" in clean:
        expr.source_type = "hardcoded"
        expr.classification_reason = "inline data literal"
        return expr
    if "Table.FromRows(" in clean:
        expr.source_type = "embedded"
        expr.classification_reason = "inline data literal"
        return expr

    for call in _CONNECTOR_CALL_RE.finditer(clean):
        namespace, function = call.group(1), call.group(2)
        if namespace in _STDLIB_NAMESPACES or f"{namespace}.{function}" in _TRANSFORM_FNS:
            continue
        expr.source_type = "connector"
        expr.connector_namespace = namespace
        expr.connector_function = function
        expr.classification_reason = f"connector call {namespace}.{function}"
        _extract_connector_details(expr, clean, namespace, function)
        return expr

    items = _combine_items(clean)
    if items:
        sources = _combine_sources(clean, items)
        if sources:
            expr.source_type = "table_combine"
            expr.combine_sources = sources
            expr.classification_reason = f"combine of {len(sources)} queries"
            return expr

    reference = _first_step_reference(clean)
    if reference:
        expr.source_type, expr.derived_from = reference
        expr.classification_reason = f"first step references {expr.derived_from}"
        return expr

    if expr.builds_table:
        expr.source_type = "generated"
        expr.classification_reason = "generated in M"
        return expr

    expr.classification_reason = "no connector, combine or query reference found"
    return expr


def _extract_string_or_param_arg(clean: str, pattern_quoted: str, pattern_bare: str) -> Optional[str]:
    """
    Try to extract a connector argument as a quoted string literal first.
    If that fails, try again treating the argument as a bare M identifier
    (an M parameter reference) and return it wrapped as "[param:Name]" -
    the exact marker format source_resolver.py's _resolve_param already
    expects and substitutes.
    Returns None if neither pattern matches.
    """
    m = re.search(pattern_quoted, clean)
    if m:
        return m.group(1)
    m = re.search(pattern_bare, clean)
    if m:
        return f"[param:{m.group(1)}]"
    return None


def _native_query_from_value_native_query(clean: str) -> str:
    start = re.search(r'Value\.NativeQuery\s*\(', clean)
    if not start:
        return ""
    i = start.end()
    depth = 1
    args: list[str] = []
    current: list[str] = []
    in_string = False
    while i < len(clean) and depth > 0:
        ch = clean[i]
        if in_string:
            if ch == '"':
                if clean[i:i + 2] == '""':
                    current.append('""')
                    i += 2
                    continue
                in_string = False
            current.append(ch)
        elif ch == '"':
            in_string = True
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append("".join(current))
                break
            current.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if len(args) < 2:
        return ""
    second = args[1].strip()
    if len(second) >= 2 and second[0] == second[-1] == '"':
        return second[1:-1].replace('""', '"')
    return ""


def _extract_connector_details(expr: SourceExpression, clean: str, namespace: str, function: str) -> None:
    """Populates detail fields on expr based on namespace/function. Mutates in place."""

    if (namespace, function) in (("PowerBI", "Dataflows"), ("PowerPlatform", "Dataflows")):
        wid    = re.search(r'workspaceId\s*=\s*"([^"]+)"', clean)
        dfid   = re.search(r'dataflowId\s*=\s*"([^"]+)"', clean)
        entity = re.search(r'entity\s*=\s*"([^"]+)"', clean)
        if wid:    expr.workspace_id = wid.group(1)
        if dfid:   expr.dataflow_id  = dfid.group(1)
        if entity: expr.entity       = entity.group(1)

    elif namespace in ("Sql", "AzureSQL", "AmazonRedshift") and function == "Database":
        # Extract server argument (first parameter)
        server_quoted_pattern = r'(?:Sql|AzureSQL|AmazonRedshift)\.Database\s*\(\s*"([^"]*)"'
        server_bare_pattern = r'(?:Sql|AzureSQL|AmazonRedshift)\.Database\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.server = _extract_string_or_param_arg(clean, server_quoted_pattern, server_bare_pattern) or ""
        
        # Extract database argument (second parameter)
        database_quoted_pattern = r'(?:Sql|AzureSQL|AmazonRedshift)\.Database\s*\([^,]+,\s*"([^"]*)"'
        database_bare_pattern = r'(?:Sql|AzureSQL|AmazonRedshift)\.Database\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.database = _extract_string_or_param_arg(clean, database_quoted_pattern, database_bare_pattern) or ""
        native = re.search(r'\[Query\s*=\s*"([^"]+)"\]', clean)
        if native:
            expr.is_native_query = True
            expr.native_query    = native.group(1)
        else:
            native_vq = _native_query_from_value_native_query(clean)
            if native_vq:
                expr.is_native_query = True
                expr.native_query    = native_vq
            else:
                for nav in re.finditer(r'\{?\[Schema\s*=\s*"([^"]*)"\s*,\s*Item\s*=\s*"([^"]*)"\]?\}\[Data\]', clean):
                    schema_val = nav.group(1)
                    item_val   = nav.group(2)
                    expr.physical_tables.append(PhysicalTableRef(schema=schema_val, table=item_val, source="navigation"))
                if expr.physical_tables:
                    expr.schema        = expr.physical_tables[0].schema
                    expr.table_or_view = expr.physical_tables[0].table
                else:
                    tbl = re.search(r'Schema\s*=\s*"([^"]+)"\s*,\s*Item\s*=\s*"([^"]+)"', clean)
                    if tbl:
                        expr.schema        = tbl.group(1)
                        expr.table_or_view = tbl.group(2)
                if re.search(r'Value\.NativeQuery\s*\(', clean):
                    for ref in expr.physical_tables:
                        ref.source = "native_query"

    elif namespace == "Dataverse" and function == "Feed":
        quoted_pattern = r'Dataverse\.Feed\s*\(\s*"([^"]+)"'
        bare_pattern = r'Dataverse\.Feed\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif namespace == "Odbc" and function == "DataSource":
        quoted_pattern = r'Odbc\.DataSource\s*\(\s*"([^"]+)"'
        bare_pattern = r'Odbc\.DataSource\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.dsn = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif (function == "Database" and namespace in ("Oracle", "MySql", "PostgreSQL", "DB2", "SapHana")) \
            or (namespace == "Snowflake" and function == "Databases"):
        # Extract server argument (first parameter)
        server_patterns = {
            "Oracle":     (r'Oracle\.Database\s*\(\s*"([^"]*)"', r'Oracle\.Database\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "MySql":      (r'MySql\.Database\s*\(\s*"([^"]*)"', r'MySql\.Database\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "PostgreSQL": (r'PostgreSQL\.Database\s*\(\s*"([^"]*)"', r'PostgreSQL\.Database\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "DB2":        (r'DB2\.Database\s*\(\s*"([^"]*)"', r'DB2\.Database\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "SapHana":    (r'SapHana\.Database\s*\(\s*"([^"]*)"', r'SapHana\.Database\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "Snowflake":  (r'Snowflake\.Databases\s*\(\s*"([^"]*)"', r'Snowflake\.Databases\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
        }
        if namespace in server_patterns:
            server_quoted, server_bare = server_patterns[namespace]
            expr.server = _extract_string_or_param_arg(clean, server_quoted, server_bare) or ""
        
        # Extract database argument (second parameter)
        database_patterns = {
            "Oracle":     (r'Oracle\.Database\s*\([^,]+,\s*"([^"]*)"', r'Oracle\.Database\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "MySql":      (r'MySql\.Database\s*\([^,]+,\s*"([^"]*)"', r'MySql\.Database\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "PostgreSQL": (r'PostgreSQL\.Database\s*\([^,]+,\s*"([^"]*)"', r'PostgreSQL\.Database\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "DB2":        (r'DB2\.Database\s*\([^,]+,\s*"([^"]*)"', r'DB2\.Database\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "SapHana":    (r'SapHana\.Database\s*\([^,]+,\s*"([^"]*)"', r'SapHana\.Database\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "Snowflake":  (r'Snowflake\.Databases\s*\([^,]+,\s*"([^"]*)"', r'Snowflake\.Databases\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)'),
        }
        if namespace in database_patterns:
            database_quoted, database_bare = database_patterns[namespace]
            expr.database = _extract_string_or_param_arg(clean, database_quoted, database_bare) or ""

    elif namespace == "Teradata" and function == "Database":
        quoted_pattern = r'Teradata\.Database\s*\(\s*"([^"]+)"'
        bare_pattern = r'Teradata\.Database\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.server = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif namespace == "Databricks" and function in ("Catalogs", "Contents"):
        quoted_pattern = r'Databricks\.(?:Catalogs|Contents)\s*\(\s*"([^"]+)"'
        bare_pattern = r'Databricks\.(?:Catalogs|Contents)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.server = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif namespace == "SharePoint" and function in ("Files", "Tables"):
        quoted_pattern = r'SharePoint\.(?:Files|Tables)\s*\(\s*"([^"]+)"'
        bare_pattern = r'SharePoint\.(?:Files|Tables)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.sharepoint_url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""
        if "Excel.Workbook" in clean:
            # Extract file_name from File.Contents
            fn_quoted = r'\[Name\]\s*=\s*"([^"]+\.xlsx?)"'
            fn_bare = r'\[Name\]\s*=\s*([A-Za-z_][A-Za-z0-9_]*)'
            expr.file_name = _extract_string_or_param_arg(clean, fn_quoted, fn_bare) or ""
            sheet = re.search(r'Item\s*=\s*"([^"]+)"', clean)
            if sheet:
                expr.sheet_name = sheet.group(1)
        else:
            lst = re.search(r'Name\s*=\s*"([^"]+)"', clean)
            if lst:
                expr.table_or_view = lst.group(1)

    elif namespace == "Excel" and function == "Workbook":
        quoted_pattern = r'File\.Contents\s*\(\s*"([^"]+)"'
        bare_pattern = r'File\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.file_name = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""
        if not expr.file_name:
            web_quoted = r'Web\.Contents\s*\(\s*"([^"]+)"'
            web_bare = r'Web\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
            expr.url = _extract_string_or_param_arg(clean, web_quoted, web_bare) or ""
        sheet = re.search(r'Item\s*=\s*"([^"]+)"', clean)
        if sheet:
            expr.sheet_name = sheet.group(1)

    elif namespace == "Csv" and function == "Document":
        quoted_pattern = r'File\.Contents\s*\(\s*"([^"]+)"'
        bare_pattern = r'File\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.file_name = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif (namespace, function) in (("Web", "Contents"), ("OData", "Feed")):
        quoted_pattern = r'(?:Web\.Contents|OData\.Feed)\s*\(\s*"([^"]+)"'
        bare_pattern = r'(?:Web\.Contents|OData\.Feed)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""
        entity = re.search(r'Name\s*=\s*"([^"]+)"', clean)
        if entity:
            expr.table_or_view = entity.group(1)

    elif (namespace, function) in (("SmartsheetGlobal", "Contents"), ("Smartsheet", "Tables")):
        # Only SmartsheetGlobal has the region parameter, Smartsheet.Tables doesn't
        if namespace == "SmartsheetGlobal":
            quoted_pattern = r'SmartsheetGlobal\.Contents\s*\(\s*"([^"]+)"'
            bare_pattern = r'SmartsheetGlobal\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
            expr.url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif (namespace, function) == ("AzureDevOps", "Contents"):
        quoted_pattern = r'AzureDevOps\.Contents\s*\(\s*"([^"]+)"'
        bare_pattern = r'AzureDevOps\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif (namespace, function) == ("Dynamics365", "FinanceAndOperations"):
        quoted_pattern = r'Dynamics365\.FinanceAndOperations\s*\(\s*"([^"]+)"'
        bare_pattern = r'Dynamics365\.FinanceAndOperations\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'
        expr.url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif namespace in ("GoogleSheets", "QuickBooks", "GitHub") and function == "Contents":
        patterns = {
            "GoogleSheets": (r'GoogleSheets\.Contents\s*\(\s*"([^"]+)"', r'GoogleSheets\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "QuickBooks":   (r'QuickBooks\.Contents\s*\(\s*"([^"]+)"', r'QuickBooks\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
            "GitHub":       (r'GitHub\.Contents\s*\(\s*"([^"]+)"', r'GitHub\.Contents\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)'),
        }
        if namespace in patterns:
            quoted_pattern, bare_pattern = patterns[namespace]
            expr.url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif namespace == "Salesforce" and function in ("Data", "Reports"):
        quoted_pattern = r"Salesforce\.(?:Data|Reports)\s*\(\s*\"([^\"]+)\""
        bare_pattern = r"Salesforce\.(?:Data|Reports)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)"
        expr.url = _extract_string_or_param_arg(clean, quoted_pattern, bare_pattern) or ""

    elif namespace == "AzureStorage" and function in ("Blobs", "BlobContents", "Table", "DataLake", "DataLakeContents"):
        acct_quoted = r"AzureStorage\.(?:Blobs|BlobContents|Table|DataLake|DataLakeContents)\s*\(\s*\"([^\"]*)\""
        acct_bare = r"AzureStorage\.(?:Blobs|BlobContents|Table|DataLake|DataLakeContents)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)"
        expr.account = _extract_string_or_param_arg(clean, acct_quoted, acct_bare) or ""
        if function in ("Blobs", "BlobContents", "DataLake", "DataLakeContents"):
            cont_quoted = r"AzureStorage\.(?:Blobs|BlobContents|DataLake|DataLakeContents)\s*\([^,]+,\s*\"([^\"]*)\""
            cont_bare = r"AzureStorage\.(?:Blobs|BlobContents|DataLake|DataLakeContents)\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)"
            expr.container = _extract_string_or_param_arg(clean, cont_quoted, cont_bare) or ""

    # ARCH-03 - unconditional navigation fallbacks.
    # Pattern A (Schema/Item) and Pattern B (Name chain) are Power BI's own
    # navigation syntax, not connector vocabulary - if either appears in the M
    # code, navigation to a physical table happened, regardless of connector.
    # Specific branches above remain as label/detail upgraders only; when a
    # branch already populated physical_tables, these fallbacks do nothing.
    if not expr.physical_tables:
        nav_tag = "native_query" if re.search(r'Value\.NativeQuery\s*\(', clean) else "navigation"
        for nav in re.finditer(r'\{?\[Schema\s*=\s*"([^"]*)"\s*,\s*Item\s*=\s*"([^"]*)"\]?\}\[Data\]', clean):
            expr.physical_tables.append(PhysicalTableRef(schema=nav.group(1), table=nav.group(2), source=nav_tag))
    if not expr.physical_tables:
        segments = re.findall(r'\{?\[Name\s*=\s*"([^"]+)"\]\}?\[Data\]', clean)
        if segments:
            last = segments[-1]
            second_last = segments[-2] if len(segments) >= 2 else ""
            tag = "native_query" if re.search(r'Value\.NativeQuery\s*\(', clean) else "navigation"
            expr.physical_tables.append(PhysicalTableRef(schema=second_last, table=last, source=tag))


# ---------------------------------------------------------------------------
# Table partition source_ref extractor
#
# Only returns a value when the partition source is a bare #"expression-name"
# reference pointing to expressions.tmdl - no let block, no inline M.
# ---------------------------------------------------------------------------

def _extract_partition_source_ref(content: str) -> str:
    """
    Returns the expression name if this table's partition is a simple
    #"expression-name" pointer to expressions.tmdl. Returns "" otherwise.
    """
    bt = re.search(r"source\s*=\s*```([\s\S]*?)```", content)
    if bt:
        block = bt.group(1).strip()
        if "let" not in block.lower():
            ref = re.match(r'^#"([^"]+)"\s*$', block)
            if ref:
                return ref.group(1)
        return ""

    m = re.search(r'^\s*source\s*=\s*#"([^"]+)"\s*$', content, re.MULTILINE)
    if m:
        return m.group(1)

    return ""


# ---------------------------------------------------------------------------
# Table file parser
# ---------------------------------------------------------------------------

def _parse_table_file(filepath: str) -> Optional[Table]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    header_line = None
    header_indent = 0
    for i, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        name_match = re.match(r"^table\s+(.+)$", stripped)
        if not name_match:
            return None
        name = _unquote(name_match.group(1))
        header_line = stripped
        header_indent = len(raw_line) - len(raw_line.lstrip("\t "))
        header_index = i
        break
    else:
        return None

    # Tree-parse the table header's direct children (indent 0 -> indent 1)
    children, _ = _parse_tree(lines, header_index + 1, header_indent)
    table_root = TmdlNode(key="", children=children)

    is_hidden   = _find_child(table_root, "isHidden") is not None
    lineage_tag = ""
    lt_node = _find_child(table_root, "lineageTag")
    if lt_node:
        lineage_tag = lt_node.value.strip().strip("'\"")

    comment_map = _extract_leading_comments(content)
    description = comment_map.get(header_line, "")

    qg = re.search(r"queryGroup:\s*'?([^'\n]+)'?", content)
    query_group = qg.group(1).strip().strip("'\"") if qg else ""

    pt = re.search(
        r"^\s*partition\s+(?:'[^']*'|\"[^\"]*\"|\S+)\s*=\s*(\w+)",
        content, re.MULTILINE
    )
    partition_type = pt.group(1).strip() if pt else ""

    rt_m = re.search(r"PBI_ResultType\s*=\s*(\S+)", content)
    result_type = rt_m.group(1).strip() if rt_m else ""

    table_type = _classify_table(name, partition_type, content)
    is_loaded  = "TabularEditor_EnableLoad = false" not in content
    source_ref = _extract_partition_source_ref(content) if partition_type == "m" else ""

    dax_partition = ""
    if partition_type == "calculated":
        dax_m = re.search(
            r"^\s*source\s*=\s*([\s\S]+?)(?=\n\s*annotation|\n\s*changedProperty|\Z)",
            content, re.MULTILINE
        )
        if dax_m:
            dax_partition = dax_m.group(1).strip()

    inline_source = None
    if partition_type == "m" and not source_ref:
        inline_source = _classify_m_content(content, name, result_type)

    columns = []
    for b in _extract_blocks(content, "column "):
        header = b.split("\n")[0].strip()
        col = _parse_column(b, description=comment_map.get(header, ""))
        if col:
            columns.append(col)

    measures = []
    for b in _extract_blocks(content, "measure "):
        header = b.split("\n")[0].strip()
        m = _parse_measure(b, leading_description=comment_map.get(header, ""))
        if m:
            measures.append(m)
    calculation_items = _parse_calculation_items(content) if table_type == "calc_group" else []

    return Table(
        name=name,
        table_type=table_type,
        query_group=query_group,
        partition_type=partition_type,
        source_ref=source_ref,
        is_hidden=is_hidden,
        is_loaded=is_loaded,
        lineage_tag=lineage_tag,
        description=description,
        columns=columns,
        measures=measures,
        calculation_items=calculation_items,
        dax_partition=dax_partition,
        inline_source=inline_source,
    )


# ---------------------------------------------------------------------------
# Relationship parser
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r"^\s*('(?:[^']|'')+'|[^.']+)\.('(?:[^']|'')+'|.+?)\s*$")


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] == "'":
        return name[1:-1].replace("''", "'")
    if len(name) >= 2 and name[0] == name[-1] == '"':
        return name[1:-1].replace('""', '"')
    return name


def _split_table_column(ref: str) -> tuple[str, str]:
    m = _REF_RE.match(ref)
    return (_unquote(m.group(1)), _unquote(m.group(2))) if m else ("", "")


def _parse_relationships(filepath: str) -> list:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    rels = []
    normalised = re.sub(r"^relationship\s+", "\nrelationship ", content, count=1)
    for block in re.split(r"\nrelationship\s+", normalised):
        lines = block.split("\n")
        # header at indent 0, properties at indent 1
        children, _ = _parse_tree(lines, 1, 0)
        root = TmdlNode(key="", children=children)

        from_node = _find_child(root, "fromColumn")
        to_node   = _find_child(root, "toColumn")
        if not from_node or not to_node:
            continue

        from_card_m = _find_child(root, "fromCardinality")
        to_card_m   = _find_child(root, "toCardinality")
        from_card = from_card_m.value.strip() if from_card_m else "many"
        to_card   = to_card_m.value.strip()   if to_card_m   else "one"

        if from_card == "one" and to_card == "many":
            cardinality = "One-to-Many"
        elif from_card == "many" and to_card == "one":
            cardinality = "Many-to-One"
        elif from_card == "many" and to_card == "many":
            cardinality = "Many-to-Many"
        elif from_card == "one" and to_card == "one":
            cardinality = "One-to-One"
        else:
            cardinality = f"{from_card.capitalize()}-to-{to_card.capitalize()}"

        is_active_node = _find_child(root, "isActive")
        active = not (is_active_node and is_active_node.value.strip() == "false")

        # Add tree lookups for crossFilteringBehavior and securityFilteringBehavior
        cfb_node = _find_child(root, "crossFilteringBehavior")
        sfb_node = _find_child(root, "securityFilteringBehavior")
        cross_filtering = cfb_node.value.strip().strip("'\"") if cfb_node else "oneDirection"
        security_filtering = sfb_node.value.strip().strip("'\"") if sfb_node else "oneDirection"

        from_table, from_column = _split_table_column(from_node.value.strip())
        to_table, to_column = _split_table_column(to_node.value.strip())
        if from_table and from_column and to_table and to_column:
            rels.append(Relationship(
                from_table=from_table,
                from_column=from_column,
                to_table=to_table,
                to_column=to_column,
                cardinality=cardinality,
                is_active=active,
                cross_filtering_behavior=cross_filtering,
                security_filtering_behavior=security_filtering,
            ))
    return rels


# ---------------------------------------------------------------------------
# Roles parser
# ---------------------------------------------------------------------------

def _parse_roles(filepath: str) -> list:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    roles = []
    normalised = re.sub(r"^role\s+", "\nrole ", content, count=1)
    for block in re.split(r"\nrole\s+", normalised):
        block = block.strip()
        if not block:
            continue

        name_m = (
            re.match(r"'((?:[^']|'')+)'", block) or
            re.match(r'"([^"]+)"', block) or
            re.match(r"(\S+)", block)
        )
        if not name_m:
            continue
        name = name_m.group(1).strip()
        name = name.replace("''", "'")
        if name.startswith("//"):
            continue

        lines = block.split("\n")

        filters = []
        i = 1
        while i < len(lines):
            stripped = lines[i].strip()
            perm_m = re.match(
                r"tablePermission\s+('(?:[^']|'')+'|\"[^\"]+\"|[^\s=]+)\s*(?:=(.*))?$",
                stripped,
            )
            if not perm_m:
                i += 1
                continue
            table_name = _unquote(perm_m.group(1))
            value_part = (perm_m.group(2) or "").strip()
            if value_part.startswith("```"):
                dax, i = _read_fenced_value(lines, i + 1)
                filters.append(TableFilter(table=table_name, dax_filter=dax))
                continue
            if value_part:
                filters.append(TableFilter(table=table_name, dax_filter=value_part))
                i += 1
                continue
            perm_indent = len(lines[i]) - len(lines[i].lstrip("\t "))
            collected = []
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if not line.strip():
                    j += 1
                    continue
                indent = len(line) - len(line.lstrip("\t "))
                if indent <= perm_indent:
                    break
                collected.append(line)
                j += 1
            filters.append(TableFilter(table=table_name, dax_filter=_dedent("\n".join(collected))))
            i = j

        is_dynamic = False
        dynamic_fn = ""
        all_dax = " ".join(f.dax_filter for f in filters)
        if "USERPRINCIPALNAME()" in all_dax.upper():
            is_dynamic, dynamic_fn = True, "USERPRINCIPALNAME"
        elif "USERNAME()" in all_dax.upper():
            is_dynamic, dynamic_fn = True, "USERNAME"

        roles.append(SecurityRole(
            name=name,
            table_filters=filters,
            is_dynamic=is_dynamic,
            dynamic_function=dynamic_fn,
        ))

    return roles


def _parse_functions(filepath: str) -> list:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    comment_map = _extract_leading_comments(content)
    functions = []
    for block in _extract_blocks(content, "function "):
        lines = block.split("\n")
        header = lines[0].strip()
        m = re.match(
            r"function\s+(?:'((?:[^']|'')+)'|\"([^\"]+)\"|([^\s'\"=]+))\s*=(?:\s*(.*))?$",
            header,
        )
        if not m:
            continue
        name = (m.group(1) or m.group(2) or m.group(3)).strip()
        name = name.replace("''", "'")
        if name.startswith("//"):
            continue

        inline = (m.group(4) or "").strip()
        if inline.startswith("```"):
            expression, _next = _read_fenced_value(lines, 1)
        elif inline:
            expression = inline
        else:
            dax_lines = []
            for line in lines[1:]:
                s = line.strip()
                if re.match(r"(formatString|displayFolder|lineageTag|isHidden|annotation|description):", s) or s == "isHidden":
                    break
                dax_lines.append(line)
            expression = "\n".join(dax_lines).strip().rstrip("`").strip()

        description = comment_map.get(header, "")
        functions.append(UserFunction(
            name=name,
            expression=expression,
            description=description,
        ))

    return functions


# ---------------------------------------------------------------------------
# Model / database level parser
# ---------------------------------------------------------------------------

def _parse_model_database(definition_path: str) -> tuple[str, str, str]:
    """
    Reads model.tmdl and database.tmdl for the three Overview-level fields
    in scope for this stage. Returns (culture, data_source_version,
    compatibility_level) - each "" if the file or property is absent.
    """
    culture = ""
    data_source_version = ""
    compatibility_level = ""

    model_file = os.path.join(definition_path, "model.tmdl")
    if os.path.exists(model_file):
        with open(model_file, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        # model header is indent 0, its direct properties are indent 1
        children, _ = _parse_tree(lines, 1, 0)
        root = TmdlNode(key="", children=children)
        culture_node = _find_child(root, "culture")
        if culture_node:
            culture = culture_node.value.strip().strip("'\"")
        version_node = _find_child(root, "defaultPowerBIDataSourceVersion")
        if version_node:
            data_source_version = version_node.value.strip().strip("'\"")

    database_file = os.path.join(definition_path, "database.tmdl")
    if os.path.exists(database_file):
        with open(database_file, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        children, _ = _parse_tree(lines, 1, 0)
        root = TmdlNode(key="", children=children)
        compat_node = _find_child(root, "compatibilityLevel")
        if compat_node:
            compatibility_level = compat_node.value.strip().strip("'\"")

    return culture, data_source_version, compatibility_level


# ---------------------------------------------------------------------------
# Expression classifier (expressions.tmdl)
#
# Shared expressions already have their M extracted cleanly by the
# expressions parser, so we use the same content-scan approach here.
# ---------------------------------------------------------------------------

_FUNC_SIGNATURE_RE = re.compile(
    r"\([^)]*\)\s*(?:as\s+(?:nullable\s+)?[A-Za-z_.]+\s*)?=>"
)


def _is_function_expression(block: str) -> bool:
    rt_m = re.search(r"PBI_ResultType\s*=\s*(\S+)", block)
    if rt_m:
        return rt_m.group(1).strip() == "Function"
    header = re.match(
        r"(?:expression\s+)?(?:'(?:[^']|'')+'|\"[^\"]+\"|[^\s=]+)\s*=", block
    )
    body = block[header.end():] if header else block
    body = body.lstrip()
    if body.startswith("```"):
        body = body[3:].lstrip()
    return _FUNC_SIGNATURE_RE.match(body) is not None


def _classify_expression(block: str, name: str) -> SourceExpression:
    expr = SourceExpression(name=name, raw_m=block)

    qg = re.search(r"queryGroup:\s*'?([^'\n]+)'?", block)
    if qg:
        expr.query_group = qg.group(1).strip().strip("'\"")

    if "IsParameterQuery=true" in block or "IsParameterQuery = true" in block:
        expr.source_type = "parameter"
        expr.classification_reason = "IsParameterQuery = true"
        val = re.match(r"['\"]?" + re.escape(name) + r"['\"]?\s*=\s*(.+?)\s+meta", block, re.DOTALL)
        if val:
            expr.param_value = val.group(1).strip().strip('"')
        t = re.search(r'Type\s*=\s*"([^"]+)"', block)
        expr.param_type = t.group(1) if t else "Text"
        return expr

    rt_m = re.search(r"PBI_ResultType\s*=\s*(\S+)", block)
    rt = rt_m.group(1).strip() if rt_m else ""

    if _is_function_expression(block):
        expr.source_type = "function_def"
        expr.classification_reason = (
            "annotation PBI_ResultType = Function" if rt else "function signature"
        )
        return expr

    if rt in ("Date", "DateTime", "Number", "Text", "Boolean") and "Table" not in rt:
        expr.source_type = "scalar_helper"
        expr.classification_reason = f"annotation PBI_ResultType = {rt}"
        return expr

    classified = _classify_m_content(block, name)
    classified.query_group = expr.query_group
    return classified


# ---------------------------------------------------------------------------
# Expressions.tmdl parser
# ---------------------------------------------------------------------------

def _parse_expressions(filepath: str) -> tuple[list, list]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    source_expressions: list[SourceExpression] = []
    m_parameters: list[MParameter] = []

    blocks = re.split(r"(?:^|\n)expression\s+", content)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        name_m = (
            re.match(r"'((?:[^']|'')+)'\s*=", block) or
            re.match(r'"([^"]+)"\s*=', block) or
            re.match(r"([^\s=]+)\s*=", block)
        )
        if not name_m:
            continue
        name = name_m.group(1).strip()
        name = name.replace("''", "'")
        if name.startswith("//"):
            continue

        expr = _classify_expression(block, name)

        if expr.source_type == "parameter":
            m_parameters.append(MParameter(
                name=name,
                value=expr.param_value,
                param_type=expr.param_type,
            ))
        else:
            source_expressions.append(expr)

    return source_expressions, m_parameters


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_semantic_model(model_folder: str, report_name: str) -> SemanticModel:
    model = SemanticModel(report_name=report_name)
    definition_path = os.path.join(model_folder, "definition")

    if not os.path.isdir(definition_path):
        return model

    expressions_file = os.path.join(definition_path, "expressions.tmdl")
    if os.path.exists(expressions_file):
        model.source_expressions, model.m_parameters = _parse_expressions(expressions_file)

    relationships_file = os.path.join(definition_path, "relationships.tmdl")
    if os.path.exists(relationships_file):
        model.relationships = _parse_relationships(relationships_file)

    roles_dir = os.path.join(definition_path, "roles")
    security_roles: list = []
    if os.path.isdir(roles_dir):
        for filename in sorted(os.listdir(roles_dir)):
            if filename.endswith(".tmdl"):
                security_roles.extend(_parse_roles(os.path.join(roles_dir, filename)))
    legacy_roles_file = os.path.join(definition_path, "roles.tmdl")
    if os.path.exists(legacy_roles_file):
        security_roles.extend(_parse_roles(legacy_roles_file))
    model.security_roles = security_roles

    functions_file = os.path.join(definition_path, "functions.tmdl")
    if os.path.exists(functions_file):
        model.functions = _parse_functions(functions_file)

    model.model_culture, model.model_data_source_version, model.database_compatibility_level = \
        _parse_model_database(definition_path)

    tables_path = os.path.join(definition_path, "tables")
    if os.path.isdir(tables_path):
        for filename in sorted(os.listdir(tables_path)):
            if filename.endswith(".tmdl"):
                tbl = _parse_table_file(os.path.join(tables_path, filename))
                if tbl:
                    model.tables.append(tbl)

    return model