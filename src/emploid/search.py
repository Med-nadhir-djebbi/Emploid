"""Search orchestration: run every source, filter by the user's parameters, store results."""
import datetime as dt
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import countries, db, eligibility, enrich, harvest, query, sources, store, translate, verify
from .classify import extract_deadline

DATA = db.DATA
HERE = Path(__file__).resolve().parent
SEARCH_FILE = DATA / "search.json"
SETTINGS_FILE = DATA / "settings.json"
BOARDS_FILE = DATA / "boards.json"
SEED_FILE = HERE / "companies.txt"
MAX_RESULTS = 800

DEFAULT_SETTINGS = {
    "keys": {}, "feeds": [], "companies": [],
    "sources": {n: True for n in list(sources.AGGREGATORS) + list(sources.BOARDS)},
    "headed": False, "dry_run": False, "home_country": "", "auto_apply": False,
}
DEFAULT_SEARCH = {"query": "", "companies": "", "types": ["internship"], "location": "", "remote": "any",
                  "posted_days": 0, "season": "", "start_year": 0, "require_start": False,
                  "countries": [], "visa": "all", "exclude": "", "hide_phd": False}

state = {"running": False, "phase": "idle", "log": [], "per_source": {}, "started": None,
         "finished": None, "matched": 0, "hidden": 0, "new": 0, "error": None, "interpreted": None,
         "steps": []}
_state_lock = threading.Lock()


def _load(path, default):
    try:
        return {**default, **json.loads(path.read_text())}
    except (OSError, ValueError):
        return dict(default)


def load_settings():
    s = _load(SETTINGS_FILE, DEFAULT_SETTINGS)
    s["sources"] = {**DEFAULT_SETTINGS["sources"], **s.get("sources", {})}
    return s


def save_settings(s):
    store.write_json(SETTINGS_FILE, s, indent=2)


def load_search():
    return _load(SEARCH_FILE, DEFAULT_SEARCH)


PRESETS_FILE = DATA / "presets.json"


def load_presets():
    try:
        return json.loads(PRESETS_FILE.read_text())
    except (OSError, ValueError):
        return []


HIDDEN_FILE = DATA / "hidden.json"


def load_hidden():
    try:
        return json.loads(HIDDEN_FILE.read_text())
    except (OSError, ValueError):
        return []


def hide_company(name):
    names = load_hidden()
    if query.clean_company(name) not in {query.clean_company(n) for n in names}:
        names.append(name.strip())
        store.write_json(HIDDEN_FILE, names, indent=1)
    return names


def unhide_company(name):
    names = [n for n in load_hidden() if query.clean_company(n) != query.clean_company(name)]
    store.write_json(HIDDEN_FILE, names, indent=1)
    return names


def update_preset_stats(preset_id, matched, new):
    presets = load_presets()
    for p in presets:
        if p["id"] == preset_id:
            p.update(last_run=time.time(), last_matched=matched, last_new=new)
    store.write_json(PRESETS_FILE, presets, indent=2)


def save_preset(name, params):
    """Create a preset, or overwrite the one with the same name."""
    presets = load_presets()
    name = name.strip()[:60]
    for p in presets:
        if p["name"].lower() == name.lower():
            p["name"], p["params"] = name, params
            p.pop("last_new", None)
            break
    else:
        presets.append({"id": f"p{int(time.time() * 1000)}", "name": name, "params": params})
    store.write_json(PRESETS_FILE, presets, indent=2)
    return presets


def delete_preset(preset_id):
    presets = [p for p in load_presets() if p["id"] != preset_id]
    store.write_json(PRESETS_FILE, presets, indent=2)
    return presets


def saved_search_exists():
    return SEARCH_FILE.exists()


def save_search(p):
    store.write_json(SEARCH_FILE, p, indent=2)


def _norm(s):
    return query.norm(s)


_known = {"at": 0, "names": set()}


