"""Auto-apply for Greenhouse, Lever and Ashby postings using a real (headless) browser.

The filler reads every form field on the page, maps it to the user's profile, and only submits
when every required field has an answer. Anything it can't answer, or a captcha, turns into a
"manual" result with the reason, so the user gets the link instead of a half-sent application.
"""
import json
import queue
import re
import threading
import time
from pathlib import Path

from . import db, search, store

DATA = db.DATA
PROFILE_FILE = DATA / "profile.json"
RESUME_DIR = DATA / "resume"
SHOT_DIR = DATA / "apply"
RESUME_DIR.mkdir(exist_ok=True)
SHOT_DIR.mkdir(exist_ok=True)

# Questions that come up on most application forms. `match` is a regex tested against the form's
# question text; `kind` is "yesno" or "text". Answers live in profile["fixed"][key].
FIXED_QUESTIONS = [
    {"key": "work_auth", "group": "Eligibility", "kind": "yesno", "label": "Legally authorized to work in the job's country",
     "match": r"authori[sz]ed to work|legally (eligible|authori[sz]ed)|work permit|right to work|eligible to work"},
    {"key": "sponsorship", "group": "Eligibility", "kind": "yesno", "label": "Will need visa sponsorship",
     "match": r"sponsorship|require.{0,30}visa|visa.{0,30}(require|need)"},
    {"key": "over18", "group": "Eligibility", "kind": "yesno", "label": "At least 18 years old",
     "match": r"18 years|over 18|legal age|at least 18"},
    {"key": "citizenship", "group": "Eligibility", "kind": "text", "label": "Citizenship / nationality",
     "match": r"citizenship|nationality"},
    {"key": "country", "group": "Eligibility", "kind": "text", "label": "Country of residence",
     "match": r"^country( of residence)?\b|country you (live|reside)"},
    {"key": "relocate", "group": "Availability", "kind": "yesno", "label": "Willing to relocate",
     "match": r"relocat"},
    {"key": "onsite", "group": "Availability", "kind": "yesno", "label": "Able to work on-site / in office",
     "match": r"on-?site|in[- ]office|hybrid|work from (the )?office"},
    {"key": "start_date", "group": "Availability", "kind": "text", "label": "Earliest start date (e.g. June 2027)",
     "match": r"start date|when can you start|available to start|earliest.{0,20}start|availability date"},
    {"key": "duration", "group": "Availability", "kind": "text", "label": "Internship availability (e.g. 12 weeks, June to August)",
     "match": r"how long|duration|availab\w+ (for|during)|weeks"},
    {"key": "salary", "group": "Availability", "kind": "text", "label": "Salary / stipend expectation",
     "match": r"salary|compensation|pay expectation|stipend|hourly rate"},
    {"key": "student", "group": "Education", "kind": "yesno", "label": "Currently enrolled student",
     "match": r"currently (a )?(student|enrolled)|enrolled in|are you a student"},
    {"key": "degree", "group": "Education", "kind": "text", "label": "Degree you are pursuing (e.g. BSc Computer Science)",
     "match": r"degree|level of education|highest (level|education)"},
    {"key": "major", "group": "Education", "kind": "text", "label": "Field of study / major",
     "match": r"major|field of study|discipline|concentration"},
    {"key": "grad_date", "group": "Education", "kind": "text", "label": "Expected graduation date (e.g. 06/2028)",
     "match": r"graduation|graduate"},
    {"key": "gpa", "group": "Education", "kind": "text", "label": "GPA / grade", "match": r"\bgpa\b|grade point"},
    {"key": "languages", "group": "About you", "kind": "text", "label": "Languages spoken",
     "match": r"languages?( you)? (speak|spoken)|^languages?$"},
    {"key": "years_exp", "group": "About you", "kind": "text", "label": "Years of relevant experience",
     "match": r"years of (relevant |work |professional )?experience"},
    {"key": "pronouns", "group": "About you", "kind": "text", "label": "Pronouns", "match": r"pronoun"},
    {"key": "hear", "group": "About you", "kind": "text", "label": "How did you hear about the job", "default": "Job board",
     "match": r"hear about|how did you find|referral source|where did you (hear|find)|source of (application|referral)"},
    {"key": "referred", "group": "About you", "kind": "yesno", "label": "Referred by an employee", "default": "No",
     "match": r"referred by|employee referral|know anyone (at|who)"},
    {"key": "prev_employed", "group": "About you", "kind": "yesno", "label": "Previously worked or applied at this company",
     "default": "No", "match": r"previously (worked|employed|applied)|former employee|worked (for|at) .{0,40} before"},
]
FIXED_BY_KEY = {q["key"]: q for q in FIXED_QUESTIONS}

