# Changelog

## [0.7.2](https://github.com/arsmagistralis/tmdl-lens/compare/v0.7.1...v0.7.2) (2026-10-21)


### Bug Fixes

* **generator:** align Markdown, HTML and text renderer output ([68e823f](https://github.com/arsmagistralis/tmdl-lens/commit/68e823f37147746a1f2908c99fa3766d0d847221))
* **generator:** drop unreachable manual source label claim ([055e47b](https://github.com/arsmagistralis/tmdl-lens/commit/055e47b58d7227b329dada26327abc402654ba9d))
* **packaging:** raise build requirement and ship tests in the sdist ([dd504be](https://github.com/arsmagistralis/tmdl-lens/commit/dd504be780cc878e11c7259a770245a48446cb93))
* renderer alignment, sdist packaging fix and repository URL update ([59d2583](https://github.com/arsmagistralis/tmdl-lens/commit/59d25837c5366a6e84fe1bc0ec8b09c7567d2ebb))

## [0.7.1](https://github.com/nox-magistralis/tmdl-lens/compare/v0.7.0...v0.7.1) (2026-10-15)


### Bug Fixes

* bug-report remediation - parser, sources, CLI output and statistics ([8eeb0ce](https://github.com/nox-magistralis/tmdl-lens/commit/8eeb0ce06737177049baf99b5398a1cf1f2721d4))
* **cli:** name reports, split streams and count skips in summary ([a8b8fcf](https://github.com/nox-magistralis/tmdl-lens/commit/a8b8fcfbf58b65ac4823c31258f8c0da44f9397c))
* **generator:** align statistics table with summary and add Columns ([6563292](https://github.com/nox-magistralis/tmdl-lens/commit/6563292be743605c8cb29dc06de07535e52eb394))
* **generator:** find hidden references in permissive DAX shapes ([ff05d57](https://github.com/nox-magistralis/tmdl-lens/commit/ff05d57012cb67bb490a0021c34eeb56775707ba))
* **parser:** table typing, M comments, key case and value unquoting ([7ed7902](https://github.com/nox-magistralis/tmdl-lens/commit/7ed79025a238f0bb9f0f45084ede488cb1aa7aa4))
* **sources:** keep the site URL for SharePoint.Contents sources ([d9ea6a2](https://github.com/nox-magistralis/tmdl-lens/commit/d9ea6a2e161a53b656b2b6349466f2ca4633a6fa))

## [0.7.0](https://github.com/nox-magistralis/tmdl-lens/compare/v0.6.1...v0.7.0) (2026-10-13)


### Features

* audit remediation, output formats and the report layer ([bafc600](https://github.com/nox-magistralis/tmdl-lens/commit/bafc600d52c9268b68a2de12c868065bf4e767e5))
* **formats:** add a JSON output format with a published schema ([305adbb](https://github.com/nox-magistralis/tmdl-lens/commit/305adbbced7e83c212b9a6dc202fb3469a5eac8d))
* **formats:** add a plain-text output format ([0b8ad4e](https://github.com/nox-magistralis/tmdl-lens/commit/0b8ad4e6d0dbdbd2e12ada548a3664586043adcf))
* **generator:** add a table of contents built from the section list ([8203462](https://github.com/nox-magistralis/tmdl-lens/commit/82034628aa11f3e8e82da7fa3005691ad3e9204f))
* **generator:** draw an opt-in Mermaid lineage diagram ([c2d5e56](https://github.com/nox-magistralis/tmdl-lens/commit/c2d5e568c374b328cececcf4fc89689d78e32711))
* **report:** parse the report layer into pages, visuals and usages ([262557b](https://github.com/nox-magistralis/tmdl-lens/commit/262557b2396c84a2298d1a8529585ba66e2b6685))


### Bug Fixes

* **cli:** fail loudly on unreadable config and make skip hash-first ([3dc809b](https://github.com/nox-magistralis/tmdl-lens/commit/3dc809b0173bc632b9fb6b906ffdf5e4c51e2160))
* **config:** keep a broken config intact and validate every value ([5e3cca4](https://github.com/nox-magistralis/tmdl-lens/commit/5e3cca45d22a2a2d2e0fd3bd3070d9397650e125))
* **parser:** resolve M sources through a documented precedence order ([0d4abcf](https://github.com/nox-magistralis/tmdl-lens/commit/0d4abcf4cfaee77045dff40629d7b481d8087ddc))
* **pipeline:** find the model folder from the project pointers ([27aba3d](https://github.com/nox-magistralis/tmdl-lens/commit/27aba3dc12728ef3d4430f2e67d3c4b5dac724bc))

## [0.6.1](https://github.com/nox-magistralis/tmdl-lens/compare/v0.6.0...v0.6.1) (2026-10-09)


### Bug Fixes

* **generator:** compute table and measure lists once for both renderers ([1096310](https://github.com/nox-magistralis/tmdl-lens/commit/1096310c0eddee871d41b9f19977cc3ef9cb6cd8))
* **generator:** rendering parity between Markdown and HTML ([c5aa471](https://github.com/nox-magistralis/tmdl-lens/commit/c5aa471aa2d977cc70d6fb806d01831b6c104beb))

## [0.6.0](https://github.com/nox-magistralis/tmdl-lens/compare/v0.5.4...v0.6.0) (2026-10-09)


### Features

* **functions:** document DAX functions and fix rendering output ([ad7f6fe](https://github.com/nox-magistralis/tmdl-lens/commit/ad7f6fed28a6088dabe1a97d285511195a2d1040))
* **functions:** document DAX user-defined functions ([13f2af4](https://github.com/nox-magistralis/tmdl-lens/commit/13f2af4c6e66ba61a14d7a5a6cdfd823af7c1c7e))


### Bug Fixes

* **generator:** cover calculated and field-parameter tables in details ([317758d](https://github.com/nox-magistralis/tmdl-lens/commit/317758d6e131291e4ff48dac28914d2cc1532a20))
* **generator:** escape HTML output exactly once ([0da37a6](https://github.com/nox-magistralis/tmdl-lens/commit/0da37a667b93c3f44ee6d531d5defc8569369986))
* **generator:** escape Markdown table cells ([d2a82b6](https://github.com/nox-magistralis/tmdl-lens/commit/d2a82b61a7ae4734ef60e9cee14dd916128d6c30))
* **generator:** filter auto-date tables from the whole output ([ef995c1](https://github.com/nox-magistralis/tmdl-lens/commit/ef995c1cadc93be3e3889e4dc2acab01c03deb7a))
* **generator:** list hidden loaded tables in Data Sources ([005258c](https://github.com/nox-magistralis/tmdl-lens/commit/005258c14c305535e7533a9edac04365e1500a6b))
* **parser:** detect the source connector across all M calls ([e8f14f0](https://github.com/nox-magistralis/tmdl-lens/commit/e8f14f0ae81b129f57bbc535ca57897f52b49308))
* **parser:** parse roles folder layout and multi-line RLS filters ([90ae7b5](https://github.com/nox-magistralis/tmdl-lens/commit/90ae7b5a1a941c856e1662849c8b41c66342fb79))

## [0.5.4](https://github.com/nox-magistralis/tmdl-lens/compare/v0.5.3...v0.5.4) (2026-10-06)


### Bug Fixes

* **parser:** classify M functions by annotation and body start ([d1615ff](https://github.com/nox-magistralis/tmdl-lens/commit/d1615ffda98e1bd430db7d7f7da05671d8c62051))
* **parser:** default omitted relationship cardinality to many-to-one ([e1c0030](https://github.com/nox-magistralis/tmdl-lens/commit/e1c0030feca18e52ecdd0e257a6cc13b4879be07))
* **parser:** handle quoted names, escapes and expressionless measures ([699643b](https://github.com/nox-magistralis/tmdl-lens/commit/699643b033cbd9e37399ae1e849b8d51d02e7090))
* **parser:** relationship defaults, function and name parsing ([0b7ad0b](https://github.com/nox-magistralis/tmdl-lens/commit/0b7ad0b631a079815db8261bee14d567e5257f21))

## [0.5.3](https://github.com/nox-magistralis/tmdl-lens/compare/v0.5.2...v0.5.3) (2026-10-06)


### Bug Fixes

* **packaging:** make the release zip step resilient to file locks ([d8a5a14](https://github.com/nox-magistralis/tmdl-lens/commit/d8a5a14dff30449373bd68326484d8ffeab07420))
* **packaging:** track the PyInstaller spec so the release build can find it ([d22a34f](https://github.com/nox-magistralis/tmdl-lens/commit/d22a34f6bd3dc070a01a23589376f002d21bf478))
* **release:** repair the exe build and publish from the tag ([0491aeb](https://github.com/nox-magistralis/tmdl-lens/commit/0491aeb5c7826f6f43448fa6db5d6cab07811c91))

## [0.5.2](https://github.com/nox-magistralis/tmdl-lens/compare/v0.5.1...v0.5.2) (2026-10-06)


### Bug Fixes

* **generator:** remove the generation date from generated docs ([ec99db5](https://github.com/nox-magistralis/tmdl-lens/commit/ec99db5bad9356551b1fb42dec609a171db98621))


### Documentation

* **readme:** list docs/ in the project structure ([0f21acd](https://github.com/nox-magistralis/tmdl-lens/commit/0f21acdd722700c7bb6dc1abe613fdfd041f05f8))
