"""Job sources. Every fetcher returns a list of normalised jobs (see classify.make_job).

Aggregators return everything they have; company-board crawlers (Greenhouse, Lever, Ashby,
SmartRecruiters, Workable, Recruitee) go through the company list so small employers show up too.
Filtering by the user's parameters happens in search.py, not here.
"""
import datetime as dt
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import db
from .classify import make_job

UA = {"User-Agent": "Mozilla/5.0 (compatible; emploid/1.0; personal job search tool)"}
CACHE_DIR = db.DATA / "cache"
CACHE_TTL = 4 * 3600
TIMEOUT = 15
_session = requests.Session()
_session.headers.update(UA)


def prune_cache(max_age=3 * 86400):
    """Delete cached responses older than a few days so the folder doesn't grow forever."""
    cutoff = time.time() - max_age
    try:
        for f in CACHE_DIR.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
        for f in CACHE_DIR.glob("*.txt"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def _cache_path(key):
    return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def get_json(url, params=None, ttl=CACHE_TTL, method="GET", body=None):
    """GET/POST JSON with a small on-disk cache so repeated searches stay polite and fast.
    Returns None on 404 / network errors."""
    key = f"{method}|{url}|{json.dumps(params, sort_keys=True)}|{json.dumps(body, sort_keys=True)}"
    cp = _cache_path(key)
    if ttl and cp.exists() and time.time() - cp.stat().st_mtime < ttl:
        try:
            return json.loads(cp.read_text())
        except ValueError:
            pass
    try:
        r = _session.request(method, url, params=params, json=body, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data))
    return data


def get_text(url, ttl=CACHE_TTL):
    cp = _cache_path("T|" + url)
    if ttl and cp.exists() and time.time() - cp.stat().st_mtime < ttl:
        return cp.read_text()
    try:
        r = _session.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_text(r.text)
    return r.text


def _iso(ts):
    """Accept ms/s epochs or ISO strings; return ISO date string or None."""
    if ts in (None, ""):
        return None
    if isinstance(ts, (int, float)):
        if ts > 1e11:
            ts /= 1000
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()
    return str(ts)


def _pretty(slug):
    return re.sub(r"[-_]+", " ", slug).title()


# ---------------------------------------------------------------- aggregators

def remotive(params, cfg):
    out = []
    terms = params["phrases"] or [""]
    for term in terms[:6]:
        data = get_json("https://remotive.com/api/remote-jobs", {"search": term} if term else None)
        for j in (data or {}).get("jobs", []):
            out.append(make_job("Remotive", j["title"], j["company_name"], j["url"],
                                j.get("candidate_required_location", ""), True, j.get("job_type", ""),
                                j.get("description", ""), j.get("tags"), j.get("publication_date"),
                                salary=j.get("salary", "")))
    return out


def arbeitnow(params, cfg):
    out = []
    for page in range(1, 6):
        data = get_json("https://www.arbeitnow.com/api/job-board-api", {"page": page})
        jobs = (data or {}).get("data", [])
        if not jobs:
            break
        for j in jobs:
            out.append(make_job("Arbeitnow", j["title"], j["company_name"], j["url"], j.get("location", ""),
                                j.get("remote", False), " ".join(j.get("job_types", [])),
                                j.get("description", ""), j.get("tags"), _iso(j.get("created_at"))))
    return out


def remoteok(params, cfg):
    data = get_json("https://remoteok.com/api") or []
    return [make_job("RemoteOK", j["position"], j["company"], j.get("url") or j.get("apply_url"),
                     j.get("location") or "Remote", True, "", j.get("description", ""), j.get("tags"),
                     j.get("date"), apply_url=j.get("apply_url"))
            for j in data if isinstance(j, dict) and j.get("position")]