DEFAULT_PROFILE = {
    "first_name": "", "last_name": "", "email": "", "phone": "", "location": "",
    "linkedin": "", "github": "", "website": "", "current_company": "", "school": "",
    "resume": "",
    "cover_letter": "Dear hiring team,\n\nI am excited to apply for the {title} position at {company}. "
                    "My background and motivation make this role a strong fit, and I would welcome the "
                    "chance to contribute.\n\nBest regards,\n{first_name} {last_name}",
    "fixed": {},     # answers to FIXED_QUESTIONS, by key
    "custom": [],    # [{"match": "text the question contains", "answer": "..."}] added by the user
}
UNANSWERED_FILE = DATA / "unanswered.json"

FIELD_JS = r"""
() => {
  const txt = e => (e && e.textContent || '').replace(/\s+/g, ' ').trim();
  const labelOf = el => {
    const parts = [];
    if (el.getAttribute('aria-label')) parts.push(el.getAttribute('aria-label'));
    (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).forEach(id => parts.push(txt(document.getElementById(id))));
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) parts.push(txt(l)); }
    const wl = el.closest('label'); if (wl && el.type !== 'radio' && el.type !== 'checkbox') parts.push(txt(wl));
    if (!parts.join('').trim()) {
      let p = el.parentElement;
      for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
        const l = p.querySelector(':scope > label, :scope > legend, :scope > [class*="label"], :scope > div > label');
        if (l && txt(l)) { parts.push(txt(l)); break; }
      }
    }
    if (!parts.join('').trim()) parts.push(el.placeholder || el.name || '');
    return parts.join(' ').trim();
  };
  const groupLabel = el => {
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return txt(lg); }
    let p = el.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      const l = p.querySelector(':scope > label, :scope > legend, :scope > [class*="label"], :scope > [class*="question"]');
      if (l && !l.contains(el) && txt(l)) return txt(l);
    }
    return el.name || '';
  };
  const out = []; const seenGroups = {}; let n = 0;
  document.querySelectorAll('input, textarea, select').forEach(el => {
    const t = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(t)) return;
    if (el.closest('[aria-hidden="true"]') && t !== 'file') return;
    const r = el.getBoundingClientRect();
    const visible = (r.width > 0 && r.height > 0) || t === 'file' || t === 'checkbox' || t === 'radio';
    if (!visible || el.disabled) return;
    if (el.classList.contains('g-recaptcha-response') || /captcha/i.test(el.name || '')) return;
    const idx = String(n++); el.setAttribute('data-rt', idx);
    let f = {idx, tag: el.tagName.toLowerCase(), type: t, name: el.name || '', role: el.getAttribute('role') || '',
             required: el.required || el.getAttribute('aria-required') === 'true', value: el.value || ''};
    if (t === 'radio') {
      const g = el.name || ('r' + idx);
      if (seenGroups[g] !== undefined) { out[seenGroups[g]].options.push({idx, text: txt(el.closest('label')) || el.value}); return; }
      seenGroups[g] = out.length;
      f.label = groupLabel(el); f.options = [{idx, text: txt(el.closest('label')) || el.value}];
    } else {
      f.label = labelOf(el);
      if (t === 'checkbox') f.label = txt(el.closest('label')) || f.label;
    }
    if (el.tagName === 'SELECT') f.options = [...el.options].map(o => ({text: o.text.trim(), value: o.value})).filter(o => o.value !== '');
    if (/\*|✱/.test(f.label)) f.required = true;
    f.label = f.label.replace(/[*✱]/g, '').trim();
    out.push(f);
  });
  return out;
}
"""

