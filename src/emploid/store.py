"""Small helpers for the JSON files in the data folder: atomic writes, tolerant reads."""
import json
import os
import tempfile
import threading
from pathlib import Path

_lock = threading.Lock()


def write_json(path, data, indent=None):
    """Write to a temp file and swap it in, so a crash can never leave half a file behind.
    Files are private to the user (they can hold API keys and personal answers)."""
    path = Path(path)
    with _lock:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
