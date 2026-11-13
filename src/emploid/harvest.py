"""Grow the list of company boards by reading the links we already see.

Every posting link names the hiring system and company it belongs to (jobs.lever.co/<company>/...).
Collecting those turns one curated list into hundreds of boards we can search directly."""
import json
import re

from . import db, store

FILE = db.DATA / "discovered.json"
PATTERNS = {
    "greenhouse": re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?([a-z0-9_-]+)", re.I),
    "lever": re.compile(r"jobs(?:\.eu)?\.lever\.co/([a-z0-9_.-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)", re.I),
    "smartrecruiters": re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    "workable": re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I),
    "recruitee": re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com", re.I),
}
WORKDAY = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([^/?#]+)", re.I)
SKIP = {"embed", "jobs", "careers", "www", "apply", "v1", "api", "static"}


def load():
    try:
        d = json.loads(FILE.read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault("boards", {})
    d.setdefault("workday", [])
    return d


def harvest(jobs):
    """Read every link in `jobs`; remember new boards. Returns (discovered, number_new)."""
    d = load()
    known = {b: set(v) for b, v in d["boards"].items()}
    wd_known = {(w["tenant"], w["site"]) for w in d["workday"]}
    new = 0
    for j in jobs:
        for url in {j.get("url") or "", j.get("apply_url") or ""}:
            if not url:
                continue
            for board, rx in PATTERNS.items():
                m = rx.search(url)
                if m and m.group(1).lower() not in SKIP and m.group(1).lower() not in known.setdefault(board, set()):
                    known[board].add(m.group(1).lower())
                    new += 1
            m = WORKDAY.search(url)
            if m and (m.group(1).lower(), m.group(3)) not in wd_known and m.group(3).lower() not in ("login", "job"):
                wd_known.add((m.group(1).lower(), m.group(3)))
                d["workday"].append({"name": j.get("company") or m.group(1), "tenant": m.group(1).lower(),
                                     "wd": m.group(2).lower(), "site": m.group(3)})
                new += 1
    d["boards"] = {b: sorted(v) for b, v in known.items()}
    if new:
        store.write_json(FILE, d)
    return d, new


def pairs(d=None):
    d = d or load()
    return [(b, s) for b, slugs in d["boards"].items() for s in slugs]