RULES = [
    ("first_name", r"first name|given name|prénom|vorname|forename"),
    ("last_name", r"last name|family name|surname|nom de famille|nachname"),
    ("email", r"e-?mail"),
    ("phone", r"phone|mobile|telephone|téléphone|\btel\b"),
    ("linkedin", r"linkedin"),
    ("github", r"github"),
    ("website", r"website|portfolio|personal (site|url|page)|^url$|other (link|url)|\blink\b"),
    ("current_company", r"current (company|employer)|employer|company name"),
    ("school", r"school|university|college|institution"),
    ("location", r"^location|current location|\bcity\b|where are you (based|located)|\baddress\b|location \(city\)"),
    ("full_name", r"^(full |your |legal |preferred )?name\b|^name$"),
]
EEO_RE = re.compile(r"gender|race|ethnic|veteran|disabilit|hispanic|latino|sexual orientation|transgender|pronoun|lgbt", re.I)
DECLINE_RE = re.compile(r"decline|prefer not|do not wish|don't wish|not to (say|answer|disclose)|rather not", re.I)
CONSENT_RE = re.compile(r"agree|consent|acknowledge|privacy|terms|certify|confirm|i have read|gdpr|data processing", re.I)
SUCCESS_RE = re.compile(r"thank you for (applying|your application|your interest)|application (has been |was )?(submitted|received|sent)|"
                        r"successfully submitted|we(’|')?ve received your application|application complete", re.I)


def load_profile():
    try:
        raw = json.loads(PROFILE_FILE.read_text())
    except (OSError, ValueError):
        raw = {}
    p = {**DEFAULT_PROFILE, **raw}
    if "answers" in raw and not raw.get("custom"):  # first-version profiles
        p["custom"] = [a for a in raw["answers"] if a.get("answer")]
    p["fixed"] = {**{q["key"]: q["default"] for q in FIXED_QUESTIONS if q.get("default")}, **p.get("fixed", {})}
    return p


def load_unanswered():
    try:
        return json.loads(UNANSWERED_FILE.read_text())
    except (OSError, ValueError):
        return {}


def record_unanswered(labels):
    data = load_unanswered()
    for l in labels:
        l = l.strip()[:160]
        if l:
            data[l] = data.get(l, 0) + 1
    store.write_json(UNANSWERED_FILE, data, indent=1)


def forget_unanswered(label):
    data = load_unanswered()
    data.pop(label, None)
    store.write_json(UNANSWERED_FILE, data, indent=1)


def save_profile(p):
    store.write_json(PROFILE_FILE, p, indent=2)


def missing_profile_fields(p):
    need = ["first_name", "last_name", "email", "phone", "resume"]
    missing = [k for k in need if not p.get(k)]
    if p.get("resume") and not Path(p["resume"]).exists():
        missing.append("resume")
    return missing


def apply_url_for(job):
    ref = job["ats_ref"] or {}
    slug, jid = ref.get("slug"), ref.get("job_id")
    if job["ats"] == "greenhouse":
        return f"https://job-boards.greenhouse.io/{slug}/jobs/{jid}"
    if job["ats"] == "lever":
        return f"https://jobs.lever.co/{slug}/{jid}/apply"
    if job["ats"] == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}/{jid}/application"
    return job["apply_url"]


