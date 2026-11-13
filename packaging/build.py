"""Build the standalone app for the current OS:  python packaging/build.py
Output: dist/emploid-<os>.zip (Windows) or .tar.gz (Linux/macOS) containing a emploid/ folder."""
import platform
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
name = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform, sys.platform)
arch = platform.machine().lower().replace("amd64", "x86_64")

shutil.rmtree(DIST / "emploid", ignore_errors=True)
PyInstaller.__main__.run([
    str(ROOT / "packaging" / "launcher.py"),
    "--name", "emploid",
    "--noconfirm", "--clean", "--onedir", "--console",
    "--paths", str(ROOT / "src"),
    "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    "--collect-all", "emploid",      # code, static files, programs.json, companies.txt
    "--collect-all", "playwright",      # includes the driver used to download the browser
    "--collect-all", "geonamescache",   # country / city data
    "--collect-all", "langdetect",      # language profiles
    "--collect-submodules", "waitress",
])
shutil.copy(ROOT / "packaging" / "BUNDLE-README.txt", DIST / "emploid" / "README.txt")
shutil.copy(ROOT / "LICENSE", DIST / "emploid" / "LICENSE.txt")
out = DIST / f"emploid-{name}-{arch}"
if sys.platform == "win32":
    archive = shutil.make_archive(str(out), "zip", DIST, "emploid")
else:
    archive = shutil.make_archive(str(out), "gztar", DIST, "emploid")
print("built", archive)