def known_companies():
    """Cleaned names of companies we can recognise in a query without a cue word (cached for an hour)."""
    if time.time() - _known["at"] < 3600 and _known["names"]:
        return _known["names"]
    names = set(query.ALIASES)
    names |= {query.clean_company(w[0]) for w in sources.WORKDAY}
    names |= {query.clean_company(s.replace("-", " ")) for s in company_slugs({"companies": []})}
    for label, url in sources.SIMPLIFY_URLS[:1]:
        for x in sources.get_json(url, ttl=6 * 3600) or []:
            names.add(query.clean_company(x.get("company_name", "")))
    names.discard("")
    _known.update(at=time.time(), names=names)
    return names


def normalise_params(p):
    parsed = query.parse(p.get("query", ""), p.get("companies", ""), known_companies())
    return {
        **p,
        "phrases": parsed["roles"],
        "role_rx": [query.phrase_regexes(ph) for ph in parsed["roles"]],
        "companies": parsed["companies"],
        "types": p.get("types") or [],
        "locations": [_norm(x.strip()) for x in re.split(r"[,;]", p.get("location", "")) if x.strip()],
        "season": (p.get("season") or "").capitalize(),
        "start_year": int(p.get("start_year") or 0),
        "require_start": bool(p.get("require_start")),
        "hidden": {query.clean_company(n) for n in load_hidden()},
        "country_codes": sorted({c for c in (p.get("countries") or []) if c in countries.CODES}),
        "home": load_settings().get("home_country", ""),
        "visa": p.get("visa") or "all",
        "exclude_rx": [re.compile(w) for w in (query.word_pattern(x) for x in re.split(r"[,;\n]", p.get("exclude", "")) if x.strip())],
        "hide_phd": bool(p.get("hide_phd")),
    }


def _all_match(regexes, text):
    return all(r.search(text) for r in regexes)


def where(j):
    """Countries of a job (computed once): extra.countries = on-site, extra.remote_countries = remote limits."""
    ex = j["extra"]
    if "loc" not in ex:
        info = countries.locate(j["location"])
        ex["countries"] = sorted(set(ex.get("countries") or info["countries"]))
        ex["remote_countries"] = info["remote_countries"]
        if info["remote"]:
            j["remote"] = True
        if j["remote"] and not ex["remote_countries"] and ex["countries"] and not countries.WORLDWIDE.search(j["location"]):
            ex["remote_countries"] = list(ex["countries"])  # remote, but in a stated place: remote within that country
        ex["loc"] = 1
    return ex


def score_job(j, params):
    """Relevance score, or None when the job does not fit the parameters (season is checked later)."""
    if params["types"] and j["type"] not in params["types"]:
        return None
    if params["hidden"] and query.clean_company(j["company"]) in params["hidden"]:
        return None
    if params["companies"] and not query.company_matches(j["company"], params["companies"]):
        return None
    title_n = _norm(j["title"])
    if params["hide_phd"] and re.search(r"\bph\.? ?d\b|doctoral|doctorate", title_n):
        return None
    if any(rx.search(title_n) for rx in params["exclude_rx"]):
        return None
    if params["country_codes"]:
        ex = where(j)
        chosen = set(params["country_codes"])
        on_site = bool(set(ex["countries"]) & chosen)
        remote_ok = False
        if j["remote"] and params["remote"] != "office":
            rc = set(ex.get("remote_countries") or [])
            remote_ok = (not rc) or bool(rc & chosen) or bool(params["home"] and params["home"] in rc)
        if not (on_site or remote_ok):
            return None
    if params["remote"] == "only" and not j["remote"]:
        return None
    if params["remote"] == "office" and j["remote"]:
        return None
    if params["locations"]:
        loc = _norm(j["location"])
        in_loc = any(l in loc for l in params["locations"])
        if not in_loc and not (j["remote"] and params["remote"] != "office"):
            return None
    days = int(params.get("posted_days") or 0)
    recent = 0
    if j["posted_at"]:
        d = None
        for parse in (lambda v: dt.datetime.fromisoformat(v.replace("Z", "+00:00")),
                      lambda v: dt.datetime.strptime(v[:25], "%a, %d %b %Y %H:%M:%S")):
            try:
                d = parse(str(j["posted_at"]))
                break
            except ValueError:
                continue
        if d:
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            age = (dt.datetime.now(dt.timezone.utc) - d).days
            if days and age > days:
                return None
            recent = 1 if age <= 7 else 0
    score = float(recent)
    if params["role_rx"]:
        title, tags, desc = _norm(j["title"]), _norm(" ".join(j["tags"])), _norm(j["description"])
        hit = 0.0
        why = ""
        for ph, rx in zip(params["phrases"], params["role_rx"]):
            if _all_match(rx, title):
                hit += 5
                why = why or f"“{ph}” appears in the title"
            elif _all_match(rx, tags):
                hit += 3
                why = why or f"“{ph}” is one of its tags"
            elif _all_match(rx, desc):
                hit += 1
                why = why or f"“{ph}” is mentioned in the description"
        if hit == 0:
            return None
        score += hit
        j["extra"]["why"] = why
    return score


