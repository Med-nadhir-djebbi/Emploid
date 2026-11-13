"""SQLite storage. Job status: new | saved | dismissed | applied | manual | failed."""
import json
import sqlite3
import threading
import time
from . import paths

DATA = paths.data_dir()
DB_PATH = DATA / "jobs.db"
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, location TEXT, remote INTEGER,
  type TEXT, url TEXT, apply_url TEXT, description TEXT, tags TEXT, posted_at TEXT,
  ats TEXT, ats_ref TEXT, salary TEXT,
  score REAL DEFAULT 0, in_results INTEGER DEFAULT 0, first_seen REAL, last_seen REAL,
  status TEXT DEFAULT 'new', note TEXT DEFAULT '', status_at REAL,
  starts TEXT, start_label TEXT DEFAULT '', duration TEXT DEFAULT '', lang TEXT DEFAULT '',
  orig_title TEXT DEFAULT '', orig_description TEXT DEFAULT '', extra TEXT,
  stage TEXT DEFAULT '', user_note TEXT DEFAULT '', follow_up TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS translations (h TEXT PRIMARY KEY, out TEXT);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, in_results);
"""


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


_c = conn()
with _lock:
    _c.executescript(SCHEMA)
    for col, decl in (("starts", "TEXT"), ("start_label", "TEXT DEFAULT ''"), ("duration", "TEXT DEFAULT ''"),
                      ("lang", "TEXT DEFAULT ''"), ("orig_title", "TEXT DEFAULT ''"),
                      ("orig_description", "TEXT DEFAULT ''"), ("extra", "TEXT"), ("stage", "TEXT DEFAULT ''"),
                      ("user_note", "TEXT DEFAULT ''"), ("follow_up", "TEXT DEFAULT ''")):
        try:  # upgrade databases created by the first version
            _c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
    _c.commit()


def _row(r):
    d = dict(r)
    d["tags"] = json.loads(d["tags"] or "[]")
    d["ats_ref"] = json.loads(d["ats_ref"]) if d["ats_ref"] else None
    d["starts"] = json.loads(d["starts"] or "[]")
    d["extra"] = json.loads(d["extra"] or "{}")
    d["translated"] = bool(d["orig_title"] or d["orig_description"])
    d["remote"] = bool(d["remote"])
    d["auto"] = bool(d["ats"])
    return d


def reset_results():
    with _lock:
        _c.execute("UPDATE jobs SET in_results=0")
        _c.commit()


def upsert(jobs_with_scores, run_started):
    """jobs_with_scores: [(job, score)]. Returns number of jobs seen for the first time."""
    new = 0
    cols = ["source", "title", "company", "location", "remote", "type", "url", "apply_url", "description",
            "tags", "posted_at", "ats", "ats_ref", "salary", "starts", "start_label", "duration", "lang",
            "orig_title", "orig_description", "extra", "score"]
    with _lock:
        for j, score in jobs_with_scores:
            vals = [j["source"], j["title"], j["company"], j["location"], int(j["remote"]), j["type"], j["url"],
                    j["apply_url"], j["description"], json.dumps(j["tags"]), j["posted_at"], j["ats"],
                    json.dumps(j["ats_ref"]) if j["ats_ref"] else None, j["salary"], json.dumps(j["starts"]),
                    j["start_label"], j["duration"], j["lang"], j["orig_title"], j["orig_description"],
                    json.dumps(j["extra"]), score]
            if _c.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone():
                _c.execute("UPDATE jobs SET " + ",".join(f"{c}=?" for c in cols) + ",in_results=1,last_seen=? WHERE id=?",
                           vals + [time.time(), j["id"]])
            else:
                new += 1
                # same link as something already applied to / dismissed (reposted under a new id): keep it hidden
                twin = _c.execute("SELECT status FROM jobs WHERE status IN ('applied','dismissed') AND (url=? OR apply_url=?) LIMIT 1",
                                  (j["url"], j["apply_url"])).fetchone()
                _c.execute("INSERT INTO jobs (" + ",".join(cols) + ",in_results,first_seen,last_seen,id,status,status_at) VALUES ("
                           + ",".join("?" * len(cols)) + ",1,?,?,?,?,?)",
                           vals + [run_started, time.time(), j["id"], twin[0] if twin else "new", time.time() if twin else None])
                if twin:
                    new -= 1
        _c.commit()
    return new


def set_translation(job_id, title, description, orig_title, orig_description, lang):
    with _lock:
        _c.execute("UPDATE jobs SET title=?, description=?, orig_title=?, orig_description=?, lang=? WHERE id=?",
                   (title, description, orig_title, orig_description, lang, job_id))
        _c.commit()


def cache_get(h):
    with _lock:
        r = _c.execute("SELECT out FROM translations WHERE h=?", (h,)).fetchone()
    return r[0] if r else None


def cache_put(h, out):
    with _lock:
        _c.execute("INSERT OR REPLACE INTO translations VALUES (?,?)", (h, out))
        _c.commit()


def list_jobs(tab, since=None):
    with _lock:
        if tab == "results":
            q = "SELECT * FROM jobs WHERE in_results=1 AND status IN ('new','manual','failed') ORDER BY score DESC, posted_at DESC"
            rows = _c.execute(q).fetchall()
        else:
            status = {"saved": "('saved')", "applied": "('applied')", "dismissed": "('dismissed')"}[tab]
            rows = _c.execute(f"SELECT * FROM jobs WHERE status IN {status} ORDER BY status_at DESC").fetchall()
    return [_row(r) for r in rows]


def counts():
    with _lock:
        r = _c.execute("""SELECT
          SUM(in_results=1 AND status IN ('new','manual','failed')) results,
          SUM(status='saved') saved, SUM(status='applied') applied, SUM(status='dismissed') dismissed,
          SUM(status='applied' AND follow_up != '' AND follow_up <= date('now','localtime')
              AND stage IN ('applied','interviewing')) followups
          FROM jobs""").fetchone()
    return {k: r[k] or 0 for k in ("results", "saved", "applied", "dismissed", "followups")}


def get(job_id):
    with _lock:
        r = _c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(r) if r else None


def set_status(job_id, status, note=None):
    with _lock:
        _c.execute("UPDATE jobs SET status=?, note=COALESCE(?, note), status_at=? WHERE id=?",
                   (status, note, time.time(), job_id))
        if status == "applied":  # applications start in the tracker's first stage
            _c.execute("UPDATE jobs SET stage='applied' WHERE id=? AND COALESCE(stage,'')=''", (job_id,))
        _c.commit()


STAGES = ("applied", "interviewing", "offer", "rejected", "withdrawn")


def track(job_id, stage=None, user_note=None, follow_up=None):
    """Application tracker fields; only the ones given are changed."""
    with _lock:
        if stage is not None and stage in STAGES:
            _c.execute("UPDATE jobs SET stage=? WHERE id=?", (stage, job_id))
        if user_note is not None:
            _c.execute("UPDATE jobs SET user_note=? WHERE id=?", (user_note[:4000], job_id))
        if follow_up is not None:
            _c.execute("UPDATE jobs SET follow_up=? WHERE id=?", (follow_up[:10], job_id))
        _c.commit()