def jobicy(params, cfg):
    data = get_json("https://jobicy.com/api/v2/remote-jobs", {"count": 100}) or {}
    return [make_job("Jobicy", j["jobTitle"], j["companyName"], j["url"], j.get("jobGeo", ""), True,
                     " ".join(j.get("jobType", []) if isinstance(j.get("jobType"), list) else [j.get("jobType", "")]),
                     j.get("jobDescription", ""), j.get("jobIndustry"), j.get("pubDate"))
            for j in data.get("jobs", [])]


def himalayas(params, cfg):
    out = []
    for offset in range(0, 300, 20):
        data = get_json("https://himalayas.app/jobs/api", {"limit": 20, "offset": offset})
        jobs = (data or {}).get("jobs", [])
        if not jobs:
            break
        for j in jobs:
            out.append(make_job("Himalayas", j["title"], j.get("companyName", ""), j["applicationLink"],
                                ", ".join(j.get("locationRestrictions") or ["Worldwide"]), True,
                                j.get("employmentType", ""), j.get("description", ""),
                                j.get("categories"), _iso(j.get("pubDate"))))
    return out


def weworkremotely(params, cfg):
    text = get_text("https://weworkremotely.com/remote-jobs.rss")
    out = []
    if not text:
        return out
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        company, _, role = title.partition(": ")
        out.append(make_job("We Work Remotely", role or title, company if role else "", item.findtext("link"),
                            item.findtext("region") or "Remote", True, "", item.findtext("description") or "",
                            None, item.findtext("pubDate")))
    return out


def custom_feeds(params, cfg):
    """User-supplied RSS/Atom feeds (settings > custom feeds)."""
    out = []
    for url in cfg.get("feeds", []):
        text = get_text(url)
        if not text:
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        for item in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
            link = item.findtext("link") or (item.find("{http://www.w3.org/2005/Atom}link") is not None and
                                              item.find("{http://www.w3.org/2005/Atom}link").get("href"))
            title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
            desc = item.findtext("description") or item.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            out.append(make_job("Custom feed", title, "", link, "", False, "", desc))
    return out


# ------------------------------------------------------------- keyed APIs (optional)

def adzuna(params, cfg):
    key = cfg.get("keys", {})
    app_id, app_key = key.get("adzuna_id"), key.get("adzuna_key")
    if not (app_id and app_key):
        return []
    out = []
    countries = [c.strip().lower() for c in key.get("adzuna_countries", "gb,us,fr,de").split(",") if c.strip()]
    for country in countries:
        for term in (params["phrases"] or [""])[:4]:
            q = {"app_id": app_id, "app_key": app_key, "results_per_page": 50, "what": term, "content-type": "application/json"}
            if params.get("location"):
                q["where"] = params["location"]
            if "part_time" in params["types"]:
                q["part_time"] = 1
            if "internship" in params["types"]:
                q["what"] = (term + " intern").strip()
            data = get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", q)
            for j in (data or {}).get("results", []):
                out.append(make_job("Adzuna", j["title"], j.get("company", {}).get("display_name", ""),
                                    j["redirect_url"], j.get("location", {}).get("display_name", ""), False,
                                    j.get("contract_time", ""), j.get("description", ""), None, j.get("created")))
    return out


def jooble(params, cfg):
    key = cfg.get("keys", {}).get("jooble_key")
    if not key:
        return []
    out = []
    for term in (params["phrases"] or [""])[:4]:
        kw = term + (" internship" if "internship" in params["types"] else "")
        data = get_json(f"https://jooble.org/api/{key}", method="POST",
                        body={"keywords": kw.strip(), "location": params.get("location", "")})
        for j in (data or {}).get("jobs", []):
            out.append(make_job("Jooble", j["title"], j.get("company", ""), j["link"], j.get("location", ""),
                                False, j.get("type", ""), j.get("snippet", ""), None, j.get("updated")))
    return out


# ------------------------------------------------- curated lists and company career sites

SIMPLIFY_URLS = [
    ("SimplifyJobs", "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"),
    ("Internship list (vanshb03)", "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json"),
]


