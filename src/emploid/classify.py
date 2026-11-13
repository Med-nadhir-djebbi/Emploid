"""Job normalisation helpers: type detection, ATS detection, text cleaning."""
import hashlib
import html
import re

INTERN_RE = re.compile(
    r"\b(intern(ship)?s?|stagiaires?|pfe|praktikum|praktikant(in)?|werkstudent(in)?|working student|"
    r"trainee|apprentice(ship)?|alternance|alternant|co-?op|summer analyst|stage)\b", re.I)
EARLY_STAGE_RE = re.compile(r"\b(early|late|growth|seed|pre-seed|series [a-z]|next|fast|startup)[- ]stage\b", re.I)
PART_RE = re.compile(r"\b(part[- ]?time|temps partiel|teilzeit|mini[- ]?job|half[- ]?time|20 hours|hours per week)\b", re.I)
FREELANCE_RE = re.compile(r"\b(freelance|freelancer|contractor|contract basis|gig)\b", re.I)

ATS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([^/?#]+)/jobs/(\d+)")),
    ("lever", re.compile(r"jobs(?:\.eu)?\.lever\.co/([^/?#]+)/([0-9a-f-]{36})")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})")),
]


def detect_ats(url):
    for name, pat in ATS_PATTERNS:
        m = pat.search(url or "")
        if m:
            return name, m.group(1), m.group(2)
    return None, None, None


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def detect_type(title, structured="", description=""):
    """Return internship | part_time | freelance | full_time."""
    title = title or ""
    structured = (structured or "").lower().replace("_", " ").replace("-", " ")
    if re.search(r"intern|apprentic|trainee|co op", structured):
        return "internship"
    if "part" in structured:
        return "part_time"
    if re.search(r"freelanc|contract", structured) and not re.search(r"full", structured):
        return "freelance"
    if INTERN_RE.search(EARLY_STAGE_RE.sub("", title)):
        return "internship"
    if PART_RE.search(title):
        return "part_time"
    if FREELANCE_RE.search(title):
        return "freelance"
    head = (description or "")[:500]
    if PART_RE.search(head):
        return "part_time"
    return "full_time"



SEASON_WORDS = {
    "summer": "Summer", "été": "Summer", "ete": "Summer", "sommer": "Summer", "verano": "Summer",
    "estate": "Summer", "estivo": "Summer", "verão": "Summer", "zomer": "Summer",
    "fall": "Fall", "autumn": "Fall", "automne": "Fall", "herbst": "Fall", "otoño": "Fall", "autunno": "Fall",
    "winter": "Winter", "hiver": "Winter", "invierno": "Winter", "inverno": "Winter",
    "spring": "Spring", "printemps": "Spring", "frühling": "Spring", "fruhling": "Spring", "primavera": "Spring",
}
_SEASON_ALT = "|".join(sorted(SEASON_WORDS, key=len, reverse=True))
SEASON_YEAR_RE = re.compile(rf"\b({_SEASON_ALT})\b[\s,'’/-]*((?:20)?\d\d)?\b|\b(20\d\d)[\s,\-–—/]+({_SEASON_ALT})\b", re.I)
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12, "janv": 1, "févr": 2, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
          "juil": 7, "août": 8, "aout": 8, "sept": 9, "déc": 12, "januar": 1, "februar": 2, "märz": 3, "marz": 3,
          "juni": 6, "juli": 7, "oktober": 10, "dezember": 12}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September",
                "October", "November", "December"]
START_MONTH_RE = re.compile(
    rf"(?:start(?:ing|s)?(?: date)?|begin(?:ning|s)?|commenc\w+|available from|from|d[ée]but|beginn|(?:[àa] )?partir de|d[èe]s|\bab)\W{{0,12}}"
    rf"(?:(?:[àa] partir de |partir de |ab |d[èe]s |from |in |on |at |the |le |im |en )*)(?:early |mid[- ]?|late |end of |beginning of |d[ée]but )?"
    rf"\b({_MONTH_ALT})[a-zé]*\.?\s*(?:\d{{1,2}}(?!\d)(?:st|nd|rd|th)?,?\s*)?(20\d\d)?", re.I)
MONTH_RANGE_RE = re.compile(
    rf"\b({_MONTH_ALT})[a-zé]*\.?\s*(?:[-–—]|to|bis|à|au)\s*({_MONTH_ALT})[a-zé]*\.?\s*(20\d\d)?", re.I)
DURATION_RE = re.compile(
    r"(\d{1,2})(?:\s*(?:[-–—]|to|bis|à)\s*(\d{1,2}))?[\s-]*(weeks?|months?|mois|monate?|semaines|wochen)\b"
    r"(?!\s*(?:of|d['’])?\s*(?:relevant |work |professional |prior |hands-on |industry )?(?:experience|exp\b|expérience|erfahrung))", re.I)
DURATION_CTX = re.compile(r"intern|program|duration|period|lasting|last(?:s|ing)|term|placement|stage|praktikum|dur[ée]e|commitment|full[- ]time for", re.I)


def month_season(m):
    return "Summer" if m in (6, 7, 8) else "Fall" if m in (9, 10, 11) else "Winter" if m in (12, 1, 2) else "Spring"


def _year(y):
    if not y:
        return None
    y = int(y)
    return 2000 + y if y < 100 else y


def parse_terms(text):
    """'Summer 2027, Fall 2027' -> [{'season': 'Summer', 'year': 2027}, ...]"""
    out = []
    for m in SEASON_YEAR_RE.finditer(text or ""):
        word = m.group(1) or m.group(4)
        year = _year(m.group(2) or m.group(3))
        item = {"season": SEASON_WORDS[word.lower()], "year": year}
        if item not in out:
            out.append(item)
    return out