def _season_over(start, today):
    """True when the season of this start term has already ended."""
    y = start["year"]
    if not y:
        return False
    end = {"Summer": dt.date(y, 9, 1), "Fall": dt.date(y, 12, 31), "Winter": dt.date(y + 1, 3, 1),
           "Spring": dt.date(y, 6, 1)}[start["season"]]
    return end < today


def season_ok(j, params):
    """Start-time filter; only internships have a start time to check."""
    if j["type"] == "internship" and j["starts"] and all(_season_over(s, dt.date.today()) for s in j["starts"]):
        return False
    if j["type"] != "internship" or not (params["season"] or params["start_year"] or params["require_start"]):
        return True
    if not j["starts"]:
        return not params["require_start"]
    return any((not params["season"] or s["season"] == params["season"])
               and (not params["start_year"] or s["year"] in (None, params["start_year"])) for s in j["starts"])


STEPS = [("sources", "Job platforms and career sites"), ("boards", "Company career boards"),
         ("match", "Matching your criteria"), ("read", "Reading job details"),
         ("verify", "Checking that postings are still open"),
         ("translate", "Translating to English"), ("save", "Saving results")]


def _step(key, status=None, detail=None, done=None, total=None):
    """Update one stage of the progress list shown in the UI (pending | active | done | skipped)."""
    with _state_lock:
        for st in state["steps"]:
            if st["key"] == key:
                if status:
                    st["status"] = status
                if detail is not None:
                    st["detail"] = detail
                if done is not None:
                    st["done"] = done
                if total is not None:
                    st["total"] = total


def _log(msg):
    with _state_lock:
        state["phase"] = msg
        state["log"].append(f"{dt.datetime.now():%H:%M:%S}  {msg}")
        state["log"] = state["log"][-60:]


def company_slugs(settings):
    seeds = [l.strip().lower() for l in SEED_FILE.read_text().splitlines() if l.strip() and not l.startswith("#")] \
        if SEED_FILE.exists() else []
    extra = [re.sub(r"[^a-z0-9_.-]", "", c.lower()) for c in settings.get("companies", [])]
    return list(dict.fromkeys(seeds + [e for e in extra if e]))


def guess_slugs(companies):
    out = []
    for c in companies:
        for term in query.company_terms(c) or [query.clean_company(c)]:
            words = term.split()
            out += ["".join(words), "-".join(words), words[0] if words else ""]
    return [s for s in dict.fromkeys(out) if s]


def _merge(old, new):
    """Same posting found twice: keep the auto-apply-capable copy and fill gaps from the other."""
    base, other = (new, old) if (new["ats"] and not old["ats"]) else (old, new)
    for k in ("description", "starts", "start_label", "duration", "posted_at", "salary"):
        if not base[k] and other[k]:
            base[k] = other[k]
    base["extra"] = {**other["extra"], **base["extra"]}
    return base