def _simplify_one(label, url):
    out = []
    for x in get_json(url, ttl=6 * 3600) or []:
        if not x.get("active") or x.get("is_visible") is False or not x.get("url"):
            continue
        terms = [t for t in (x.get("terms") or ([x["season"]] if x.get("season") else [])) if t and t != "N/A"]
        locs = x.get("locations") or []
        out.append(make_job(label, x["title"], x["company_name"], x["url"], ", ".join(locs),
                            any("remote" in l.lower() for l in locs), "internship", "", [x.get("category")],
                            _iso(x.get("date_posted")), start_hint=", ".join(terms),
                            extra={k: v for k, v in (("sponsorship", x.get("sponsorship")),
                                                     ("degrees", x.get("degrees"))) if v and v != "Other"}))
    return out


def simplify(params, cfg):
    """Curated, community-maintained internship lists: structured start terms (Summer 2027 ...)."""
    out = []
    for label, url in SIMPLIFY_URLS:
        out.extend(_simplify_one(label, url))
    return out


GOOGLE_TYPES = {"internship": "INTERN", "part_time": "PART_TIME", "full_time": "FULL_TIME"}


def google_careers(params, cfg):
    """Google's own careers site (also lists DeepMind, YouTube, Waymo ...)."""
    out = []
    emp = [GOOGLE_TYPES[t] for t in params["types"] if t in GOOGLE_TYPES]
    for term in (params["phrases"] or [""])[:4]:
        for page in range(1, 6):
            q = [("page", page)] + ([("q", term)] if term else []) + [("employment_type", e) for e in emp]
            try:
                r = _session.get("https://www.google.com/about/careers/applications/jobs/results/", params=q, timeout=TIMEOUT)
            except requests.RequestException:
                break
            m = re.search(r"AF_initDataCallback\(\{key: 'ds:1', hash: '2', data:(.*?), sideChannel", r.text, re.S) if r.status_code == 200 else None
            if not m:
                break
            try:
                data = json.loads(m.group(1))
            except ValueError:
                break
            jobs = data[0] or []
            for j in jobs:
                def part(i):
                    v = j[i] if len(j) > i else None
                    return v[1] if isinstance(v, list) and len(v) > 1 and v[1] else ""
                locs = [l[0] for l in (j[9] or []) if l]
                out.append(make_job("Google Careers", j[1], j[7] or "Google",
                                    f"https://www.google.com/about/careers/applications/jobs/results/{j[0]}",
                                    "; ".join(locs), False, "",
                                    "\n".join(x for x in (part(10), part(3), part(4), part(19)) if x),
                                    None, _iso(j[12][0]) if len(j) > 12 and j[12] else None))
            if len(jobs) < 20:
                break
    return out


def _parse_us_date(s):
    try:
        return dt.datetime.strptime(s, "%B %d, %Y").isoformat()
    except (ValueError, TypeError):
        return None


def amazon_jobs(params, cfg):
    out = []
    intern = "internship" in params["types"]
    for term in (params["phrases"] or [""])[:4]:
        q = (term + (" intern" if intern else "")).strip()
        for page in range(2):
            data = get_json("https://www.amazon.jobs/en/search.json",
                            {"base_query": q, "result_limit": 100, "offset": page * 100})
            jobs = (data or {}).get("jobs", [])
            for j in jobs:
                out.append(make_job("Amazon Jobs", j["title"], j.get("company_name") or "Amazon",
                                    "https://www.amazon.jobs" + j["job_path"], j.get("normalized_location") or j.get("location", ""),
                                    False, j.get("job_schedule_type", ""),
                                    "\n".join(filter(None, (j.get("description"), j.get("basic_qualifications")))),
                                    [j.get("job_category")], _parse_us_date(j.get("posted_date"))))
            if len(jobs) < 100:
                break
    return out


