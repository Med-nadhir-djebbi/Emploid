"""Fetch the full description for matched jobs whose listing only had a title (Greenhouse, Workday)."""
import html

from . import sources
from .classify import strip_html


def enrich(job):
    """Fill job['description'] (and part-time hint) in place. Returns True if something was added."""
    if job["description"]:
        return False
    if job["ats"] == "greenhouse" and job["ats_ref"]:
        ref = job["ats_ref"]
        data = sources.get_json(f"https://boards-api.greenhouse.io/v1/boards/{ref['slug']}/jobs/{ref['job_id']}")
        if data and data.get("content"):
            job["description"] = strip_html(html.unescape(data["content"]))[:8000]
            return True
    wd = (job.get("extra") or {}).get("workday")
    if wd:
        data = sources.get_json(f"https://{wd['tenant']}.{wd['wd']}.myworkdayjobs.com/wday/cxs/{wd['tenant']}/{wd['site']}{wd['path']}")
        info = (data or {}).get("jobPostingInfo") or {}
        if info.get("jobDescription"):
            job["description"] = strip_html(info["jobDescription"])[:8000]
            if (info.get("timeType") or "").lower().startswith("part") and job["type"] == "full_time":
                job["type"] = "part_time"
            return True
    return False