_TITLE_NOISE = re.compile(r"\b(summer|fall|autumn|winter|spring|20\d\d|intern(ship)?s?|stage|praktikum|working student|werkstudent|"
                          r"m ?/ ?[fwd] ?/ ?[dxwf]|f ?/ ?m ?/ ?[dx]|gn|all genders|new|for|the|a|and|at|in|program|programme|early career|"
                          r"undergraduate|graduate|student|bs ?/ ?ms|bs|ms|phd|remote|hybrid)\b")
_TITLE_SYN = (("swe", "software engineer"), ("sde", "software development engineer"), ("software engineering", "software engineer"),
              ("software developer", "software engineer"), ("developer", "engineer"), ("dev", "engineer"))


def core_title(title):
    """A title reduced to what identifies the role, so 'SWE Intern, Summer 2027' and
    'Software Engineer Intern (m/f/d)' are recognised as the same posting."""
    t = _norm(re.sub(r"\(.*?\)|\[.*?\]", " ", title))
    t = _TITLE_NOISE.sub(" ", t)
    for a, b in _TITLE_SYN:
        t = re.sub(rf"\b{a}\b", b, t)
    return " ".join(sorted(set(t.split())))


def _group_locations(ranked):
    """One card per role: the same title at the same company in several places becomes a single entry
    listing every location. The group keeps the smallest id so it stays stable between searches."""
    groups, order = {}, []
    for j, s in ranked:
        key = (query.clean_company(j["company"]), core_title(j["title"])) if j["company"] else (j["id"],)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((j, s))
    out = []
    for key in order:
        members = groups[key]
        leader, score = min(members, key=lambda m: m[0]["id"])
        score = max(s for _, s in members)
        variants, seen = [], set()
        for j, _ in members:
            loc = j["location"] or "Location not listed"
            if loc not in seen:
                seen.add(loc)
                variants.append({"location": loc, "url": j["url"]})
        if len(variants) > 1:
            leader["extra"]["countries"] = sorted({c for j, _ in members for c in j["extra"].get("countries", [])})
            leader["extra"]["remote_countries"] = sorted({c for j, _ in members for c in j["extra"].get("remote_countries", [])})
            leader["extra"]["variants"] = variants
            shown = ", ".join(v["location"] for v in variants[:2])
            leader["location"] = shown + (f" +{len(variants) - 2} more" if len(variants) > 2 else "")
            leader["remote"] = any(j["remote"] for j, _ in members)
        out.append((leader, score))
    return out


def _refresh_start(j):
    if j["type"] == "internship" and not j["starts"]:
        from .classify import extract_start
        j["starts"], j["start_label"], j["duration"] = extract_start(j["title"], j["description"], "")


