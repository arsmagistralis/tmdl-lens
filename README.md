# tmdl-lens

Automated documentation generator for Power BI projects.

Reads TMDL files from a folder of `.pbip` reports and generates structured HTML, Markdown, plain-text or JSON documentation for each one - covering data sources, tables, measures, relationships, M parameters, security roles, and calculation groups.

Runs as a standalone Windows desktop app or as a headless command-line tool. Output can be HTML (opens in any browser), Markdown (README.md for GitHub) plain text (`<report>.txt` for terminals, tickets and AI agents) or typed JSON (`<report>.json` for tools and CI). A live file watcher regenerates documentation automatically on every save.

---

## What it documents

See a [real example output](sample/README.md) generated from the included sample report.

Each generated README includes:

- **Contents** - a linked table of contents of the sections below (Markdown and HTML)
- **Lineage** (optional, Markdown) - a Mermaid source-to-table flowchart, see [Lineage diagram](#lineage-diagram)
- **Data Sources** - connector type and resolved source detail for every query. 30+ Power Query connector functions have dedicated labels (SQL, Dataflows, SharePoint, Excel, OData, Azure Blob/Table/Data Lake storage, Databricks, Snowflake, Salesforce, Oracle, PostgreSQL, SAP HANA, and more); any connector without a dedicated label is still auto-detected from the query and shown with its namespace and function.
- **Table Details** - table type, source detail, and column list
- **Measures** - full DAX (optional), display folder, and format string
- **Functions** - DAX user-defined functions with description, where they are used, and full DAX (optional)
- **Relationships** - cardinality, cross-filter direction, and active/inactive state
- **M Parameters** - current value and which source expressions reference each parameter
- **Security Roles** - static and dynamic RLS rules per table, flagged by type
- **Calculation Groups** - calculation items with DAX and ordinal order
- **Model Statistics** - table, column, measure, and relationship counts

---

## Installation

### Option A - Command line (PyPI)

Requires Python 3.12+.

```
pip install tmdl-lens
tmdl-lens --reports-folder C:\path\to\reports --format md
```

The base package installs the dependency-free `tmdl-lens` command and nothing else. For the desktop GUI, install the GUI extras and launch it as a module:

```
pip install "tmdl-lens[gui]"
python -m tmdl_lens.app
```

### Option B - Standalone executable

Download `tmdl-lens.v<version>.zip` from the [Releases](https://github.com/arsmagistralis/tmdl-lens/releases) page, extract it, and run `tmdl-lens.exe` from the extracted folder. No Python or pip required. Keep the extracted files together - the executable loads its dependencies from the `_internal` folder next to it.

A `config.json` file will be created alongside the executable on first run to store your settings.

> **Note:** Windows may show a SmartScreen warning on first run. Click **More info** then **Run anyway**. This is expected for unsigned applications.

### Option C - Run from source

Requires Python 3.12+.

```
git clone https://github.com/arsmagistralis/tmdl-lens.git
cd tmdl-lens
pip install -r requirements.txt
python main.py
```

---

## Usage

1. Launch the app
2. Under **Configure**, set the **Reports folder** to the root of your `.pbip` projects
3. Set an **Output folder** if you want READMEs written somewhere other than next to each `.pbip`
4. Press **Run Now** to generate documentation for all reports
5. Enable **Watch for TMDL changes** to auto-regenerate on every save

Each report's semantic model folder is found in this order: the report listed in the `.pbip` file's `artifacts`, then that report's `definition.pbir` (`datasetReference` `byPath`), then a `<pbip name>.SemanticModel` folder next to the `.pbip` as a fallback when the first two are absent. A report whose `definition.pbir` uses `byConnection` is skipped, because it has no local model, and so is a `byPath` reference to a missing folder. A model folder without a `definition/` TMDL folder (for example a `model.bim` project) is skipped with a message, and an existing output file is left untouched.

If no output folder is set, each `README.md` is written next to its `.pbip` file. If a separate output folder is set, each report gets its own named subfolder inside it - for example `docs/SalesReport/README.md`, `docs/FinanceReport/README.md` - so multiple reports never collide.

Optional documentation metadata (owner, team, refresh schedule) is set in the **Configure** tab and stored in `config.json`: next to the executable for the standalone app, in the repository root when run from source, and in `%APPDATA%\tmdl-lens` on Windows or `~/.config/tmdl-lens` elsewhere for a pip install. A pip install that finds no file there copies an older `config.json` from its package folder once and leaves the old file in place. Values left blank are omitted from the generated output.

By default the app skips reports whose TMDL files and documentation settings have not changed since the last run - each report is hashed, and only reports that actually moved are regenerated. Turn this off with **Skip reports with no TMDL changes** in **Configure**.

On startup the app validates the config and logs a warning for an empty reports folder, a watch debounce outside 1-300, or an output format other than `html`, `md`, `txt` or `json`; path existence is checked when a run starts. A `config.json` that cannot be read is logged as an error and is not overwritten until you press **Save**; a value of the wrong type is logged with the default used instead.

### Command line

The `tmdl-lens` command runs the same documentation pipeline without the GUI:

```
tmdl-lens --reports-folder C:\path\to\reports
tmdl-lens -r C:\path\to\reports -o docs --format html --overwrite
```

Run `tmdl-lens --help` for the full list of options. Exit codes: `0` when everything succeeds, `1` when a report fails or the reports folder does not exist, and `2` when `--reports-folder` is missing or the file passed to `--config` exists but cannot be parsed (a UTF-8 byte order mark is accepted). Settings can be read from a `config.json` with `--config` (CLI flags override file values) - this is also what makes `--skip-unchanged` persist its content hashes between runs. A `--config` path that does not exist is warned about and not created; relative paths inside the config resolve against the config file's folder. A value of the wrong type is warned about and replaced by its default for that run, and the file keeps your value. With `--skip-unchanged`, a report whose content changed is regenerated even when `--overwrite` is off.

### Output formats

| `--format` | File per report | Content |
|---|---|---|
| `html` (default) | `<report>.html` | styled page for a browser |
| `md` | `README.md` | Markdown for GitHub and other repository viewers |
| `txt` | `<report>.txt` | plain text: the same sections as the Markdown, with aligned columns, no markup, ASCII headings and LF line endings on every platform |
| `json` | `<report>.json` | typed data for tools and CI, described by [`docs/tmdl-lens-output.schema.json`](docs/tmdl-lens-output.schema.json) |

The JSON output is versioned by `schema_version` (currently `1.0`) and is deterministic across machines: no timestamp or tool version, every list of named items sorted by name, LF line endings. Values are fixed codes rather than display text (`kind`, `source.type`, `cardinality`, `cross_filter`, `security_filter`, warning `code`), a source that could not be resolved is `{"resolved": false, "reason": ...}`, and `source` is `null` for a table without an M source. Every shared expression is listed under `expressions`, including those no table uses. With `--no-include-dax`, every `expression` is `null`; hidden-reference warnings are still reported.

### Lineage diagram

`--include-lineage` (config key `include_lineage`, GUI option **Include lineage diagram**) adds a `### Lineage` sub-section at the end of "1. Data Sources" in the Markdown output: a Mermaid flowchart from each external source, through the shared queries, to every loaded and not-loaded table. GitHub, Azure DevOps and the VS Code preview render it without any script, so the output stays offline. Helper functions, scalar helpers and parameters are left out. It is off by default, and with it off the output is unchanged. The diagram is Markdown-only: with `--format html`, `txt` or `json` the option has no effect and a warning is logged once per run (the JSON output already carries each source's `chain` and `combine_sources`). Node ids are derived from a SHA-256 of each node's identity, so the diagram is byte-identical across runs and machines, and adding a table does not rename the other nodes.

---

## Requirements

The command-line core has no third-party dependencies (pure Python standard library). The desktop GUI adds two packages:

| Package | Version | Used for |
|---|---|---|
| customtkinter | >= 5.2.0 | GUI |
| watchdog | >= 4.0.0 | file watcher |

Python 3.12 or later required when running from source.

---

## Compatibility & Public API

The items below are the public contract of `tmdl-lens`. They are frozen from
version 1.0.0 - changing, renaming or removing any of them is a breaking
change and requires a new major version, announced in the GitHub release notes.

**CLI flags** (`tmdl-lens` command):

`--version`, `-r` / `--reports-folder`, `-o` / `--output-folder`,
`--format` (`html`, `md`, `txt` or `json`), `--include-dax` / `--no-include-dax`,
`--include-lineage` / `--no-include-lineage`, `--overwrite` / `--no-overwrite`, `--skip-unchanged` / `--no-skip-unchanged`,
`--owner`, `--team`, `--refresh-schedule`, `--config`, `-q` / `--quiet`.

**Exit codes:** `0` success; `1` a report failed or the reports folder does
not exist; `2` `--reports-folder` is missing or the `--config` file exists
but cannot be parsed.

**`config.json` keys:** `reports_folder`, `output_folder`, `output_format`,
`overwrite_readme`, `include_dax`, `include_lineage`, `skip_unchanged`, `watch_debounce`,
`owner`, `team`, `refresh_schedule`, `file_hashes`, `features.watcher`.

Not part of the contract: importing `tmdl_lens.*` as a Python library (the
package is distributed for its CLI - the module layout may change) and the
exact wording or layout of the generated HTML/Markdown (best effort).

## Limitations

- Import-mode PBIP reports only. Live Connection, Direct Lake and other
  models without a `definition/` TMDL folder are not documented; such a
  report is skipped with a message naming the reason.
- Connectors are detected from the query text. Known connectors get a
  dedicated label; anything else is shown with its Power Query namespace and
  function.
- The parser targets the TMDL shapes seen in real PBIP projects, but the
  format keeps evolving - an unhandled object type is reported rather than
  crashing.

## Development

```
pip install -r requirements-dev.txt
python -m pytest
```

`requirements-dev.txt` adds dev-only dependencies (pytest, pyinstaller) on top of the base `requirements.txt`. The test suite runs against the bundled sample report and covers the TMDL parser, source resolution, config validation, and README/HTML generation.

---

## Project structure

```
tmdl-lens/
  main.py                   entry point (desktop GUI)
  pyproject.toml            package metadata and CLI entry point (PyPI)
  requirements.txt          GUI dependencies (source installs)
  requirements-dev.txt      dev-only dependencies (pytest, build, twine, pyinstaller)
  pytest.ini
  tmdl_lens/
    app.py                  CustomTkinter UI
    cli.py                  command-line interface
    pipeline.py             documentation generation pipeline
    tmdl_parser.py          TMDL file parser
    source_resolver.py      M expression source resolver
    readme_generator.py     README markdown generator
    watcher.py              file watcher (watchdog)
    config.py               app settings + documentation metadata (config.json)
    version.py              single source of the app version
  docs/                     TMDL syntax and parser internals reference
  sample/                   sample .pbip project for testing
  tests/                    pytest suite
```

---

## Author

**Marcin Mozol** - [github.com/arsmagistralis](https://github.com/arsmagistralis)

---

## License

MIT - see [LICENSE](LICENSE)
