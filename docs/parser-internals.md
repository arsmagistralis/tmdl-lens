# Parser and pipeline internals

**TMDL parser (`tmdl_parser.py`)**
- Core structure parsing goes through `_parse_tree()`, which builds a tree of `TmdlNode` from indentation. Nested TMDL structure is parsed only this way; regex is used solely to locate block boundaries.
- `_extract_blocks()` is a block-boundary locator only (finds where a `column`/`measure`/`calculationItem` block starts and ends by indentation). It does not parse the block's internal structure.
- `_classify_m_content()` classifies a partition in a fixed order: scalar helper, then the specific shapes (transform functions, hardcoded and embedded data, derived references), and the generic connector match last. Any `Namespace.Function(` call outside the M standard library and the known transform functions is treated as a connector.
- M derivation in `_classify_m_content()` also recognizes a first `let` binding
  that assigns a named query to any variable (`wb = #"shared-mapping-source"`),
  quoted references classifying as `derived` and bare as `derived_table`.
- Adding a new connector with custom detail extraction: add a branch to `_extract_connector_details()` in `tmdl_parser.py`, add an entry to `CONNECTOR_TYPE_LABEL` in `source_resolver.py`. That dict is the only source of connector labels - `readme_generator.py` imports it, so there is no second copy to keep in sync. Generic connectors with no custom branch still get classified and labeled - the custom branch is only needed to extract extra detail fields (server, database, url, etc.).
- `_SOURCE_TYPE_LABEL` in `readme_generator.py` is a separate axis: it names non-connector source types (`hardcoded`, `embedded`, `table_combine`, `dynamic`, `unresolved`, `function_def`, `scalar_helper`). Extend it only when a new `source_type` value is introduced.
- M comment stripping (`_strip_m_comments`) must run before any connector detection.

**Source resolver (`source_resolver.py`)**
- Three-tier resolution: terminal connectors (tier 1) → derived/custom_function chains (tier 2) → inline table sources (tier 3).
- Terminal types listed in `_TERMINAL_TYPES` - chain walking stops there.
- `resolve_sources()` does multiple passes to handle chains where derived expressions reference other derived expressions.
- Shared expressions or inline M that reference a loaded table resolve from the
  model's own tables: tables whose partition is a `source_ref` pointer act as
  aliases to that expression, and derived expressions that reference tables are
  resolved in the same multi-pass loop as inline table sources.

**Pipeline (`pipeline.py`)**
- Pure-Python orchestration with no GUI/thread dependencies: finds `.pbip` files, runs parse → resolve → generate per report, returns `SingleResult`/`PipelineResult`.
- `skip_unchanged` computes a SHA256 of each report's `.tmdl` files plus the generator-relevant config (`include_dax`, `output_format`, `owner`, `team`, `refresh_schedule`), the report's output path and the tool version; the hash is computed on every run inside the per-report error handling. `run_single` skips with reason `unchanged` when the hash stored for the report's path relative to `reports_folder` (forward slashes) matches and the output file already exists; a missing or differing hash regenerates even when `overwrite` is off. Hashes are stored only after a successful write, keyed by that relative path. The app persists the hashes to `config.json` under `file_hashes`.

**CLI (`cli.py`)**
- argparse-based headless interface over `Pipeline`, no GUI imports. Installed as the `tmdl-lens` console command via `pyproject.toml` `[project.scripts]`.
- Exit codes: 0 success, 1 report failure or missing reports folder, 2 missing `--reports-folder`.
- Reads settings from a `config.json` only when `--config` is passed; that is also the only way `--skip-unchanged` hashes persist between runs (CLI flags override file values). A missing config file logs a warning and is never created; a file that exists but does not parse (BOM, invalid JSON, non-object JSON, non-UTF-8) is an error with exit code 2 and is never written. Relative `reports_folder`/`output_folder` values from the file resolve against the config file's folder. Write-back merges `file_hashes` into the loaded settings and replaces the file atomically. The standard config.json location belongs to the GUI, so the CLI never writes there implicitly.

**Config file - one file**
- `config.json` - program settings (output format, paths, watcher) plus optional documentation metadata (owner, team, refresh schedule) and `skip_unchanged` content hashes (`file_hashes`). Lives next to executable or repo root.
- `config.validate_config()` returns warning strings for missing/broken paths, `watch_debounce` outside 1-300, and invalid `output_format` (accepts `html` or `md`); `app.py` logs them at startup.

**GUI (`app.py`)**
- CustomTkinter, dark theme only. Colors defined in `COLORS` dict at top of file.
- Single scrollable Configure pane (paths, options, watcher, optional documentation metadata) beside the log panel, action bar, and status bar. The left sidebar's nav buttons are non-functional; there is no top tab bar.
- All pipeline work runs in a background thread (`_run_pipeline_async` → `_on_pipeline_done`). The watcher delegates to `Pipeline.run_single()`. Pipeline work never runs on the main thread.
- Log panel uses native `tk.Text` with color tags - use `self.log(message, level)` for all output. Levels: `ok`, `warn`, `err`, `info`, `msg`.
- Watcher (watchdog) is optional. Guard all watcher code with `WATCHER_AVAILABLE` check.

**Tests**
- Tests are pytest and run from the repo root with `python -m pytest` (dev deps first: `pip install -r requirements-dev.txt`).
- Tests run against the sample report in `sample/`, which is also the published example output. Extend it deliberately when a new case is needed, and keep the existing cases intact.
- Run the suite after changing `tmdl_parser.py`, `source_resolver.py`, `readme_generator.py`, `config.py`, or the tests.