def _run(params, daily):
    settings = load_settings()
    started = time.time()
    all_jobs = []
    enabled = settings["sources"]
    targets = params["companies"]
    with _state_lock:
        state["interpreted"] = {"roles": params["phrases"], "companies": targets}

    def run_source(name):
        try:
            res = sources.AGGREGATORS[name](params, settings)
        except Exception as e:
            return name, [], f"{type(e).__name__}: {e}"
        return name, res, None

    names = []
    for n in sources.AGGREGATORS:
        if not enabled.get(n):
            continue
        only = sources.TARGETED.get(n)
        if only and targets and not any(query.company_matches(only[0], [t]) for t in targets):
            continue
        names.append(n)
    total_n = len(names)
    _log(f"Querying {total_n} job sources" + (f" for {', '.join(targets)}" if targets else ""))
    _step("sources", "active", f"0 of {total_n}", 0, total_n)
    done_n = 0

    def record(name, res, err):
        nonlocal done_n
        done_n += 1
        with _state_lock:
            state["per_source"][name] = {"read": len(res), "error": err}
        all_jobs.extend(res)
        _step("sources", detail=f"{done_n} of {total_n} · {len(all_jobs):,} postings", done=done_n)

    if "simplify" in names:  # first: its links reveal company boards that later steps can search directly
        names.remove("simplify")
        record(*run_source("simplify"))
        _, n_new = harvest.harvest(all_jobs)
        if n_new:
            _log(f"Discovered {n_new} new company boards from posting links")
    with ThreadPoolExecutor(8) as ex:
        for fut in as_completed([ex.submit(run_source, n) for n in names]):
            record(*fut.result())
    _step("sources", "done")
    _log(f"Sources done: {len(all_jobs)} postings read")

    boards_on = [b for b in sources.BOARDS if enabled.get(b)]
    if boards_on:
        if targets:  # a specific employer: try its likely board names only
            dead = {}
            slugs = guess_slugs(targets)
        else:
            try:
                dead = json.loads(BOARDS_FILE.read_text())
            except (OSError, ValueError):
                dead = {}
            slugs = company_slugs(settings)
        _step("boards", "active", "Starting", 0, 1)
        jobs, working = sources.crawl_boards(
            slugs, boards_on,
            lambda d, t, n: _step("boards", detail=f"{d:,} of {t:,} checked · {n:,} postings", done=d, total=t), dead,
            extra_pairs=[] if targets else harvest.pairs())
        harvest.harvest(jobs)
        _step("boards", "done")
        if not targets:
            store.write_json(BOARDS_FILE, dead)
        all_jobs.extend(jobs)
        with _state_lock:
            for b, found in working.items():
                if b in boards_on and (found or not targets):
                    state["per_source"][b] = {"read": len(found), "error": None, "unit": "companies"}
    else:
        _step("boards", "skipped")

    _step("match", "active", f"{len(all_jobs):,} postings")
    _log("Matching your parameters")
    best = {}
    for j in all_jobs:
        if not j["url"]:
            continue
        s = score_job(j, params)
        if s is None:
            continue
        old = best.get(j["id"])
        if old is None:
            best[j["id"]] = (j, s)
        else:
            best[j["id"]] = (_merge(old[0], j), max(old[1], s))
    cands = sorted(best.values(), key=lambda x: -x[1])[:MAX_RESULTS]

    _step("match", "done", f"{len(cands):,} candidates")
    need = [j for j, _ in cands if not j["description"] and (j["ats"] == "greenhouse" or j["extra"].get("workday"))][:400]
    if need:
        _log(f"Reading {len(need)} job descriptions")
        _step("read", "active", f"0 of {len(need)}", 0, len(need))
        counter = [0]

        def read_one(j):
            enrich.enrich(j) and _refresh_start(j)
            counter[0] += 1
            _step("read", detail=f"{counter[0]} of {len(need)}", done=counter[0])

        with ThreadPoolExecutor(16) as ex:
            list(ex.map(read_one, need))
        _step("read", "done")
    else:
        _step("read", "skipped")

    today = dt.date.today()
    ranked = []
    for j, s in cands:
        if not season_ok(j, params):
            continue
        deadline = extract_deadline(j["description"], today)
        if deadline:
            if deadline < today.isoformat():
                continue  # the posting says applications already closed
            j["extra"]["deadline"] = deadline
        if params["season"] and j["type"] == "internship" and j["starts"]:
            s += 2  # stated start matches the season wanted
        ranked.append((j, s))
    ranked.sort(key=lambda x: str(x[0]["posted_at"] or ""), reverse=True)
    ranked.sort(key=lambda x: -x[1])
    for j, _ in ranked:
        where(j)
    _step("verify", "active", "Starting", 0, 1)
    closed, checked = verify.drop_closed(
        [j for j, _ in ranked],
        lambda d, t, n: _step("verify", detail=f"{d} of {t} checked · {n} closed", done=d, total=t))
    ranked = [(j, s) for j, s in ranked if j["id"] not in closed]
    _step("verify", "done" if checked else "skipped", f"{len(closed)} closed postings removed" if checked else "")
    ranked = _group_locations(ranked)

    foreign = []
    for j, _ in ranked:
        if not j["lang"]:
            lang = translate.detect(f"{j['title']}. {j['description'][:600]}") or "en"
            j["lang"] = lang
            if lang != "en":
                foreign.append(j)
    if foreign:
        _log(f"Translating {len(foreign)} postings to English")
        _step("translate", "active", f"0 of {len(foreign)}", 0, len(foreign))
        deadline = time.time() + 150
        tcount = [0]

        def translate_one(j):
            ok = time.time() < deadline and translate.translate_job(j)
            tcount[0] += 1
            _step("translate", detail=f"{tcount[0]} of {len(foreign)}", done=tcount[0])
            return ok

        with ThreadPoolExecutor(2) as ex:
            list(ex.map(translate_one, foreign))
        retry_until = time.time() + 60  # the service throttles bursts: retry the failures one by one
        for j in [j for j in foreign if not j["orig_title"]]:
            if time.time() > retry_until or translate.cooling_down():
                break
            time.sleep(1.5)
            translate.translate_job(j)
        for j in foreign:
            _refresh_start(j)
    # postings still in another language (service busy) are translated when opened in the UI

    _step("translate", "done" if foreign else "skipped")

    kept = []
    for j, s in ranked:
        flags = eligibility.classify(j)
        eligibility.mark_uk_sponsor(j)
        flags = j["extra"]["flags"]
        if params["visa"] == "hide_blocked" and eligibility.is_blocked(flags):
            continue
        if params["visa"] == "offered" and not ({"visa_offered", "relocation", "uk_sponsor"} & set(flags)):
            continue
        if params["visa"] != "all" and {"visa_offered", "relocation"} & set(flags):
            s += 1.5  # the user cares about visas: surface the ones that help
        kept.append((j, s))
    ranked = sorted(kept, key=lambda x: -x[1])

    _step("save", "active")
    db.reset_results()
    new = db.upsert(ranked, started)
    _step("save", "done")
    record_source_health(ranked)
    with _state_lock:
        shown = db.counts()["results"]  # jobs you already applied to, saved or dismissed are not listed again
        state.update(matched=shown, hidden=len(ranked) - shown, new=new, finished=time.time())
    if state.get("preset_id"):
        update_preset_stats(state["preset_id"], shown, new)
    _log(f"Done: {state['matched']} matching opportunities, {new} new, {state['hidden']} already handled")