def microsoft_jobs(params, cfg):
    out = []
    intern = "internship" in params["types"]
    for term in (params["phrases"] or [""])[:3]:
        q = (term + (" intern" if intern else "")).strip()
        for start in range(0, 50, 10):
            data = get_json("https://apply.careers.microsoft.com/api/pcsx/search",
                            {"domain": "microsoft.com", "query": q, "start": start})
            pos = ((data or {}).get("data") or {}).get("positions", [])
            for p in pos:
                locs = p.get("standardizedLocations") or p.get("locations") or []
                out.append(make_job("Microsoft Careers", p["name"], "Microsoft",
                                    "https://apply.careers.microsoft.com" + p["positionUrl"], "; ".join(locs),
                                    p.get("workLocationOption") == "remote", "", "", [p.get("department")],
                                    _iso(p.get("postedTs"))))
            if len(pos) < 10:
                break
    return out


WORKDAY = [  # (display name, tenant, wd host, site) - each verified to answer
    ("NVIDIA", "nvidia", "wd5", "NVIDIAExternalCareerSite"), ("Salesforce", "salesforce", "wd12", "External_Career_Site"),
    ("Adobe", "adobe", "wd5", "external_experienced"), ("Intel", "intel", "wd1", "External"),
    ("HP", "hp", "wd5", "ExternalCareerSite"), ("Mastercard", "mastercard", "wd1", "CorporateCareers"),
    ("Capital One", "capitalone", "wd12", "Capital_One"), ("Target", "target", "wd5", "targetcareers"),
    ("Workday", "workday", "wd5", "Workday"), ("Broadcom", "broadcom", "wd1", "External_Career"),
    ("Cisco", "cisco", "wd5", "Cisco_Careers"), ("PayPal", "paypal", "wd1", "jobs"),
    ("Autodesk", "autodesk", "wd1", "Ext"), ("Zoom", "zoom", "wd5", "Zoom"), ("Snap", "snapchat", "wd1", "snap"),
    ("3M", "3m", "wd1", "Search"), ("Boeing", "boeing", "wd1", "EXTERNAL_CAREERS"),
    ("CVS Health", "cvshealth", "wd1", "CVS_Health_Careers"), ("Pfizer", "pfizer", "wd1", "PfizerCareers"),
    ("Analog Devices", "analogdevices", "wd1", "External"), ("Micron", "micron", "wd1", "External"),
    ("KLA", "kla", "wd1", "Search"), ("Cadence", "cadence", "wd1", "External_Careers"),
    ("Sonos", "sonos", "wd1", "Sonos"),
]


def _wd_posted(text):
    m = re.search(r"(\d+)\+? days? ago", text or "", re.I)
    if m:
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(m.group(1)))).isoformat()
    if re.search(r"today", text or "", re.I):
        return dt.datetime.now(dt.timezone.utc).isoformat()
    if re.search(r"yesterday", text or "", re.I):
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    return None


def workday(params, cfg):
    """Workday career sites: the curated large employers, plus every Workday tenant discovered from links."""
    from . import harvest
    from .query import company_matches
    targets = params.get("companies") or []
    intern = "internship" in params["types"]
    terms = [(t + (" intern" if intern else "")).strip() for t in (params["phrases"] or [""])[:3]]
    listed = {(w[1], w[3]) for w in WORKDAY}
    entries = [(name, tenant, wd, site, terms, 3) for name, tenant, wd, site in WORKDAY]
    for w in harvest.load()["workday"]:  # discovered: one query, first page only, to keep the search fast
        if (w["tenant"], w["site"]) not in listed:
            entries.append((w["name"], w["tenant"], w["wd"], w["site"], terms[:1], 1))
    tasks = [(n, t, wd, s, q, pages) for n, t, wd, s, qs, pages in entries
             if not targets or company_matches(n, targets) for q in qs]
    jobs = []

    def one(t):
        name, tenant, wd, site, q, pages = t
        found = []
        for offset in range(0, 20 * pages, 20):
            data = get_json(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                            method="POST", body={"searchText": q, "limit": 20, "offset": offset, "appliedFacets": {}})
            posts = (data or {}).get("jobPostings", [])
            for p in posts:
                if not p.get("externalPath"):
                    continue
                found.append(make_job(
                    "Workday", p["title"], name, f"https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{p['externalPath']}",
                    p.get("locationsText", ""), "remote" in (p.get("locationsText", "")).lower(), "", "", None,
                    _wd_posted(p.get("postedOn")),
                    extra={"workday": {"tenant": tenant, "wd": wd, "site": site, "path": p["externalPath"]}}))
            if len(posts) < 20:
                break
        return found

    with ThreadPoolExecutor(16) as ex:
        for res in ex.map(one, tasks):
            jobs.extend(res)
    return jobs


