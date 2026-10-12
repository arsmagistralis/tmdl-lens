"""
config.py - Config read/write for tmdl-lens.

Single place that reads, validates and writes config.json for both the
GUI and the CLI. All keys are optional - defaults are applied for
anything missing, and values of the wrong type are replaced by their
default with a warning.
"""

import copy
import json
import os
import sys
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS = {
    "reports_folder":   "",
    "output_folder":    "",
    "overwrite_readme": False,
    "include_dax":      True,
    "output_format":    "html",
    "skip_unchanged":   True,
    "watch_debounce":   10,
    "owner":            "",
    "team":             "",
    "refresh_schedule": "",
    "file_hashes":      {},
    "features": {
        "watcher": True,
    },
}

_STRING_KEYS = frozenset({
    "reports_folder", "output_folder", "output_format",
    "owner", "team", "refresh_schedule",
})
_BOOL_KEYS = frozenset({"overwrite_readme", "include_dax", "skip_unchanged"})


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

def _package_parent() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_source_checkout() -> bool:
    return os.path.exists(os.path.join(_package_parent(), "pyproject.toml"))


def _is_pip_install() -> bool:
    return not getattr(sys, "frozen", False) and not _is_source_checkout()


def _user_config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "tmdl-lens")


def _legacy_config_path() -> str:
    return os.path.join(_package_parent(), "config.json")