HEALTH_FILE = DATA / "source_stats.json"


def load_health():
    try:
        return json.loads(HEALTH_FILE.read_text())
    except (OSError, ValueError):
        return {}


def record_source_health(ranked):
    """Per source: what it returned, what survived into the results, and how long it has been failing."""
    kept = {}
    for j, _ in ranked:
        key = sources.LABEL_TO_KEY.get(j["source"])
        if key:
            kept[key] = kept.get(key, 0) + 1
    health = load_health()
    with _state_lock:
        per = dict(state["per_source"])
    for key, v in per.items():
        h = health.setdefault(key, {"streak": 0, "history": []})
        optional = key in ("adzuna", "jooble", "feeds")  # need a key or a feed URL: empty is normal
        failed = bool(v.get("error")) or (v.get("read", 0) == 0 and not v.get("unit") and not optional)
        h.update(at=time.time(), read=v.get("read", 0), unit=v.get("unit", "postings"), error=v.get("error"),
                 kept=kept.get(key, 0), streak=h["streak"] + 1 if failed else 0)
        h["history"] = (h["history"] + [[v.get("read", 0), kept.get(key, 0)]])[-10:]
    store.write_json(HEALTH_FILE, health)


def start_search(params, daily=False, preset_id=None):
    with _state_lock:
        if state["running"]:
            return False
        state.update(running=True, log=[], per_source={}, started=time.time(), finished=None,
                     error=None, matched=0, new=0, phase="Starting", interpreted=None, preset_id=preset_id,
                     steps=[{"key": k, "label": l, "status": "pending", "detail": "", "done": 0, "total": 0}
                            for k, l in STEPS])
    p = normalise_params(params)

    def worker():
        try:
            _run(p, daily)
        except Exception as e:
            with _state_lock:
                state["error"] = f"{type(e).__name__}: {e}"
        finally:
            with _state_lock:
                state["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return True