def workingnomads(params, cfg):
    return [make_job("Working Nomads", j["title"], j.get("company_name", ""), j["url"], j.get("location") or "Remote",
                     True, "", j.get("description", ""), (j.get("tags") or "").split(",") + [j.get("category_name")],
                     j.get("pub_date")) for j in (get_json("https://www.workingnomads.com/api/exposed_jobs/") or [])]


def jobspresso(params, cfg):
    text = get_text("https://jobspresso.co/feed/?post_type=job_listing")
    out = []
    try:
        root = ET.fromstring(text or "")
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        out.append(make_job("Jobspresso", item.findtext("title") or "", "", item.findtext("link"), "Remote", True, "",
                            item.findtext("description") or "", None, item.findtext("pubDate")))
    return out


# ----------------------------------------------------------------------- abroad-focused sources

EURES_CODES = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE IS LI NO CH".split())


def eures(params, cfg):
    """EURES, the EU job mobility portal: public vacancies across the EU/EEA and Switzerland."""
    wanted = [c.lower() for c in params.get("country_codes", []) if c in EURES_CODES]
    if params.get("country_codes") and not wanted:
        return []  # none of the chosen countries is covered by EURES
    intern = "internship" in params["types"]
    terms = []
    for ph in (params["phrases"] or [""])[:3]:
        if intern:
            terms += [f"{ph} internship".strip(), f"{ph} traineeship".strip()]
        else:
            terms.append(ph)
    out = []
    for term in terms:
        for page in range(1, 4):
            body = {"resultsPerPage": 50, "page": page, "sortSearch": "BEST_MATCH",
                    "keywords": [{"keyword": term, "specificSearchCode": "EVERYWHERE"}] if term else [],
                    "publicationPeriod": None, "occupationUris": [], "skillUris": [], "requiredExperienceCodes": [],
                    "positionScheduleCodes": [], "sectorCodes": [], "educationAndQualificationLevelCodes": [],
                    "positionOfferingCodes": [], "locationCodes": wanted, "euresFlagCodes": [], "otherBenefitsCodes": [],
                    "requiredLanguages": [], "minNumberPost": None, "sessionId": "emploid"}
            data = get_json("https://europa.eu/eures/api/jv-searchengine/public/jv-search/search", method="POST", body=body)
            jvs = (data or {}).get("jvs", [])
            for j in jvs:
                emp = j.get("employer") or {}
                sched = j.get("positionScheduleCodes") or []
                out.append(make_job("EURES", j.get("title", ""), emp.get("name", ""),
                                    f"https://europa.eu/eures/portal/jv-se/jv-details/{j['id']}?lang=en",
                                    ", ".join(sorted((j.get("locationMap") or {}).keys())), False,
                                    "part_time" if sched == ["parttime"] else "", j.get("description", ""), None,
                                    _iso(j.get("creationDate")), countries=list((j.get("locationMap") or {}).keys()),
                                    extra={"website": emp.get("website", "")}))
            if len(jvs) < 50:
                break
    return out


