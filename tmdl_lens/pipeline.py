"""
pipeline.py - Documentation generation pipeline for tmdl-lens.

Pure Python, no GUI dependencies. Takes a PipelineConfig and runs the
full documentation generation flow for one or many reports.

Usable from:
  - app.py (CustomTkinter UI)   - passes a logger callback
  - cli.py (future headless mode)
  - CI/CD runners
  - AI agents / MCP servers
"""

import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from tmdl_lens.tmdl_parser import parse_semantic_model
from tmdl_lens.source_resolver import resolve_sources
from tmdl_lens.json_writer import generate_json
from tmdl_lens.readme_generator import generate_readme, generate_html, generate_text
from tmdl_lens.version import __version__


# ---------------------------------------------------------------------------
# Config & result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Pure data structure - no GUI, no tkinter."""

    reports_folder: str
    output_folder: str = ""
    include_dax: bool = True
    include_lineage: bool = False
    output_format: str = "html"  # "html" | "md"
    overwrite: bool = False
    skip_unchanged: bool = False
    owner: str = ""
    team: str = ""
    refresh_schedule: str = ""


@dataclass
class SingleResult:
    """Result of processing one .pbip report."""

    report_name: str
    success: bool = False
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""
    output_path: str = ""
    table_count: int = 0
    measure_count: int = 0
    content_hash: str = ""
    hash_key: str = ""


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""

    success_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    total_count: int = 0
    results: list = field(default_factory=list)
    hashes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _find_pbip_files(reports_folder: str) -> list[str]:
    """Recursively find all .pbip files in a folder."""
    pbip_files = []
    for root, dirs, files in os.walk(reports_folder):
        for f in files:
            if f.endswith(".pbip"):
                pbip_files.append(os.path.join(root, f))
    return pbip_files


def _detect_multi_pbip_folders(pbip_files: list[str]) -> tuple[set, list[str]]:
    """
    Folders containing more than one .pbip file are ambiguous - the
    pipeline cannot know which .SemanticModel folder belongs to which
    report. Returns (set_of_skipped_dirs, list_of_runnable_files).
    """
    folder_map: dict[str, list[str]] = defaultdict(list)
    for p in pbip_files:
        folder_map[os.path.dirname(p)].append(p)

    skipped_dirs = {d for d, files in folder_map.items() if len(files) > 1}
    runnable = [p for p in pbip_files if os.path.dirname(p) not in skipped_dirs]
    return skipped_dirs, runnable


def _get_output_path(
    pbip_dir: str,
    pbip_name: str,
    output_format: str,
    custom_out: str,
) -> str:
    """Resolve the output file path for one report."""
    if output_format == "html":
        out_filename = f"{pbip_name}.html"
    elif output_format in ("txt", "json"):
        out_filename = f"{pbip_name}.{output_format}"
    else:
        out_filename = "README.md"
    if custom_out:
        # Each report gets its own subfolder so multiple reports never collide
        return os.path.join(custom_out, pbip_name, out_filename)
    return os.path.join(pbip_dir, out_filename)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _report_dir(pbip_dir: str, pbip_data) -> str:
    if not isinstance(pbip_data, dict):
        return ""
    artifacts = pbip_data.get("artifacts")
    if not isinstance(artifacts, list):
        return ""
    for artifact in artifacts:
        report = artifact.get("report") if isinstance(artifact, dict) else None
        if isinstance(report, dict) and isinstance(report.get("path"), str):
            return os.path.join(pbip_dir, report["path"])
    return ""


def _locate_model(pbip_path: str) -> tuple[str, str]:
    """
    Find the semantic model folder of one .pbip report. Returns
    (model_dir, problem); exactly one is non-empty. Precedence: the .pbip
    report artifact, then that report's definition.pbir datasetReference,
    then the <pbip name>.SemanticModel guess.
    """
    pbip_dir = os.path.dirname(pbip_path)
    pbip_name = os.path.splitext(os.path.basename(pbip_path))[0]

    report_dir = _report_dir(pbip_dir, _read_json(pbip_path))
    pbir = _read_json(os.path.join(report_dir, "definition.pbir")) if report_dir else None
    reference = pbir.get("datasetReference") if isinstance(pbir, dict) else None
    if isinstance(reference, dict):
        by_path = reference.get("byPath")
        if isinstance(by_path, dict) and isinstance(by_path.get("path"), str):
            target = os.path.normpath(os.path.join(report_dir, by_path["path"]))
            if os.path.isdir(target):
                return target, ""
            return "", f"definition.pbir points to a missing folder: {by_path['path']}"
        if "byConnection" in reference:
            return "", "report uses a live connection (byConnection), no local semantic model"

    guess = os.path.join(pbip_dir, f"{pbip_name}.SemanticModel")
    if os.path.isdir(guess):
        return guess, ""
    return "", "no semantic model folder"


