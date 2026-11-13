"""Entry point of the packaged app (double-click on Windows, run on Linux)."""
import multiprocessing
import sys


def _browser_location():
    """The packaged Playwright defaults to a folder inside the app. Use the normal per-user folder instead, so the
    browser survives app updates and is shared with any other Playwright install."""
    import os
    from pathlib import Path
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(base / "ms-playwright")


def run():
    _browser_location()
    from emploid.cli import main
    try:
        code = main()
    except Exception as e:  # a closing window would hide the reason
        print(f"\nEmploid could not start: {type(e).__name__}: {e}")
        code = 1
    if code and sys.platform == "win32":
        input("\nPress Enter to close...")
    return code


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(run())
