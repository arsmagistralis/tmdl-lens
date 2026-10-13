"""Tests for the typed JSON writer and its published schema."""

import copy
import glob
import json
import os
import re
import subprocess
import sys

import pytest

from tmdl_lens import json_writer
from tmdl_lens.json_writer import generate_json
from tmdl_lens.source_resolver import resolve_sources
from tmdl_lens.tmdl_parser import (
    Column,
    Measure,
    Relationship,
    SemanticModel,
    SourceExpression,
    Table,
    _parse_relationships,
    parse_semantic_model,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(REPO_ROOT, "docs", "tmdl-lens-output.schema.json")
SAMPLE_MODEL_DIR = os.path.join(REPO_ROOT, "sample", "tmdl-lens-test-report.SemanticModel")


def _schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _deref(schema, root):
    while "$ref" in schema:
        schema = root["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _same(value, expected):
    return type(value) is type(expected) and value == expected


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def _errors(value, schema, root, path="$"):
    schema = _deref(schema, root)
    if "oneOf" in schema:
        matches = [s for s in schema["oneOf"] if not _errors(value, s, root, path)]
        return [] if len(matches) == 1 else [f"{path}: matches {len(matches)} oneOf branches"]
    if "const" in schema and not _same(value, schema["const"]):
        return [f"{path}: {value!r} is not {schema['const']!r}"]
    if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
        return [f"{path}: {value!r} not in enum"]
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPE_CHECKS[t](value) for t in types):
            return [f"{path}: {value!r} is not {types}"]
    errors = []
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: unexpected {key}" for key in value if key not in properties]
        for key, sub in properties.items():
            if key in value:
                errors += _errors(value[key], sub, root, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += _errors(item, schema["items"], root, f"{path}[{i}]")
    return errors


def _sample():
    model = parse_semantic_model(SAMPLE_MODEL_DIR, "tmdl-lens-test-report")
    return model, resolve_sources(model.source_expressions, model.m_parameters, tables=model.tables)


def _json(model, resolved, include_dax=True):
    return json.loads(generate_json(model, resolved, {"report_name": "r", "include_dax": include_dax}))


def _sorted_named_lists(value, path="$"):
    problems = []
    if isinstance(value, dict):
        for key, sub in value.items():
            problems += _sorted_named_lists(sub, f"{path}.{key}")
    elif isinstance(value, list):
        names = [item["name"] for item in value if isinstance(item, dict) and "name" in item]
        if names and names != sorted(names):
            problems.append(path)
        for i, item in enumerate(value):
            problems += _sorted_named_lists(item, f"{path}[{i}]")
    return problems


JSON_GOLDENS = sorted(glob.glob(os.path.join(REPO_ROOT, "tests", "golden", "*.json")))


def test_json_goldens_exist():
    assert len(JSON_GOLDENS) == 4


@pytest.mark.parametrize("path", JSON_GOLDENS, ids=os.path.basename)
def test_json_golden_validates_against_schema(path):
    with open(path, encoding="utf-8") as f:
        document = json.load(f)
    assert _errors(document, _schema(), _schema()) == []


def test_schema_checker_rejects_bad_documents():
    model, resolved = _sample()
    good = _json(model, resolved)
    root = _schema()
    assert _errors(good, root, root) == []
    for mutate in (
        lambda d: d["tables"][0].__setitem__("kind", "bogus"),
        lambda d: d.__setitem__("schema_version", "2.0"),
        lambda d: d["relationships"][0].__setitem__("cardinality", "Many-to-One"),
        lambda d: d["tables"][0].__setitem__("extra", 1),
        lambda d: d["tables"][0].pop("source"),
        lambda d: d["model"].__setitem__("compatibility_level", "1605"),
    ):
        bad = copy.deepcopy(good)
        mutate(bad)
        assert _errors(bad, root, root) != []


def test_schema_enums_match_writer_constants():
    defs = _schema()["$defs"]
    assert set(defs["table"]["properties"]["kind"]["enum"]) == (
        set(json_writer._SUPPORT_KIND.values()) | {"loaded", "not_loaded"}
    )
    resolved_branch = defs["source"]["oneOf"][2]
    assert tuple(resolved_branch["properties"]["type"]["enum"]) == json_writer.SOURCE_TYPES
    relationship = defs["relationship"]["properties"]
    assert set(relationship["cardinality"]["enum"]) == set(json_writer._CARDINALITY.values()) | {None}
    assert set(relationship["cross_filter"]["enum"]) == set(json_writer._CROSS_FILTER.values()) | {None}
    assert set(relationship["security_filter"]["enum"]) == set(json_writer._SECURITY_FILTER.values()) | {None}
    details = set(resolved_branch["properties"]["details"]["properties"])
    assert details == {key for key, _ in json_writer._DETAIL_FIELDS}


def test_cardinality_and_filters_map_from_parser_values(tmp_path):
    content = "".join(
        f"relationship r{i}\n"
        f"\tfromColumn: A.c{i}\n"
        f"\ttoColumn: B.c{i}\n"
        f"\tfromCardinality: {from_card}\n"
        f"\ttoCardinality: {to_card}\n"
        f"\tcrossFilteringBehavior: {cross}\n"
        f"\tsecurityFilteringBehavior: {security}\n\n"
        for i, (from_card, to_card, cross, security) in enumerate([
            ("one", "many", "bothDirections", "bothDirections"),
            ("many", "one", "automatic", "none"),
            ("many", "many", "oneDirection", "oneDirection"),
            ("one", "one", "oneDirection", "oneDirection"),
        ])
    )
    path = tmp_path / "relationships.tmdl"
    path.write_text(content, encoding="utf-8")
    model = SemanticModel(report_name="r", relationships=_parse_relationships(str(path)))
    rels = {r["from_column"]: r for r in _json(model, {})["relationships"]}
    assert [rels[f"c{i}"]["cardinality"] for i in range(4)] == [
        "one_to_many", "many_to_one", "many_to_many", "one_to_one",
    ]
    assert rels["c0"]["cross_filter"] == "both_directions"
    assert rels["c1"]["cross_filter"] == "automatic"
    assert rels["c1"]["security_filter"] == "none"
    assert rels["c2"]["security_filter"] == "one_direction"


def test_unknown_cardinality_is_null():
    model = SemanticModel(report_name="r", relationships=[
        Relationship(from_table="A", from_column="x", to_table="B", to_column="y", cardinality="manyToOne"),
    ])
    assert _json(model, {})["relationships"][0]["cardinality"] is None


def test_unresolved_table_has_explicit_gap():
    table = Table(
        name="T",
        table_type="fact",
        partition_type="m",
        inline_source=SourceExpression(name="T", source_type="derived", derived_from="ghost"),
    )
    model = SemanticModel(report_name="r", tables=[table])
    resolved = resolve_sources([], [], tables=[table])
    source = _json(model, resolved)["tables"][0]["source"]
    assert source == {"resolved": False, "reason": resolved["T"].unresolved_reason}
    warnings = _json(model, resolved)["warnings"]
    assert warnings == [{"code": "unresolved_source", "object": "T", "table": None, "detail": resolved["T"].unresolved_reason}]


def test_calculated_table_has_null_source_and_dax_expression():
    table = Table(name="Dates", table_type="calculated", partition_type="calculated", dax_partition="CALENDARAUTO()")
    model = SemanticModel(report_name="r", tables=[table])
    with_dax = _json(model, {})["tables"][0]
    assert with_dax["kind"] == "calculated"
    assert with_dax["source"] is None
    assert with_dax["expression"] == "CALENDARAUTO()"
    assert _json(model, {}, include_dax=False)["tables"][0]["expression"] is None


def test_include_dax_false_nulls_expressions_and_keeps_warnings():
    model, resolved = _sample()
    with_dax = _json(model, resolved)
    without = _json(model, resolved, include_dax=False)
    assert without["warnings"] == with_dax["warnings"]
    assert any(w["code"] == "hidden_reference" for w in without["warnings"])
    for table in without["tables"]:
        assert table["expression"] is None
        assert all(c["expression"] is None for c in table["columns"])
        assert all(m["expression"] is None for m in table["measures"])
        assert all(i["expression"] is None for i in table["calculation_items"])
    assert all(fn["expression"] is None for fn in without["functions"])


def test_combine_sources_are_filled_and_sorted():
    combined = SourceExpression(name="combined", source_type="table_combine", combine_sources=["q-b", "q-a"])
    table = Table(name="T", table_type="fact", partition_type="m", source_ref="combined")
    model = SemanticModel(report_name="r", tables=[table], source_expressions=[combined])
    resolved = resolve_sources([combined], [], tables=[table])
    document = _json(model, resolved)
    assert document["tables"][0]["source"]["type"] == "table_combine"
    assert document["tables"][0]["source"]["combine_sources"] == ["q-a", "q-b"]
    assert document["expressions"][0]["source"]["combine_sources"] == ["q-a", "q-b"]


def test_every_shared_expression_is_listed():
    model, resolved = _sample()
    names = [e["name"] for e in _json(model, resolved)["expressions"]]
    assert names == sorted(e.name for e in model.source_expressions)
    assert "source-excel-local" in names


def test_output_has_no_timestamp_or_version_and_uses_lf():
    model, resolved = _sample()
    text = generate_json(model, resolved, {"report_name": "r", "include_dax": True})
    assert text.endswith("\n")
    assert "\r" not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)
    assert "version" not in json.loads(text)["report"]
    assert set(json.loads(text)) == set(_schema()["required"])


def test_every_named_list_is_sorted_by_name():
    model, resolved = _sample()
    assert _sorted_named_lists(_json(model, resolved)) == []


def test_output_is_independent_of_input_order():
    model, resolved = _sample()
    reordered = SemanticModel(
        report_name=model.report_name,
        tables=[
            Table(**{**t.__dict__, "columns": list(reversed(t.columns)), "measures": list(reversed(t.measures))})
            for t in reversed(model.tables)
        ],
        relationships=list(reversed(model.relationships)),
        source_expressions=list(reversed(model.source_expressions)),
        m_parameters=list(reversed(model.m_parameters)),
        security_roles=list(reversed(model.security_roles)),
        functions=list(reversed(model.functions)),
        model_culture=model.model_culture,
        model_data_source_version=model.model_data_source_version,
        database_compatibility_level=model.database_compatibility_level,
    )
    reordered_resolved = dict(reversed(list(resolved.items())))
    config = {"report_name": "r", "include_dax": True}
    assert generate_json(reordered, reordered_resolved, config) == generate_json(model, resolved, config)


def test_output_is_identical_across_hash_seeds():
    script = (
        "import sys\n"
        "from tmdl_lens.tmdl_parser import parse_semantic_model\n"
        "from tmdl_lens.source_resolver import resolve_sources\n"
        "from tmdl_lens.json_writer import generate_json\n"
        "m = parse_semantic_model(sys.argv[1], 'r')\n"
        "r = resolve_sources(m.source_expressions, m.m_parameters, tables=m.tables)\n"
        "sys.stdout.buffer.write(generate_json(m, r, {'report_name': 'r', 'include_dax': True}).encode('utf-8'))\n"
    )
    outputs = set()
    for seed in ("0", "1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run(
            [sys.executable, "-c", script, SAMPLE_MODEL_DIR],
            cwd=REPO_ROOT, env=env, capture_output=True, check=True,
        )
        outputs.add(result.stdout)
    assert len(outputs) == 1


def test_hidden_reference_warning_names_object_table_and_target():
    hidden = Table(name="H", table_type="dim", partition_type="m", is_hidden=True,
                   columns=[Column(name="k", data_type="int64")])
    sales = Table(name="S", table_type="fact", partition_type="m",
                  measures=[Measure(name="m1", dax_expression="COUNTROWS(H) + SUM(H[k])")])
    model = SemanticModel(report_name="r", tables=[hidden, sales])
    warnings = _json(model, {})["warnings"]
    assert warnings == [{"code": "hidden_reference", "object": "m1", "table": "S", "detail": "H[k]"}]
