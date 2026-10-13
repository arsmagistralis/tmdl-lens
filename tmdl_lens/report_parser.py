"""
report_parser.py - Read-only parser for the PBIR report layer.

Reads <name>.Report/definition/ (report.json, pages/pages.json,
pages/<page>/page.json and pages/<page>/visuals/<visual>/visual.json)
into pages, visuals and every model field each of them references,
tagged with how it is used. Stage A of report-layer usage: no output
uses it yet. Never writes, and never raises for bad content; problems
are collected in ReportLayer.problems.
"""

import json
import os
from dataclasses import dataclass, field

_FIELD_KEYS = ("Column", "Measure", "Aggregation", "HierarchyLevel")

_NOT_A_FIELD = object()

_PATH_USAGE = (
    ("queryState", "projection"),
    ("sortDefinition", "sort"),
    ("filterConfig", "filter"),
    ("objects", "formatting"),
    ("visualContainerObjects", "formatting"),
)


@dataclass(frozen=True)
class FieldRef:
    table: str
    name: str
    kind: str
    hierarchy: str = ""


@dataclass(frozen=True)
class FieldUsage:
    field: FieldRef
    usage: str
    role: str = ""


@dataclass
class Visual:
    name: str
    visual_type: str
    is_group: bool
    parent_group: str
    is_hidden: bool
    usages: list = field(default_factory=list)


@dataclass
class Page:
    name: str
    display_name: str
    is_hidden: bool
    filters: list = field(default_factory=list)
    visuals: list = field(default_factory=list)


@dataclass
class ReportLayer:
    pages: list = field(default_factory=list)
    filters: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def _read_json(path: str, rel: str, problems: list):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        problems.append(f"{rel}: cannot be read ({type(e).__name__})")
        return None


def _source_table(expression, aliases: dict):
    source = expression.get("SourceRef") if isinstance(expression, dict) else None
    if not isinstance(source, dict):
        return None
    if isinstance(source.get("Entity"), str):
        return source["Entity"]
    if isinstance(source.get("Source"), str):
        return aliases.get(source["Source"])
    return None


def _field_ref(key: str, value, aliases: dict):
    if not isinstance(value, dict):
        return None
    if key in ("Column", "Measure"):
        table = _source_table(value.get("Expression"), aliases)
        name = value.get("Property")
        if table and isinstance(name, str):
            return FieldRef(table=table, name=name, kind=key.lower())
        return None
    if key == "Aggregation":
        inner = value.get("Expression")
        if isinstance(inner, dict):
            for inner_key in ("Column", "Measure"):
                if inner_key in inner:
                    return _field_ref(inner_key, inner[inner_key], aliases)
        return _NOT_A_FIELD
    hierarchy = value.get("Expression", {}).get("Hierarchy") if isinstance(value.get("Expression"), dict) else None
    level = value.get("Level")
    if not isinstance(hierarchy, dict) or not isinstance(level, str):
        return None
    expression = hierarchy.get("Expression")
    if isinstance(expression, dict) and isinstance(expression.get("PropertyVariationSource"), dict):
        variation = expression["PropertyVariationSource"]
        table = _source_table(variation.get("Expression"), aliases)
        name = variation.get("Property")
        if table and isinstance(name, str):
            return FieldRef(table=table, name=name, kind="column")
        return None
    table = _source_table(expression, aliases)
    name = hierarchy.get("Hierarchy")
    if table and isinstance(name, str):
        return FieldRef(table=table, name=level, kind="hierarchy_level", hierarchy=name)
    return None


def _usage_for(path: list) -> tuple[str, str]:
    for i, key in enumerate(path):
        for marker, usage in _PATH_USAGE:
            if key == marker:
                role = path[i + 1] if usage == "projection" and i + 1 < len(path) else ""
                return usage, role
    return "other", ""