def _pick(options, answer):
    """Choose the option whose text best matches `answer` (indices into options)."""
    a = answer.strip().lower()
    for i, o in enumerate(options):
        if o["text"].strip().lower() == a:
            return i
    for i, o in enumerate(options):
        t = o["text"].strip().lower()
        if t.startswith(a) or (len(a) > 2 and a in t):
            return i
    return None


def _decide(f, profile, job):
    """-> ('fill', value) | ('skip', None) | ('unresolved', reason)"""
    label = f["label"].lower()
    t = f["type"]
    values = {**{k: profile.get(k, "") for k in ("first_name", "last_name", "email", "phone", "location",
              "linkedin", "github", "website", "current_company", "school")},
              "full_name": f"{profile['first_name']} {profile['last_name']}".strip()}

    if t == "file":
        if re.search(r"cover", label):
            return ("skip", None) if not f["required"] else ("unresolved", "cover letter file")
        if re.search(r"resume|cv|curriculum|attach", label) or not label:
            return ("fill", profile["resume"])
        return ("skip", None) if not f["required"] else ("unresolved", f["label"])

    for rule in profile.get("custom", []):  # the user's own rules win over the built-in ones
        if rule.get("answer") and rule.get("match") and re.search(rule["match"], f["label"], re.I):
            return "fill", rule["answer"]
    for q in FIXED_QUESTIONS:
        ans = profile.get("fixed", {}).get(q["key"])
        if ans and re.search(q["match"], f["label"], re.I):
            return "fill", ans

    if EEO_RE.search(label):
        opts = f.get("options") or []
        for o in opts:
            if DECLINE_RE.search(o["text"]):
                return "fill", o["text"]
        return ("skip", None) if not f["required"] else ("unresolved", f["label"])

    if t == "checkbox":
        if CONSENT_RE.search(label) and f["required"] or (CONSENT_RE.search(label) and len(label) > 40):
            return "fill", True
        return ("skip", None) if not f["required"] else ("unresolved", f["label"])

    if "cover letter" in label or "message to" in label or "why do you want" in label:
        if t in ("textarea", "text"):
            return "fill", profile["cover_letter"].format(title=job["title"], company=job["company"],
                                                         first_name=profile["first_name"], last_name=profile["last_name"])
    for key, pat in RULES:
        if re.search(pat, label):
            v = values.get(key, "")
            if v:
                return "fill", v
            return ("skip", None) if not f["required"] else ("unresolved", f["label"])
    return ("skip", None) if not f["required"] else ("unresolved", f["label"] or f["name"])


def _fill_field(page, f, kind, value):
    sel = f'[data-rt="{f["idx"]}"]'
    el = page.locator(sel)
    t = f["type"]
    if t == "file":
        el.set_input_files(value)
    elif t == "checkbox":
        el.check(force=True)
    elif t == "radio":
        i = _pick(f["options"], value)
        if i is None:
            raise ValueError(f"no option matching '{value}'")
        page.locator(f'[data-rt="{f["options"][i]["idx"]}"]').check(force=True)
    elif f["tag"] == "select":
        opts = f.get("options", [])
        i = _pick(opts, value)
        if i is None:
            raise ValueError(f"no option matching '{value}'")
        el.select_option(value=opts[i]["value"])
    elif f["role"] == "combobox":
        el.click()
        el.fill(value)
        page.wait_for_timeout(500)
        el.press("Enter")
    else:
        el.fill(str(value))


def _captcha_present(page):
    return page.locator("iframe[src*='hcaptcha'], iframe[src*='recaptcha/api2/bframe'], .h-captcha, .g-recaptcha").count() > 0