def _config_path() -> str:
    """
    Returns the path to config.json.
    - PyInstaller .exe: same folder as the .exe
    - source checkout: the repository root (folder holding pyproject.toml)
    - pip install: a per-user folder (%APPDATA%\\tmdl-lens on Windows,
      $XDG_CONFIG_HOME/tmdl-lens or ~/.config/tmdl-lens elsewhere)
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    elif _is_source_checkout():
        base = _package_parent()
    else:
        base = _user_config_dir()
    return os.path.join(base, "config.json")


@dataclass
class LoadResult:
    config: dict
    path: str
    error: str = ""
    warnings: list = field(default_factory=list)
    migrated_from: str = ""

    @property
    def failed(self) -> bool:
        return self.error not in ("", "missing")


def read_file(path: str) -> tuple[dict, str]:
    """
    Read a config file. Returns (data, error) where error is "" on
    success, "missing" when the file does not exist, or a reason string
    when the file exists but cannot be used. A UTF-8 byte order mark is
    accepted. Never raises for an unreadable file.
    """
    if not os.path.exists(path):
        return {}, "missing"
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except UnicodeDecodeError as e:
        return {}, f"file is not valid UTF-8: {e}"
    except json.JSONDecodeError as e:
        return {}, f"file is not valid JSON: {e}"
    except OSError as e:
        return {}, f"file cannot be read: {e}"
    if not isinstance(data, dict):
        return {}, f"expected a JSON object, got {type(data).__name__}"
    return data, ""


def _render(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _value_ok(key: str, value) -> bool:
    if key in _STRING_KEYS:
        return isinstance(value, str)
    if key in _BOOL_KEYS:
        return isinstance(value, bool)
    if key == "watch_debounce":
        return isinstance(value, int) and not isinstance(value, bool)
    if key == "file_hashes":
        return isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        )
    return True


def check_types(data: dict, fallbacks: dict = None) -> tuple[dict, list]:
    """
    Return (valid, warnings): the known keys of data whose values have the
    expected type, and one warning per rejected value naming the key, the
    value found and the value used instead (from fallbacks when the caller
    passes them, otherwise from DEFAULTS). Keys absent from data stay
    absent from valid. A null file_hashes is dropped without a warning.
    """
    valid: dict = {}
    warnings: list[str] = []
    used_values = {**DEFAULTS, **(fallbacks or {})}

    def reject(key, value, used):
        warnings.append(
            f"config key '{key}' has invalid value {_render(value)}, using {_render(used)}"
        )

    for key, value in data.items():
        if key not in DEFAULTS:
            continue
        if key == "file_hashes" and value is None:
            continue
        if key == "features":
            if not isinstance(value, dict):
                reject(key, value, DEFAULTS["features"])
                continue
            features = copy.deepcopy(DEFAULTS["features"])
            for sub_key, sub_value in value.items():
                if sub_key in DEFAULTS["features"] and not isinstance(sub_value, bool):
                    reject(f"features.{sub_key}", sub_value, DEFAULTS["features"][sub_key])
                    continue
                features[sub_key] = copy.deepcopy(sub_value)
            valid["features"] = features
            continue
        if _value_ok(key, value):
            valid[key] = copy.deepcopy(value)
        else:
            reject(key, value, used_values[key])
    return valid, warnings


def normalize(data: dict) -> tuple[dict, list]:
    """Defaults merged with the valid values of data, plus the warnings."""
    config = copy.deepcopy(DEFAULTS)
    valid, warnings = check_types(data)
    config.update(valid)
    return config, warnings


def _migrate_legacy(path: str) -> tuple[dict, str]:
    try:
        legacy = _legacy_config_path()
        data, error = read_file(legacy)
        if error:
            return {}, ""
        if write_atomic(path, data):
            return data, legacy
        return data, ""
    except Exception:
        return {}, ""


def load_result() -> LoadResult:
    """
    Load config.json and report how it went. On a missing or unusable
    file the config is the defaults; the error tells the caller not to
    overwrite an unusable file implicitly. A pip install with no file in
    its per-user folder copies a legacy config.json from the package
    parent folder once; the legacy file is never deleted.
    """
    path = _config_path()
    data, error = read_file(path)
    migrated_from = ""
    if error == "missing" and _is_pip_install():
        legacy_data, migrated_from = _migrate_legacy(path)
        if legacy_data:
            data, error = legacy_data, ""
    if error:
        return LoadResult(config=copy.deepcopy(DEFAULTS), path=path, error=error)
    config, warnings = normalize(data)
    return LoadResult(
        config=config, path=path, warnings=warnings, migrated_from=migrated_from
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load() -> dict:
    """Load config from disk, merging with defaults for any missing keys."""
    return load_result().config


def write_atomic(path: str, data: dict) -> bool:
    """
    Write data as JSON to path through a temporary file in the same
    folder, replaced in one step. Creates the folder when missing.
    Returns True on success, False on failure; never leaves the
    temporary file behind.
    """
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
        return True
    except (OSError, TypeError, ValueError):
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def save(config: dict) -> bool:
    """
    Save config to disk.
    Returns True on success, False on failure.
    """
    return write_atomic(_config_path(), config)


def reset() -> bool:
    """
    Overwrite config.json on disk with the DEFAULTS values.
    Returns True on success, False on failure.
    """
    return write_atomic(_config_path(), copy.deepcopy(DEFAULTS))


def validate_config(config: dict) -> list:
    """
    Validate a loaded config dict and return a list of warning strings.

    Returns an empty list when the config looks fine. Callers (e.g. the
    GUI) can surface each warning in the log.
    """
    warnings = []

    reports_folder = str(config.get("reports_folder", "")).strip()
    if not reports_folder:
        warnings.append("reports_folder is not set - choose a reports folder to run")
    elif not os.path.isdir(reports_folder):
        warnings.append(f"reports_folder does not exist: {reports_folder}")

    output_folder = str(config.get("output_folder", "")).strip()
    if output_folder and not os.path.isdir(output_folder):
        warnings.append(f"output_folder does not exist: {output_folder}")

    watch_debounce = config.get("watch_debounce")
    if watch_debounce is not None:
        try:
            if not 1 <= int(watch_debounce) <= 300:
                warnings.append(
                    f"watch_debounce must be between 1 and 300 (got {watch_debounce})"
                )
        except (TypeError, ValueError):
            warnings.append(
                f"watch_debounce must be an integer (got {watch_debounce!r})"
            )

    output_format = str(config.get("output_format", "")).strip()
    if output_format and output_format not in ("html", "md"):
        warnings.append(
            f"output_format must be 'html' or 'md' (got {output_format!r})"
        )

    return warnings


def config_path() -> str:
    """Returns the resolved config.json path (for display in UI)."""
    return _config_path()
