"""Where the app keeps its data (database, profile, resume, caches).

Order: --data-dir flag (sets EMPLOID_DATA) or the EMPLOID_DATA env var, otherwise the OS's per-user data folder
(Linux ~/.local/share/emploid, macOS ~/Library/Application Support/emploid, Windows %LOCALAPPDATA%\\emploid)."""
import os
from pathlib import Path


def data_dir():
    env = os.environ.get("EMPLOID_DATA")
    if env:
        p = Path(env).expanduser()
    else:
        from platformdirs import user_data_dir
        p = Path(user_data_dir("emploid", appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)  # resume + answers + keys live here
    except OSError:
        pass
    return p