def fill_and_submit(page, job, profile, dry_run=False):
    """-> (status, message) with status in applied | manual | dry_run"""
    url = apply_url_for(job)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)
    if page.locator("input[type=file]").count() == 0 and page.locator("form input, form textarea").count() == 0:
        return "manual", "Application form not found on the page"
    fields = page.evaluate(FIELD_JS)
    unresolved, errors = [], []
    for f in fields:
        action, value = _decide(f, profile, job)
        if action == "unresolved":
            unresolved.append(value)
        elif action == "fill":
            try:
                _fill_field(page, f, action, value)
            except Exception as e:
                if f["required"]:
                    errors.append(f"{f['label'] or f['name']}: {str(e).splitlines()[0][:80]}")
    if unresolved or errors:
        record_unanswered(unresolved)
        return "manual", "Needs your input: " + "; ".join(dict.fromkeys(unresolved + errors))[:300]
    shot = SHOT_DIR / f"{job['id']}.png"
    page.screenshot(path=str(shot), full_page=True)
    if dry_run:
        return "dry_run", "Dry run: form filled, not submitted (see screenshot)"
    btn = page.locator("button[type=submit], input[type=submit]").last
    if btn.count() == 0:
        btn = page.get_by_role("button", name=re.compile(r"^(submit|apply|send)", re.I)).last
    if btn.count() == 0:
        return "manual", "Submit button not found"
    btn.click()
    for _ in range(24):
        page.wait_for_timeout(1000)
        try:
            body = page.inner_text("body")
        except Exception:
            body = ""
        if SUCCESS_RE.search(body) or re.search(r"confirmation|thanks|submitted", page.url, re.I):
            page.screenshot(path=str(SHOT_DIR / f"{job['id']}_done.png"))
            return "applied", "Submitted and confirmed by the site"
    reason = "captcha challenge" if _captcha_present(page) else "no confirmation page after submit"
    page.screenshot(path=str(SHOT_DIR / f"{job['id']}_after.png"))
    return "manual", f"Not confirmed ({reason}). Check the link to be sure."


# ---------------------------------------------------------------- pre-flight check

# Fixed questions whose absence stops many forms; worth flagging before a batch.
IMPORTANT_FIXED = ["work_auth", "sponsorship", "student", "start_date"]


def install_command():
    """Command that downloads Chromium. Uses Playwright's own bundled driver, so it also works in the packaged app
    (where sys.executable is the app itself, not Python)."""
    from playwright._impl._driver import compute_driver_executable
    node, cli = compute_driver_executable()
    return [str(node), str(cli), "install", "chromium"]


