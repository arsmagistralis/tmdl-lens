# Parser and pipeline internals

**TMDL parser (`tmdl_parser.py`)**
- Core structure parsing goes through `_parse_tree()`, which builds a tree of `TmdlNode` from indentation. Nested TMDL structure is parsed only this way; regex is used solely to locate block boundaries.
- `_extract_blocks()` is a block-boundary locator only (finds where a `column`/`measure`/`calculationItem` block starts and ends by indentation). It does not parse the block's internal structure.
- `_classify_m_content()` classifies M (comments stripped) with a fixed precedence; the first rule that fires wins, and every result records `classification_reason`:

  | # | Rule | `source_type` |
  |---|---|---|
  | 1 | `PBI_ResultType` is `Text`, `Number`, `Date`, `DateTime` or `Boolean` | `scalar_helper` |
  | 2 | `#table(` or `Table.FromRows(` present | `hardcoded` / `embedded` |
  | 3 | any `Namespace.Function(` call in the whole block outside the M standard library (`_STDLIB_NAMESPACES`) and `_TRANSFORM_FNS`; the first such call in source order is the connector | `connector` |
  | 4 | `Table.Combine({...})` / `Table.Append({...})` whose items resolve to queries: `#"name"`, a bare name, or a step of the same block assigned `#"name"`; other local steps are dropped | `table_combine` |
  | 5 | the first step references a query: `Source = #"x"`, `Source = X`, or a first `let` binding `a = #"x"` / `a = X` | `derived` (quoted) / `derived_table` (bare) |
  | 6 | no query reference, and the block builds a table from scratch | `generated` |
  | 7 | none of the above | `unknown` |

  `builds_table` is set on every result when the block calls a scratch builder (`List.Generate`, `List.Dates`, `List.DateTimes`, `List.Numbers`, `Table.FromList`, `Table.FromRecords`, `Table.FromColumns`). Real queries use these as transformations too, so a query reference in rule 5 always wins over them.

  Function versus table is decided before this, in `_classify_expression()`: `PBI_ResultType = Function` or a body that starts with a function signature (optionally typed, `(x as text) as table =>`) is `function_def`.
- Adding a new connector with custom detail extraction: add a branch to `_extract_connector_details()` in `tmdl_parser.py`, add an entry to `CONNECTOR_TYPE_LABEL` in `source_resolver.py`. That dict is the only source of connector labels - `readme_generator.py` imports it, so there is no second copy to keep in sync. Generic connectors with no custom branch still get classified and labeled - the custom branch is only needed to extract extra detail fields (server, database, url, etc.).
- `_SOURCE_TYPE_LABEL` in `readme_generator.py` is a separate axis: it names non-connector source types (`hardcoded`, `embedded`, `table_combine`, `dynamic`, `unresolved`, `function_def`, `scalar_helper`, `generated`). Extend it only when a new `source_type` value is introduced.
- M comment stripping (`_strip_m_comments`) must run before any connector detection.

**Source resolver (`source_resolver.py`)**
- Three-tier resolution: terminal connectors (tier 1) → derived/custom_function chains (tier 2) → inline table sources (tier 3).
- Terminal types listed in `_TERMINAL_TYPES` (including `table_combine` and `generated`) - chain walking stops there.
- A `derived` expression or table whose parent is an M parameter or a `scalar_helper` is not copied from that parent: it resolves as `generated` when its `builds_table` is true (a calendar seeded from a start date), otherwise as unresolved with the reason `first step references parameter '<name>'` or `first step references scalar helper '<name>'`. An `unknown` expression reports its `classification_reason` as the unresolved reason.
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
- Reads settings from a `config.json` only when `--config` is passed; that is also the only way `--skip-unchanged` hashes persist between runs (CLI flags override file values). A missing config file logs a warning and is never created; a file that exists but does not parse (invalid JSON, non-object JSON, non-UTF-8) is an error with exit code 2 and is never written; a UTF-8 byte order mark is accepted. Values used for the run go through `config.check_types()`; a wrong-typed value is warned about and falls back to the CLI default, while write-back keeps the raw file content. Relative `reports_folder`/`output_folder` values from the file resolve against the config file's folder. Write-back merges `file_hashes` into the loaded settings and replaces the file atomically. The standard config.json location belongs to the GUI, so the CLI never writes there implicitly.

**Config file - one file**
- `config.json` - program settings (output format, paths, watcher) plus optional documentation metadata (owner, team, refresh schedule) and `skip_unchanged` content hashes (`file_hashes`). `config_path()` resolves three cases: next to the executable when frozen, the repo root when the package's parent folder holds `pyproject.toml` (source checkout), otherwise a per-user folder (`%APPDATA%\tmdl-lens` on Windows, `$XDG_CONFIG_HOME/tmdl-lens` or `~/.config/tmdl-lens` elsewhere). On a pip install with no file there, `load_result()` copies a legacy `config.json` from the package's parent folder once, never raising and never deleting it.
- `config.py` is the only reader and writer for both CLI and GUI: `read_file()` (UTF-8 with an optional byte order mark, JSON object required, returns an error string instead of raising), `check_types()` / `normalize()` (each known key checked against the type of its default; a rejected value is replaced by the default with a warning naming the key, the value found and the value used), `load_result()` returning a `LoadResult` (config, path, error, warnings, migrated_from) and `write_atomic()` (temporary file plus `os.replace`). Defaults are always copied with `copy.deepcopy`.
- The GUI never writes `config.json` implicitly (close, hash persistence, first-launch save) after a failed load; an explicit Save overwrites it and clears the error. Every failed save is logged.
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