def landing_jobs(params, cfg):
    """Landing.jobs: tech jobs in Europe, with a relocation flag."""
    out = []
    for offset in range(0, 300, 50):
        data = get_json("https://landing.jobs/api/v1/jobs", {"limit": 50, "offset": offset})
        if not data:
            break
        for j in data:
            m = re.search(r"/at/([^/]+)/", j.get("url", ""))
            locs = j.get("locations") or []
            out.append(make_job("Landing.jobs", j["title"], _pretty(m.group(1)) if m else "", j["url"],
                                ", ".join(l.get("city", "") for l in locs), bool(j.get("remote")), j.get("type", ""),
                                "\n".join(filter(None, (j.get("role_description"), j.get("main_requirements"), j.get("perks")))),
                                j.get("tags"), j.get("published_at"), countries=[l["country_code"] for l in locs if l.get("country_code")],
                                extra={"relocation": bool(j.get("relocation_paid"))}))
        if len(data) < 50:
            break
    return out


def programs(params, cfg):
    """Curated international internship programmes (programs.json). Deadlines change every year:
    each entry links to the official page."""
    path = Path(__file__).resolve().parent / "programs.json"
    try:
        items = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return [make_job("Programs", p["name"], p["org"], p["url"], ", ".join(p["countries"]), False, "internship",
                     p["description"], p.get("tags"), None, countries=p["countries"], extra={"program": True}) for p in items]


# source label (as shown on a job) -> settings key; used by the source health view and "stop searching"
LABEL_TO_KEY = {"Remotive": "remotive", "Arbeitnow": "arbeitnow", "RemoteOK": "remoteok", "Jobicy": "jobicy", "Himalayas": "himalayas",
                "We Work Remotely": "weworkremotely", "Greenhouse": "greenhouse", "Lever": "lever", "Ashby": "ashby",
                "SmartRecruiters": "smartrecruiters", "Workable": "workable", "Recruitee": "recruitee",
                "Google Careers": "google_careers", "Amazon Jobs": "amazon_jobs", "Microsoft Careers": "microsoft_jobs",
                "Workday": "workday", "Working Nomads": "workingnomads", "Jobspresso": "jobspresso", "SimplifyJobs": "simplify",
                "Internship list (vanshb03)": "simplify", "Adzuna": "adzuna", "Jooble": "jooble", "Custom feed": "feeds",
                "EURES": "eures", "Landing.jobs": "landing", "Programs": "programs"}


# adapters that serve a single employer: only run when the search targets that employer (or nobody)
TARGETED = {"google_careers": ["google"], "amazon_jobs": ["amazon"], "microsoft_jobs": ["microsoft"]}


# ----------------------------------------------------------- company-board crawlers

def _greenhouse(slug):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if data is None:
        return None
    return [make_job("Greenhouse", j["title"], j.get("company_name") or _pretty(slug), j["absolute_url"],
                     (j.get("location") or {}).get("name", ""), False, "", "", None, j.get("updated_at"),
                     apply_url=f"https://job-boards.greenhouse.io/{slug}/jobs/{j['id']}",
                     ats_ref=("greenhouse", slug, str(j["id"])))
            for j in data.get("jobs", [])]