def _model_problem(model_dir: str) -> str:
    """Return "" when the model folder holds a TMDL definition/ folder."""
    if os.path.isdir(os.path.join(model_dir, "definition")):
        return ""
    if os.path.exists(os.path.join(model_dir, "model.bim")):
        return "model.bim (TMSL) is not supported, save the project with TMDL"
    return "no definition folder"


def _build_gen_config(report_name: str, config: PipelineConfig) -> dict:
    """Build the generator config dict for one report."""
    return {
        "report_name":      report_name,
        "owner":            config.owner,
        "team":             config.team,
        "refresh_schedule": config.refresh_schedule,
        "include_dax":      config.include_dax,
        "include_lineage":  config.include_lineage,
    }


def _content_hash(model_dir: str, config: PipelineConfig, out_path: str) -> str:
    """SHA256 of the report's TMDL content plus generator-relevant config."""
    h = hashlib.sha256()
    tmdl_files = []
    for root, _, files in os.walk(model_dir):
        for f in files:
            if f.endswith(".tmdl"):
                tmdl_files.append(os.path.join(root, f))
    tmdl_files.sort()
    for path in tmdl_files:
        rel = os.path.relpath(path, model_dir)
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        with open(path, "rb") as fh:
            h.update(fh.read())
        h.update(b"\x00")
    config_blob = json.dumps(
        {
            "include_dax":      config.include_dax,
            "include_lineage":  config.include_lineage,
            "output_format":    config.output_format,
            "owner":            config.owner,
            "team":             config.team,
            "refresh_schedule": config.refresh_schedule,
            "output_path":      out_path,
            "tool_version":     __version__,
        },
        sort_keys=True,
    )
    h.update(config_blob.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Pipeline:
    """
    Pure-Python documentation generation pipeline.

    No GUI, no tkinter, no threads. Call run() or run_single() and get
    back structured results. All logging goes through the injected
    logger callback (message: str, level: str) -> None.
    """

    def __init__(
        self,
        config: PipelineConfig,
        saved_hashes: Optional[dict] = None,
        logger: Callable[[str, str], None] = None,
    ):
        self.config = config
        self.saved_hashes = saved_hashes or {}
        self.logger = logger or (lambda msg, level: None)

    # -- Public API -----------------------------------------------------------

    def run(self) -> PipelineResult:
        """Process all reports in the configured folder. Returns a PipelineResult."""
        reports_folder = self.config.reports_folder
        self.logger(f"scanning {reports_folder}", "info")
        if self.config.include_lineage and self.config.output_format != "md":
            self.logger("warning: the lineage diagram is only added to Markdown output", "warn")

        pbip_files = _find_pbip_files(reports_folder)
        if not pbip_files:
            self.logger("no .pbip files found", "warn")
            return PipelineResult()

        skipped_dirs, runnable = _detect_multi_pbip_folders(pbip_files)
        for d in sorted(skipped_dirs):
            names = ", ".join(
                os.path.splitext(os.path.basename(p))[0]
                for p in pbip_files
                if os.path.dirname(p) == d
            )
            self.logger(
                f"skipped: {os.path.basename(d)} contains multiple .pbip files ({names})",
                "warn",
            )
            self.logger(
                "  place each report in its own folder to generate documentation",
                "warn",
            )

        collisions: dict[str, list[str]] = {}
        if self.config.output_folder:
            by_name: dict[str, list[str]] = defaultdict(list)
            for p in runnable:
                by_name[os.path.splitext(os.path.basename(p))[0]].append(p)
            collisions = {n: ps for n, ps in by_name.items() if len(ps) > 1}
        processable = [
            p for p in runnable
            if os.path.splitext(os.path.basename(p))[0] not in collisions
        ]

        for name in sorted(collisions):
            for p in sorted(collisions[name]):
                self.logger(
                    f"error: output collision - {p} and another report named "
                    f"\"{name}\" would both write to "
                    f"{os.path.join(self.config.output_folder, name)} - rename "
                    "one report or run without --output-folder",
                    "err",
                )

        self.logger(f"found {len(processable)} report(s)", "ok")

        result = PipelineResult(total_count=len(runnable))
        for pbip_path in processable:
            single = self.run_single(pbip_path)
            result.results.append(single)
            if single.content_hash:
                result.hashes[single.hash_key] = single.content_hash
            if single.success:
                result.success_count += 1
            elif single.skipped:
                result.skipped_count += 1
            else:
                result.error_count += 1
        result.error_count += sum(len(ps) for ps in collisions.values())

        self.logger(
            f"done - {result.success_count} written" + (
                f" - {result.error_count} errors" if result.error_count else ""
            ),
            "ok" if not result.error_count else "warn",
        )
        return result

    def run_single(self, pbip_path: str) -> SingleResult:
        """Process one .pbip file. Returns a SingleResult."""
        pbip_dir    = os.path.dirname(pbip_path)
        pbip_name   = os.path.splitext(os.path.basename(pbip_path))[0]
        model_dir, problem = _locate_model(pbip_path)
        problem = problem or _model_problem(model_dir)

        if problem:
            self.logger(f"{pbip_name} - skipped: {problem}", "warn")
            return SingleResult(report_name=pbip_name, skipped=True,
                                skip_reason=problem)

        guess = os.path.join(pbip_dir, f"{pbip_name}.SemanticModel")
        model_note = ""
        if os.path.normcase(os.path.normpath(model_dir)) != os.path.normcase(os.path.normpath(guess)):
            try:
                model_note = os.path.relpath(model_dir, pbip_dir).replace(os.sep, "/")
            except ValueError:
                model_note = model_dir

        out_path = _get_output_path(
            pbip_dir, pbip_name, self.config.output_format, self.config.output_folder
        )
        hash_key = os.path.relpath(
            pbip_path, self.config.reports_folder or os.curdir
        ).replace(os.sep, "/")

        try:
            current_hash = _content_hash(model_dir, self.config, out_path)

            if self.config.skip_unchanged:
                if self.saved_hashes.get(hash_key) == current_hash \
                        and os.path.exists(out_path):
                    self.logger(f"{pbip_name} - skipped (unchanged)", "msg")
                    return SingleResult(report_name=pbip_name, skipped=True,
                                        skip_reason="unchanged",
                                        hash_key=hash_key)
            elif os.path.exists(out_path) and not self.config.overwrite:
                self.logger(f"{pbip_name} - skipped (file exists)", "msg")
                return SingleResult(report_name=pbip_name, skipped=True,
                                    skip_reason="file exists",
                                    hash_key=hash_key)

            self.logger(f"-> {pbip_name}", "msg")
            if model_note:
                self.logger(f"  model: {model_note} (definition.pbir)", "msg")
            self.logger("  parsing TMDL...", "msg")
            model = parse_semantic_model(model_dir, pbip_name)

            table_count   = len(model.tables)
            measure_count = sum(len(t.measures) for t in model.tables)
            self.logger(
                f"  tables: {table_count} - measures: {measure_count}", "msg"
            )

            resolved = resolve_sources(
                model.source_expressions, model.m_parameters, tables=model.tables
            )
            gen_config = _build_gen_config(pbip_name, self.config)

            renderer = {
                "html": generate_html,
                "txt": generate_text,
                "json": generate_json,
            }.get(self.config.output_format, generate_readme)
            content = renderer(model, resolved, gen_config)

            newline = "\n" if self.config.output_format in ("txt", "json") else None
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline=newline) as f:
                f.write(content)

            out_filename = os.path.basename(out_path)
            self.logger(f"  {out_filename} written", "ok")
            return SingleResult(
                report_name=pbip_name,
                success=True,
                output_path=out_path,
                table_count=table_count,
                measure_count=measure_count,
                content_hash=current_hash,
                hash_key=hash_key,
            )

        except Exception as e:
            self.logger(f"  error: {e}", "err")
            return SingleResult(report_name=pbip_name, error=str(e),
                                hash_key=hash_key)
