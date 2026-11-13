"""The `emploid` command."""
import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

DEFAULT_PORT = 8765


def _health(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            return json.loads(r.read()).get("ok") is True
    except Exception:
        return False


def _port_free(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0 if os.name == "nt" else 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _doctor():
    from . import __version__
    ok = True

    def line(good, text):
        nonlocal ok
        ok = ok and good
        print(("  ok   " if good else "  FAIL ") + text)

    print(f"emploid {__version__}  (python {sys.version.split()[0]})")
    from . import db
    line(True, f"data folder: {db.DATA}")
    try:
        import requests
        requests.get("https://remotive.com/api/remote-jobs?limit=1", timeout=10).raise_for_status()
        line(True, "internet access to job sources")
    except Exception as e:
        line(False, f"internet access to job sources ({type(e).__name__})")
    from . import apply
    have = apply.browser_installed()
    print(("  ok   " if have else "  --   ") + "apply browser " + ("installed" if have else "not installed (only needed for auto-apply: run `emploid install-browser`)"))
    if not have and getattr(apply.browser_installed, "error", ""):
        print("         " + apply.browser_installed.error)
    return 0 if ok else 1


def main(argv=None):
    from . import __version__
    ap = argparse.ArgumentParser(prog="emploid", description="Search internships and part-time jobs, review and apply, all on your own computer.")
    ap.add_argument("command", nargs="?", default="start", choices=["start", "doctor", "install-browser", "data-dir"],
                    help="start (default): run the app | doctor: check the setup | install-browser: get the browser used by auto-apply | data-dir: print where your data lives")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true", help="don't open the page automatically")
    ap.add_argument("--data-dir", help="keep data in this folder instead of the default one")
    ap.add_argument("--version", action="version", version=f"emploid {__version__}")
    args = ap.parse_args(argv)

    if args.data_dir:
        os.environ["EMPLOID_DATA"] = args.data_dir

    if args.command == "data-dir":
        from . import paths
        print(paths.data_dir())
        return 0
    if args.command == "doctor":
        return _doctor()
    if args.command == "install-browser":
        import subprocess
        from playwright._impl._driver import get_driver_env
        from . import apply
        return subprocess.call(apply.install_command(), env={**os.environ, **get_driver_env()})

    url = f"http://127.0.0.1:{args.port}"
    if _health(args.port):  # already running: just show it
        print(f"emploid is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    if not _port_free(args.port):
        print(f"Port {args.port} is used by something else. Try: emploid --port {args.port + 1}", file=sys.stderr)
        return 1

    from . import server
    if not args.no_browser:
        def opener():
            for _ in range(60):
                if _health(args.port):
                    webbrowser.open(url)
                    return
                time.sleep(0.25)
        threading.Thread(target=opener, daemon=True).start()
    print(f"emploid {__version__} running at {url}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve(args.port)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