def _lever(slug):
    data = get_json(f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"})
    if data is None:
        data = get_json(f"https://api.eu.lever.co/v0/postings/{slug}", {"mode": "json"})
    if data is None or not isinstance(data, list):
        return None
    out = []
    for j in data:
        c = j.get("categories") or {}
        loc = c.get("location") or ", ".join(c.get("allLocations") or [])
        out.append(make_job("Lever", j["text"], _pretty(slug), j["hostedUrl"], loc,
                            j.get("workplaceType") == "remote", c.get("commitment", ""),
                            j.get("descriptionPlain", ""), [c.get("team")], _iso(j.get("createdAt")),
                            apply_url=j.get("applyUrl")))
    return out


def _ashby(slug):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if data is None:
        return None
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        out.append(make_job("Ashby", j["title"], _pretty(slug), j["jobUrl"], j.get("location", ""),
                            j.get("isRemote", False), j.get("employmentType", ""),
                            j.get("descriptionPlain", ""), [j.get("department")], j.get("publishedAt"),
                            apply_url=j.get("applyUrl")))
    return out


def _smartrecruiters(slug):
    data = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", {"limit": 100})
    if not data or not data.get("content"):
        return None
    out = []
    for j in data["content"]:
        loc = j.get("location") or {}
        out.append(make_job("SmartRecruiters", j["name"], (j.get("company") or {}).get("name") or _pretty(slug),
                            f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                            ", ".join(x for x in (loc.get("city"), loc.get("country", "").upper()) if x),
                            loc.get("remote", False), (j.get("typeOfEmployment") or {}).get("label", ""),
                            "", [(j.get("function") or {}).get("label")], j.get("releasedDate")))
    return out


def _workable(slug):
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", {"details": "true"})
    if not data or "jobs" not in data:
        return None
    return [make_job("Workable", j["title"], data.get("name") or _pretty(slug), j["url"],
                     ", ".join(x for x in (j.get("city"), j.get("country")) if x),
                     j.get("telecommuting", False), j.get("employment_type", ""),
                     j.get("description", ""), [j.get("department")], j.get("published_on"))
            for j in data["jobs"]]


def _recruitee(slug):
    data = get_json(f"https://{slug}.recruitee.com/api/offers/")
    if not data or "offers" not in data:
        return None
    return [make_job("Recruitee", j["title"], j.get("company_name") or _pretty(slug), j["careers_url"],
                     j.get("location", ""), j.get("remote", False), j.get("employment_type_code", ""),
                     j.get("description", ""), [j.get("department")], j.get("created_at"))
            for j in data["offers"]]


BOARDS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby,
          "smartrecruiters": _smartrecruiters, "workable": _workable, "recruitee": _recruitee}

AGGREGATORS = {
    "remotive": remotive, "arbeitnow": arbeitnow, "remoteok": remoteok, "jobicy": jobicy,
    "himalayas": himalayas, "weworkremotely": weworkremotely, "feeds": custom_feeds,
    "adzuna": adzuna, "jooble": jooble,
    "simplify": simplify, "google_careers": google_careers, "amazon_jobs": amazon_jobs,
    "microsoft_jobs": microsoft_jobs, "workday": workday, "workingnomads": workingnomads, "jobspresso": jobspresso,
    "eures": eures, "landing": landing_jobs, "programs": programs,
}


DEAD_TTL = 14 * 86400


def crawl_boards(slugs, enabled, progress, dead, workers=24, extra_pairs=()):
    """Try every slug on every enabled board system.

    `dead` maps "board:slug" -> epoch of a failed lookup; those are skipped for two weeks so the
    big slug list stays cheap. Returns (jobs, working) where working maps board -> [slugs]."""
    now = time.time()
    tasks = [(b, s) for s in slugs for b in BOARDS if b in enabled
             if now - dead.get(f"{b}:{s}", 0) > DEAD_TTL]
    have = set(tasks)
    tasks += [(b, s) for b, s in extra_pairs if b in enabled and (b, s) not in have
              and now - dead.get(f"{b}:{s}", 0) > DEAD_TTL]
    jobs, working, failed = [], {b: [] for b in BOARDS}, []
    done = 0

    def one(t):
        b, s = t
        try:
            return t, BOARDS[b](s)
        except Exception:
            return t, None

    with ThreadPoolExecutor(workers) as ex:
        for (b, s), res in ex.map(one, tasks):
            done += 1
            if res is None:
                failed.append(f"{b}:{s}")
            else:
                working[b].append(s)
                jobs.extend(res)
            if done % 10 == 0 or done == len(tasks):
                progress(done, len(tasks), len(jobs))
    if any(working.values()):  # an offline run must not blacklist every slug
        for k in failed:
            dead[k] = now
    return jobs, working