def extract_start(title, description, hint=""):
    """Work out when a position starts. Returns (starts, label, duration)
    starts: [{'season','year'}]; label e.g. 'Summer 2027' or 'Starts June 2027'."""
    starts = parse_terms(hint)
    label = ""
    text = f"{title}\n{(description or '')[:6000]}"
    if not starts:
        starts = parse_terms(title)
    if not starts:
        # season words in the body count only when close to an internship/start cue (avoids "winter coat")
        for m in SEASON_YEAR_RE.finditer(text):
            ctx = text[max(0, m.start() - 60):m.end() + 60]
            if re.search(r"intern|start|begin|cohort|program|stage|praktik|term|semester", ctx, re.I) and (m.group(2) or m.group(3)):
                starts = parse_terms(m.group(0))
                break
    if not starts:
        m = START_MONTH_RE.search(text)
        if m:
            mo = MONTHS[m.group(1).lower()] if m.group(1).lower() in MONTHS else MONTHS.get(m.group(1).lower()[:3])
            if mo:
                year = _year(m.group(2))
                starts = [{"season": month_season(mo), "year": year}]
                label = f"Starts {_MONTH_NAMES[mo]}" + (f" {year}" if year else "")
        else:
            m = MONTH_RANGE_RE.search(text)
            if m and re.search(r"intern|stage|praktik|summer|program", text, re.I):
                mo = MONTHS.get(m.group(1).lower()) or MONTHS.get(m.group(1).lower()[:3])
                if mo:
                    year = _year(m.group(3))
                    starts = [{"season": month_season(mo), "year": year}]
                    label = f"{_MONTH_NAMES[mo]} to {_MONTH_NAMES[MONTHS.get(m.group(2).lower()) or MONTHS.get(m.group(2).lower()[:3])]}" + (f" {year}" if year else "")
    if starts and not label:
        label = ", ".join(f"{s['season']} {s['year']}" if s["year"] else s["season"] for s in starts)
    duration = ""
    for m in DURATION_RE.finditer(text):
        if DURATION_CTX.search(text[max(0, m.start() - 70):m.end() + 20]):
            unit = m.group(3).lower()
            unit = "weeks" if unit.startswith(("w", "sem")) else "months"
            duration = f"{m.group(1)}-{m.group(2)} {unit}" if m.group(2) else f"{m.group(1)} {unit}"
            break
    return starts, label, duration


def make_job(source, title, company, url, location="", remote=False, structured_type="",
             description="", tags=None, posted_at=None, apply_url=None, salary="", ats_ref=None, start_hint="", extra=None, countries=None):
    description = strip_html(description)[:8000]
    ats, slug, ref = ats_ref if ats_ref else detect_ats(apply_url or url)
    key = f"{(company or '').lower().strip()}|{(title or '').lower().strip()}|{(location or '').lower().strip()}"
    typ = detect_type(title, structured_type, description)
    starts, start_label, duration = extract_start(title, description, start_hint) if typ == "internship" else ([], "", "")
    return {
        "id": hashlib.sha1(key.encode()).hexdigest()[:16],
        "source": source,
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "remote": bool(remote) or bool(re.search(r"\bremote|anywhere|work from home|télétravail\b", location or "", re.I)),
        "type": typ,
        "starts": starts, "start_label": start_label, "duration": duration,
        "lang": "", "orig_title": "", "orig_description": "",
        "extra": {**(extra or {}), **({"countries": sorted(set(countries))} if countries else {})},
        "url": url,
        "apply_url": apply_url or url,
        "description": description,
        "tags": [t for t in (tags or []) if t],
        "posted_at": posted_at,
        "ats": ats,
        "ats_ref": {"slug": slug, "job_id": ref} if ats else None,
        "salary": salary or "",
    }


_DL_CUE = r"(?:deadline|apply (?:by|before|until)|applications? (?:close|closes|due|must be (?:received|submitted))|closing date|closes? on|bewerbungsfrist|date limite)"
_DAY_FIRST = re.compile(rf"{_DL_CUE}[^.\n]{{0,40}}?\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})[a-zé]*\.?,?\s*(20\d\d)?", re.I)
_MONTH_FIRST = re.compile(rf"{_DL_CUE}[^.\n]{{0,40}}?\b({_MONTH_ALT})[a-zé]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(20\d\d)?", re.I)
_ISO = re.compile(rf"{_DL_CUE}[^.\n]{{0,40}}?\b(20\d\d)-(\d\d)-(\d\d)", re.I)


def extract_deadline(text, today=None):
    """ISO date of an application deadline stated in the text, or ''. Only clear cues count."""
    import datetime as _dt
    today = today or _dt.date.today()
    text = (text or "")[:8000]
    for rx, order in ((_ISO, "ymd"), (_DAY_FIRST, "dm"), (_MONTH_FIRST, "md")):
        m = rx.search(text)
        if not m:
            continue
        try:
            if order == "ymd":
                return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            day, mon = (m.group(1), m.group(2)) if order == "dm" else (m.group(2), m.group(1))
            month = MONTHS.get(mon.lower()) or MONTHS.get(mon.lower()[:3])
            year = int(m.group(3)) if m.group(3) else today.year
            d = _dt.date(year, month, int(day))
            if not m.group(3) and d < today - _dt.timedelta(days=30):
                d = _dt.date(year + 1, month, int(day))  # a deadline without a year is the next one coming
            return d.isoformat()
        except (ValueError, TypeError):
            continue
    return ""