def _collect_usages(document, rel: str, problems: list) -> list:
    found: set = set()
    unresolved = [0]

    def walk(node, path: list, aliases: dict) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, path, aliases)
            return
        if not isinstance(node, dict):
            return
        if isinstance(node.get("From"), list):
            aliases = dict(aliases)
            for item in node["From"]:
                if isinstance(item, dict) and isinstance(item.get("Name"), str) and isinstance(item.get("Entity"), str):
                    aliases[item["Name"]] = item["Entity"]
        for key, value in node.items():
            if key in _FIELD_KEYS and isinstance(value, dict):
                ref = _field_ref(key, value, aliases)
                if ref is _NOT_A_FIELD:
                    continue
                if ref is None:
                    unresolved[0] += 1
                else:
                    usage, role = _usage_for(path)
                    found.add(FieldUsage(field=ref, usage=usage, role=role))
                continue
            walk(value, path + [key], aliases)

    walk(document, [], {})
    if unresolved[0]:
        problems.append(f"{rel}: {unresolved[0]} field reference(s) could not be resolved")
    return _sorted_usages(found)


def _sorted_usages(usages) -> list:
    return sorted(
        usages,
        key=lambda u: (u.field.table, u.field.name, u.field.kind, u.field.hierarchy, u.usage, u.role),
    )


def _parse_visual(visual_dir: str, rel: str, problems: list):
    document = _read_json(os.path.join(visual_dir, "visual.json"), f"{rel}/visual.json", problems)
    if not isinstance(document, dict):
        if document is not None:
            problems.append(f"{rel}/visual.json: expected a JSON object")
        return None
    visual = document.get("visual") if isinstance(document.get("visual"), dict) else {}
    return Visual(
        name=str(document.get("name") or os.path.basename(visual_dir)),
        visual_type=str(visual.get("visualType") or ""),
        is_group="visualGroup" in document,
        parent_group=str(document.get("parentGroupName") or ""),
        is_hidden=bool(document.get("isHidden", False)),
        usages=_collect_usages(document, f"{rel}/visual.json", problems),
    )


def _parse_page(page_dir: str, rel: str, problems: list):
    document = _read_json(os.path.join(page_dir, "page.json"), f"{rel}/page.json", problems)
    if not isinstance(document, dict):
        if document is not None:
            problems.append(f"{rel}/page.json: expected a JSON object")
        return None
    visuals = []
    visuals_dir = os.path.join(page_dir, "visuals")
    if os.path.isdir(visuals_dir):
        for folder in sorted(os.listdir(visuals_dir)):
            visual_dir = os.path.join(visuals_dir, folder)
            if os.path.isfile(os.path.join(visual_dir, "visual.json")):
                visual = _parse_visual(visual_dir, f"{rel}/visuals/{folder}", problems)
                if visual is not None:
                    visuals.append(visual)
    return Page(
        name=str(document.get("name") or os.path.basename(page_dir)),
        display_name=str(document.get("displayName") or ""),
        is_hidden=document.get("visibility") == "HiddenInViewMode",
        filters=_collect_usages(document, f"{rel}/page.json", problems),
        visuals=sorted(visuals, key=lambda v: v.name),
    )


def parse_report_layer(report_dir: str) -> ReportLayer:
    """Parse <name>.Report/definition/ into pages, visuals and field usages."""
    layer = ReportLayer()
    definition = os.path.join(report_dir, "definition")
    pages_dir = os.path.join(definition, "pages")
    if not os.path.isdir(pages_dir):
        if os.path.isfile(os.path.join(report_dir, "report.json")):
            layer.problems.append("PBIR-Legacy report.json is not supported")
        else:
            layer.problems.append("no report definition found")
        return layer

    report_json = os.path.join(definition, "report.json")
    if os.path.isfile(report_json):
        document = _read_json(report_json, "definition/report.json", layer.problems)
        if isinstance(document, dict):
            layer.filters = _collect_usages(document, "definition/report.json", layer.problems)

    order: list = []
    pages_json = os.path.join(pages_dir, "pages.json")
    if os.path.isfile(pages_json):
        meta = _read_json(pages_json, "definition/pages/pages.json", layer.problems)
        if isinstance(meta, dict) and isinstance(meta.get("pageOrder"), list):
            order = [name for name in meta["pageOrder"] if isinstance(name, str)]

    pages = []
    for folder in sorted(os.listdir(pages_dir)):
        page_dir = os.path.join(pages_dir, folder)
        if os.path.isfile(os.path.join(page_dir, "page.json")):
            page = _parse_page(page_dir, f"definition/pages/{folder}", layer.problems)
            if page is not None:
                pages.append(page)
    rank = {name: i for i, name in enumerate(order)}
    layer.pages = sorted(pages, key=lambda p: (rank.get(p.name, len(rank)), p.name))
    return layer
