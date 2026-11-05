"""Fragment-level tests for the TMDL file watcher."""

import os
import threading
import types

from tmdl_lens import watcher


def _handler(debounce=0, callback=None):
    return watcher._TmdlEventHandler(debounce, callback or (lambda _pbip: None))


def _event(src_path, is_directory=False, dest_path=None):
    return types.SimpleNamespace(
        is_directory=is_directory,
        src_path=src_path,
        dest_path=dest_path,
    )


def _wait_for(event, timeout=1.0):
    assert event.wait(timeout), "callback was not fired"


def _make_report(tmp_path, name):
    model = tmp_path / f"{name}.SemanticModel"
    model.mkdir()
    (model / "a.tmdl").write_text("a", encoding="utf-8")
    pbip = tmp_path / f"{name}.pbip"
    pbip.write_text("", encoding="utf-8")
    return str(pbip), str(model / "a.tmdl")


def test_watchdog_is_available():
    assert watcher.WATCHER_AVAILABLE


def test_modified_tmdl_fires_with_pbip(tmp_path):
    pbip, tmdl = _make_report(tmp_path, "Sales")
    fired = threading.Event()
    result = []

    def callback(path):
        result.append(path)
        fired.set()

    handler = _handler(callback=callback)
    handler.on_modified(_event(tmdl))

    _wait_for(fired)
    assert result == [pbip]
    handler.cancel_all()


def test_created_tmdl_fires_with_pbip(tmp_path):
    pbip, tmdl = _make_report(tmp_path, "Sales")
    fired = threading.Event()
    result = []

    def callback(path):
        result.append(path)
        fired.set()

    handler = _handler(callback=callback)
    handler.on_created(_event(tmdl))

    _wait_for(fired)
    assert result == [pbip]
    handler.cancel_all()


def test_deleted_tmdl_fires_with_pbip(tmp_path):
    pbip, tmdl = _make_report(tmp_path, "Sales")
    fired = threading.Event()
    result = []

    def callback(path):
        result.append(path)
        fired.set()

    handler = _handler(callback=callback)
    handler.on_deleted(_event(tmdl))

    _wait_for(fired)
    assert result == [pbip]
    handler.cancel_all()


def test_moved_to_tmdl_fires_from_dest_path(tmp_path):
    pbip, tmdl = _make_report(tmp_path, "Sales")
    old_path = str(tmp_path / "old.tmdl")
    fired = threading.Event()
    result = []

    def callback(path):
        result.append(path)
        fired.set()

    handler = _handler(callback=callback)
    handler.on_moved(_event(old_path, dest_path=tmdl))

    _wait_for(fired)
    assert result == [pbip]
    handler.cancel_all()


def test_moved_to_non_tmdl_does_not_fire(tmp_path):
    _pbip, _tmdl = _make_report(tmp_path, "Sales")
    old_path = str(tmp_path / "old.tmdl")
    fired = threading.Event()

    def callback(_path):
        fired.set()

    handler = _handler(callback=callback)
    handler.on_moved(_event(old_path, dest_path=str(tmp_path / "notes.txt")))
    assert not fired.wait(0.1)
    handler.cancel_all()


def test_deleted_directory_does_not_fire(tmp_path):
    _pbip, tmdl = _make_report(tmp_path, "Sales")
    fired = threading.Event()

    def callback(_path):
        fired.set()

    handler = _handler(callback=callback)
    handler.on_deleted(_event(tmdl, is_directory=True))
    assert not fired.wait(0.1)
    handler.cancel_all()


def test_moved_directory_does_not_fire(tmp_path):
    _pbip, tmdl = _make_report(tmp_path, "Sales")
    fired = threading.Event()

    def callback(_path):
        fired.set()

    handler = _handler(callback=callback)
    handler.on_moved(_event(tmdl, is_directory=True, dest_path=str(tmp_path / "dest")))
    assert not fired.wait(0.1)
    handler.cancel_all()


def test_deleted_non_tmdl_does_not_fire(tmp_path):
    _pbip, _tmdl = _make_report(tmp_path, "Sales")
    fired = threading.Event()

    def callback(_path):
        fired.set()

    handler = _handler(callback=callback)
    handler.on_deleted(_event(str(tmp_path / "readme.txt")))
    assert not fired.wait(0.1)
    handler.cancel_all()


def test_raising_callback_is_contained(tmp_path):
    pbip, _tmdl = _make_report(tmp_path, "Sales")
    calls = []

    def callback(path):
        calls.append(path)
        raise RuntimeError("boom")

    handler = _handler(callback=callback)
    handler._fire(pbip)

    assert calls == [pbip]


def test_nested_layout_resolves_to_pbip(tmp_path):
    model = tmp_path / "Sales.SemanticModel"
    tables = model / "definition" / "tables"
    tables.mkdir(parents=True)
    tmdl = tables / "Product.tmdl"
    tmdl.write_text("t", encoding="utf-8")
    pbip = tmp_path / "Sales.pbip"
    pbip.write_text("", encoding="utf-8")

    fired = threading.Event()
    result = []

    def callback(path):
        result.append(path)
        fired.set()

    handler = _handler(callback=callback)
    handler.on_modified(_event(str(tmdl)))

    _wait_for(fired)
    assert result == [str(pbip)]
    handler.cancel_all()


def test_root_drive_candidate_resolves(monkeypatch):
    real_exists = os.path.exists
    root = os.sep
    tmdl = os.path.join(root, "Sales.SemanticModel", "table.tmdl")
    expected = os.path.join(root, "Sales.pbip")

    def fake_exists(path):
        if os.path.normcase(path) == os.path.normcase(expected):
            return True
        return real_exists(path)

    monkeypatch.setattr(watcher.os.path, "exists", fake_exists)

    fired = threading.Event()
    result = []

    def callback(path):
        result.append(path)
        fired.set()

    handler = _handler(callback=callback)
    handler.on_modified(_event(tmdl))

    _wait_for(fired)
    assert result == [expected]
    handler.cancel_all()
