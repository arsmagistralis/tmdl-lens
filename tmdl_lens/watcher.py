"""
watcher.py - File watcher for tmdl-lens.

Monitors a reports folder for TMDL file changes and fires a callback
with the resolved .pbip path after a configurable debounce window.

Requires the 'watchdog' package. If watchdog is not installed the module
sets WATCHER_AVAILABLE = False and TmdlWatcher becomes a no-op so the
rest of the app can degrade gracefully without crashing.
"""

import os
import threading

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHER_AVAILABLE = True
except ImportError:
    WATCHER_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_pbip_for_tmdl(tmdl_path: str) -> str | None:
    """
    Walk up from a changed .tmdl file to find the owning .pbip file.

    Expected layout:
        <report>.SemanticModel/
            definition/
                tables/
                    SomeTable.tmdl   <-- changed file lands here (or similar)
        <report>.pbip                <-- what we want to return

    Strategy: keep going up until we find a folder ending in '.SemanticModel',
    then look for a .pbip sibling in the parent directory.
    """
    current = os.path.normpath(tmdl_path)

    while True:
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
        base = os.path.basename(current)
        if base.endswith(".SemanticModel"):
            report_name = base[: -len(".SemanticModel")]
            candidate = os.path.join(os.path.dirname(current), report_name + ".pbip")
            if os.path.exists(candidate):
                return candidate
            break

    return None


# ---------------------------------------------------------------------------
# Event handler (only defined when watchdog is available)
# ---------------------------------------------------------------------------

if WATCHER_AVAILABLE:

    class _TmdlEventHandler(FileSystemEventHandler):

        def __init__(self, debounce_seconds: int, callback):
            super().__init__()
            self._debounce  = debounce_seconds
            self._callback  = callback
            self._timers: dict[str, threading.Timer] = {}
            self._lock = threading.Lock()

        def on_modified(self, event):
            self._handle(event)

        def on_created(self, event):
            self._handle(event)

        def on_deleted(self, event):
            self._handle(event)

        def on_moved(self, event):
            self._handle(event, event.dest_path)

        def _handle(self, event, path=None):
            if event.is_directory:
                return
            path = path or event.src_path
            if not path.endswith(".tmdl"):
                return

            pbip = _find_pbip_for_tmdl(path)
            if pbip is None:
                return

            with self._lock:
                existing = self._timers.get(pbip)
                if existing:
                    existing.cancel()
                timer = threading.Timer(self._debounce, self._fire, args=(pbip,))
                self._timers[pbip] = timer
                timer.start()

        def _fire(self, pbip: str):
            with self._lock:
                self._timers.pop(pbip, None)
            try:
                self._callback(pbip)
            except Exception:
                pass

        def cancel_all(self):
            with self._lock:
                for t in self._timers.values():
                    t.cancel()
                self._timers.clear()


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class TmdlWatcher:
    """
    Wraps a watchdog Observer to watch a folder for TMDL changes.

    Usage:
        watcher = TmdlWatcher(folder, debounce_seconds=10, callback=on_change)
        watcher.start()
        ...
        watcher.stop()

    callback(pbip_path: str) is called on the watchdog thread after debounce.
    The caller is responsible for any thread-safety when updating the UI.

    If WATCHER_AVAILABLE is False, start() and stop() are silent no-ops.
    """

    def __init__(self, folder: str, debounce_seconds: int, callback):
        self._folder   = folder
        self._debounce = debounce_seconds
        self._callback = callback
        self._observer = None
        self._handler  = None

    def start(self):
        if not WATCHER_AVAILABLE:
            return
        if self._observer and self._observer.is_alive():
            return

        self._handler  = _TmdlEventHandler(self._debounce, self._callback)
        self._observer = Observer()
        self._observer.schedule(self._handler, self._folder, recursive=True)
        self._observer.start()

    def stop(self):
        if not WATCHER_AVAILABLE:
            return
        if self._handler:
            self._handler.cancel_all()
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            self._handler  = None

    @property
    def is_running(self) -> bool:
        return (
            WATCHER_AVAILABLE
            and self._observer is not None
            and self._observer.is_alive()
        )
