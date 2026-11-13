"""Is a curated-list posting still open? Lists like SimplifyJobs keep closed postings around for a while."""
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import sources

CURATED = {"SimplifyJobs", "Internship list (vanshb03)"}
GONE = re.compile(r"no longer (accepting|available|open|active)|(position|job|role|posting|vacancy) (has been|is|was) (filled|closed|removed|expired)|"
                  r"job (not found|has expired)|this (job|position|posting) (has been )?(closed|removed|expired)|"
                  r"page (could not be|not) found|we couldn.t find (that|this) (job|page)|applications? (is|are) closed", re.I)
WD = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([^/?#]+)(/job/[^?#]+)", re.I)


def alive(job):
    """False only when we are fairly sure the posting is gone; network trouble counts as alive."""
    ref, ats = job.get("ats_ref") or {}, job.get("ats")
    try:
        if ats == "greenhouse" and ref:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{ref['slug']}/jobs/{ref['job_id']}", timeout=8)
            return r.status_code != 404
        if ats == "lever" and ref:
            r = requests.get(f"https://api.lever.co/v0/postings/{ref['slug']}/{ref['job_id']}", timeout=8)
            return r.status_code != 404
        m = WD.search(job["url"])
        if m:
            r = requests.get(f"https://{m.group(1)}.{m.group(2)}.myworkdayjobs.com/wday/cxs/{m.group(1)}/{m.group(3)}{m.group(4)}",
                             headers=sources.UA, timeout=8)
            return r.status_code != 404
        r = requests.get(job["url"], headers=sources.UA, timeout=8, allow_redirects=True)
        if r.status_code in (404, 410):
            return False
        return not (r.status_code == 200 and GONE.search(r.text[:30000]))
    except requests.RequestException:
        return True


def drop_closed(jobs, progress, budget=60, limit=500):
    """Check the curated-list postings among `jobs`; returns the set of ids that are closed."""
    todo = [j for j in jobs if j["source"] in CURATED][:limit]
    dead, done = set(), [0]
    deadline = time.time() + budget

    def one(j):
        if time.time() > deadline:
            return
        if not alive(j):
            dead.add(j["id"])
        done[0] += 1
        progress(done[0], len(todo), len(dead))

    if todo:
        with ThreadPoolExecutor(16) as ex:
            list(ex.map(one, todo))
    return dead, len(todo)
