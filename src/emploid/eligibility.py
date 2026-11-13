"""Visa / work-authorization signals read from a posting. Heuristics: signals, never guarantees.

flags (subset of):
  visa_offered   the posting says it sponsors visas
  relocation     relocation help is offered
  no_sponsorship the posting says it does not sponsor
  citizens_only  citizenship / nationality is required
  clearance      a security clearance is required (usually citizens only)
  auth_required  "must be authorized to work in <country>" (may or may not sponsor)
  uk_sponsor     the employer is on the UK register of licensed visa sponsors
"""
import csv
import io
import re
import threading
import time

import requests

from . import db, query

OFFERED = re.compile(
    r"visa sponsorship (is )?(available|provided|offered|possible)|(we|company|employer) (can|will|do|does|may)( also)? (offer )?sponsor|"
    r"sponsor(s|ing)? (work )?visas?|(offer|provide|provides|offers)s? (visa|immigration) (support|sponsorship|assistance)|"
    r"visa support|blue card|work permit (support|assistance|provided)|immigration (support|assistance)|sponsorship (is )?available", re.I)
RELOCATION = re.compile(r"relocation (assistance|support|package|bonus|allowance|budget|help|benefits?|stipend|reimbursement)|"
                        r"(we )?(offer|provide)s? relocation|relocation (is )?(offered|provided|available)|help(s|ing)? you relocate", re.I)
NO_SPONSOR = re.compile(
    r"(no|not|unable to|cannot|can't|won't|will not|does not|do not|doesn't|don't|without|not able to|not eligible for)[ ,]+(\w+ ){0,3}(visa )?sponsor|"
    r"sponsorship (is )?(not|un)(available|offered|provided)|not (offering|providing) (visa )?sponsorship|"
    r"unable to (provide|offer) (visa|immigration)|we (are )?not (currently )?(able|in a position) to sponsor", re.I)
CITIZENS = re.compile(r"(u\.?s\.?|united states|uk|canadian|british|eu|german|french|australian)? ?citizen(ship)? (is )?(required|only|needed)|"
                      r"must be (a )?(u\.?s\.?|united states|uk|british|canadian|eu|german|french)? ?(citizen|national)|citizens? (and permanent residents )?only|"
                      r"only (u\.?s\.?|uk|canadian|eu|british)? ?(citizens|nationals)|eligible for (a )?(security )?clearance", re.I)
CLEARANCE = re.compile(r"security clearance|secret clearance|ts/sci|top secret|dv clearance|sc clearance|public trust", re.I)
AUTH = re.compile(r"(must|need to|required to|should) (be )?(legally |currently )?(authori[sz]ed|eligible|permitted|entitled|allowed) to work|"
                  r"(legal )?right to work in|work authori[sz]ation (is )?required|authori[sz]ed to work in", re.I)

SIMPLIFY = {"Does Not Offer Sponsorship": "no_sponsorship", "U.S. Citizenship is Required": "citizens_only", "Offers Sponsorship": "visa_offered"}
BLOCKING = {"no_sponsorship", "citizens_only", "clearance"}


def classify(job):
    """Add job['extra']['flags'] (see module docstring)."""
    text = f"{job['title']}\n{job['description']}"
    flags = []
    structured = (job.get("extra") or {}).get("sponsorship")
    if structured in SIMPLIFY:
        flags.append(SIMPLIFY[structured])
    if OFFERED.search(text):
        flags.append("visa_offered")
    if RELOCATION.search(text) or (job.get("extra") or {}).get("relocation"):
        flags.append("relocation")
    if NO_SPONSOR.search(text):
        flags.append("no_sponsorship")
    if CITIZENS.search(text):
        flags.append("citizens_only")
    if CLEARANCE.search(text):
        flags.append("clearance")
    if AUTH.search(text):
        flags.append("auth_required")
    if "visa_offered" in flags and "no_sponsorship" in flags and not structured:
        flags.remove("visa_offered")  # contradictory text ("no sponsorship... other visas"): trust the refusal
    job["extra"]["flags"] = list(dict.fromkeys(flags))
    return job["extra"]["flags"]


def is_blocked(flags):
    return bool(BLOCKING & set(flags)) and "visa_offered" not in flags


# ------------------------------------------------------------- UK register of licensed sponsors

REGISTER_FILE = db.DATA / "uk_sponsors.txt"
_loaded = {"names": None}
_lock = threading.Lock()


def _download():
    page = requests.get("https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers",
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    m = re.search(r'https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv', page)
    if not m:
        return False
    raw = requests.get(m.group(0), headers={"User-Agent": "Mozilla/5.0"}, timeout=120).content.decode("utf-8-sig", "ignore")
    names = set()
    for row in csv.reader(io.StringIO(raw)):
        if row and row[0] and row[0].lower() != "organisation name":
            names.add(query.clean_company(row[0]))
    names.discard("")
    REGISTER_FILE.write_text("\n".join(sorted(names)))
    return True


def uk_sponsors():
    """Set of cleaned organisation names; refreshed weekly. Empty set when unavailable."""
    with _lock:
        if _loaded["names"] is not None:
            return _loaded["names"]
        try:
            if not REGISTER_FILE.exists() or time.time() - REGISTER_FILE.stat().st_mtime > 7 * 86400:
                _download()
            _loaded["names"] = set(REGISTER_FILE.read_text().splitlines()) if REGISTER_FILE.exists() else set()
        except (requests.RequestException, OSError):
            _loaded["names"] = set(REGISTER_FILE.read_text().splitlines()) if REGISTER_FILE.exists() else set()
        return _loaded["names"]


def mark_uk_sponsor(job):
    if "GB" in job["extra"].get("countries", []) and query.clean_company(job["company"]) in uk_sponsors():
        job["extra"]["flags"].append("uk_sponsor")
