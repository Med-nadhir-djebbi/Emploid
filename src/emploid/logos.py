"""Company logos: find the company's real domain, then fetch its icon (cached on disk).

Domain evidence, best first: the posting's own link (when it is not a job-board link), the Clearbit
name->domain lookup, then a verified guess (<name>.com whose home page mentions the company).
A wrong logo is worse than none, so anything unverified returns nothing and the UI shows initials."""
import re
import threading
import time
from urllib.parse import urlparse

import requests

from . import db, query

LOGO_DIR = db.DATA / "logos"
LOGO_DIR.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; emploid/1.0; personal job search tool)"}
NEGATIVE_TTL = 7 * 86400
_slots = threading.BoundedSemaphore(6)
_locks = {}
_locks_guard = threading.Lock()

# job boards, ATSs and aggregators: their domain says nothing about the employer
GENERIC = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "workday.com", "smartrecruiters.com",
           "workable.com", "recruitee.com", "remotive.com", "arbeitnow.com", "remoteok.com", "jobicy.com",
           "himalayas.app", "weworkremotely.com", "workingnomads.com", "jobspresso.co", "adzuna.com", "jooble.org",
           "github.com", "simplify.jobs", "icims.com", "taleo.net", "successfactors.com", "successfactors.eu",
           "breezy.hr", "bamboohr.com", "jobvite.com", "linkedin.com", "indeed.com", "glassdoor.com", "wellfound.com",
           "ycombinator.com", "teamtailor.com", "personio.de", "personio.com", "join.com", "go.vansh.nyc",
           "oraclecloud.com", "paylocity.com", "ultipro.com", "dayforcehcm.com", "applytojob.com", "jazz.co",
           "careers-page.com", "hire.lever.co", "pinpointhq.com", "rippling.com", "gh_jid", "eightfold.ai",
           "phenompeople.com", "avature.net", "csod.com", "cornerstoneondemand.com", "apply.workable.com")
TWO_PART_TLDS = {"co.uk", "com.au", "co.in", "co.jp", "com.br", "co.nz", "com.tn", "co.za", "com.sg", "com.tr"}


def registrable(host):
    labels = host.lower().split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_PART_TLDS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def own_domain(url):
    """The employer's domain when `url` is on the employer's own site, else ''."""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    if not host or any(host == g or host.endswith("." + g) for g in GENERIC):
        return ""
    return registrable(host)


def _key(company):
    return re.sub(r"[^a-z0-9]+", "-", query.clean_company(company)).strip("-")[:60] or "unknown"


def _fetch_icon(domain):
    try:
        r = requests.get(f"https://icons.duckduckgo.com/ip3/{domain}.ico", headers=UA, timeout=8)
    except requests.RequestException:
        return None
    return r.content if r.status_code == 200 and len(r.content) > 300 else None


def _lookup_domain(company):
    """Clearbit's free name -> domain suggestion, accepted only on a clear name match."""
    try:
        r = requests.get("https://autocomplete.clearbit.com/v1/companies/suggest", params={"query": company},
                         headers=UA, timeout=6)
        items = r.json() if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return ""
    want = query.clean_company(company)
    for it in items:
        got = query.clean_company(it.get("name", ""))
        if got and (got == want or got.startswith(want + " ")):
            return it.get("domain", "")
    return ""


def _page_mentions(domain, company):
    """Verify a guessed domain: its home page must mention the company name."""
    try:
        r = requests.get(f"https://{domain}", headers=UA, timeout=6)
    except requests.RequestException:
        return False
    head = re.sub(r"\s+", " ", r.text[:40000].lower())
    words = [w for w in query.clean_company(company).split() if len(w) > 1]
    return bool(words) and all(w in head for w in words)


def _candidates(company, url):
    seen = []

    def add(d):
        if d and d not in seen:
            seen.append(d)
            return True
        return False

    own = own_domain(url)
    if own:
        yield own, True
    key = query.clean_company(company)
    if key in query.ALIASES:
        yield key + ".com", True
    looked = _lookup_domain(company)
    if looked and add(looked):
        yield looked, True
    slug = re.sub(r"[^a-z0-9]", "", key)
    for tld in ("com", "io", "ai", "co", "org"):
        guess = f"{slug}.{tld}"
        if slug and add(guess):
            yield guess, False


def resolve(company, url=""):
    """Path of the cached logo file for this company, or None."""
    if not (company or "").strip():
        return None
    key = _key(company)
    for ext in ("png", "ico"):
        p = LOGO_DIR / f"{key}.{ext}"
        if p.exists():
            return p
    miss = LOGO_DIR / f"{key}.none"
    if miss.exists() and time.time() - miss.stat().st_mtime < NEGATIVE_TTL:
        return None
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock, _slots:
        for ext in ("png", "ico"):  # another thread may have finished while we waited
            p = LOGO_DIR / f"{key}.{ext}"
            if p.exists():
                return p
        for domain, trusted in _candidates(company, url):
            icon = _fetch_icon(domain)
            if icon and (trusted or _page_mentions(domain, company)):
                p = LOGO_DIR / (key + (".png" if icon[:4] == b"\x89PNG" else ".ico"))
                p.write_bytes(icon)
                return p
        miss.write_text("")
    return None