def browser_installed():
    """True when Playwright's Chromium is available (auto-apply needs it; searching does not)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            exe = Path(pw.chromium.executable_path)
            browser_installed.error = "" if exe.exists() else f"expected at {exe}"
            return exe.exists()
    except Exception as e:
        browser_installed.error = f"{type(e).__name__}: {e}"[:300]
        return False


_install = {"state": "idle", "message": ""}


def install_browser():
    """Download Chromium for Playwright in the background (about 150 MB, once)."""
    import subprocess
    from playwright._impl._driver import get_driver_env
    if _install["state"] == "running":
        return _install

    def work():
        _install.update(state="running", message="Downloading the browser, this takes a minute or two...")
        try:
            r = subprocess.run(install_command(), capture_output=True, text=True, timeout=900,
                               env={**__import__("os").environ, **get_driver_env()})
            ok = r.returncode == 0
            _install.update(state="done" if ok else "error",
                            message="Browser ready." if ok else (r.stderr or r.stdout or "install failed")[-300:])
        except Exception as e:
            _install.update(state="error", message=f"{type(e).__name__}: {e}"[:300])
    threading.Thread(target=work, daemon=True).start()
    return _install


def install_status():
    return dict(_install)


def check(job_ids):
    """Pre-flight review for a batch. Nothing is submitted or changed."""
    profile = load_profile()
    settings = search.load_settings()
    missing = missing_profile_fields(profile)
    resume_ok = bool(profile.get("resume")) and Path(profile["resume"]).exists()
    unset = [FIXED_BY_KEY[k]["label"] for k in IMPORTANT_FIXED if not profile["fixed"].get(k)]
    jobs = [j for j in (db.get(i) for i in job_ids) if j]
    per_company = {}
    for j in jobs:
        per_company[j["company"].lower()] = per_company.get(j["company"].lower(), 0) + 1
    applied_companies = {j["company"].lower() for j in db.list_jobs("applied")}
    rows = []
    for j in jobs:
        warnings, blocked = [], False
        if j["status"] == "applied":
            warnings.append("You already applied to this one")
            blocked = True
        elif j["company"].lower() in applied_companies:
            warnings.append("You already applied to another role at this company")
        if per_company[j["company"].lower()] > 1:
            warnings.append(f"{per_company[j['company'].lower()]} roles selected at this company")
        if j["status"] == "manual" and j["note"]:
            warnings.append("Earlier attempt needed you: " + j["note"][:90])
        if not j["auto"]:
            warnings.append("Can't be automated: you will get the link")
        rows.append({"id": j["id"], "title": j["title"], "company": j["company"], "auto": j["auto"],
                     "ats": j["ats"], "blocked": blocked, "warnings": warnings})
    return {
        "profile_missing": missing, "resume_ok": resume_ok, "questions_unset": unset,
        "cover_letter": bool(profile.get("cover_letter", "").strip()),
        "dry_run": bool(settings.get("dry_run")), "rows": rows,
        "auto_enabled": bool(settings.get("auto_apply")), "browser_ok": browser_installed(),
        "auto_count": sum(1 for r in rows if r["auto"] and not r["blocked"]),
    }


# ---------------------------------------------------------------- queue / worker

apply_state = {}   # job_id -> {"state": queued|running|done, "status", "message"}
_q = queue.Queue()
_worker_started = False
_lock = threading.Lock()


def _process(job_id):
    from playwright.sync_api import sync_playwright
    job = db.get(job_id)
    settings = search.load_settings()
    profile = load_profile()
    apply_state[job_id].update(state="running")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not settings.get("headed", False))
            ctx = browser.new_context(viewport={"width": 1280, "height": 1600},
                                      user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                                 "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
            page = ctx.new_page()
            try:
                status, msg = fill_and_submit(page, job, profile, settings.get("dry_run", False))
            finally:
                browser.close()
    except Exception as e:
        status, msg = "manual", f"Automation error: {type(e).__name__}: {str(e).splitlines()[0][:150]}"
    db_status = "applied" if status == "applied" else "manual"
    db.set_status(job_id, db_status, msg)
    apply_state[job_id].update(state="done", status=status, message=msg)


def _worker():
    while True:
        job_id = _q.get()
        try:
            _process(job_id)
            time.sleep(4)  # one form at a time, with a pause: polite to the employers' sites
        except Exception as e:
            apply_state[job_id].update(state="done", status="manual", message=str(e)[:150])
        _q.task_done()


def enqueue(job_ids):
    """Queue auto-apply for jobs; non-automatable jobs are returned as manual immediately."""
    global _worker_started
    profile = load_profile()
    missing = missing_profile_fields(profile)
    if missing:
        return {"error": "Profile incomplete: " + ", ".join(missing)}
    automatable = any(j and j["ats"] for j in (db.get(i) for i in job_ids))
    if automatable and not search.load_settings().get("auto_apply"):
        return {"error": "Auto-apply is switched off. Turn it on in Settings first."}
    if automatable and not browser_installed():
        return {"error": "The apply browser isn't installed yet. Use Install browser in the review window."}
    with _lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True).start()
            _worker_started = True
    result = {}
    for jid in job_ids:
        job = db.get(jid)
        if not job:
            continue
        if not job["ats"]:
            db.set_status(jid, "manual", "This site can't be automated; open the link to apply")
            result[jid] = "manual"
            continue
        if apply_state.get(jid, {}).get("state") in ("queued", "running"):
            continue
        apply_state[jid] = {"state": "queued", "status": None, "message": ""}
        _q.put(jid)
        result[jid] = "queued"
    return {"queued": result}
