"""Translate job text to English (Google's public translate endpoint, paced, cached in SQLite).

Job titles and descriptions are sent to Google for translation; only non-English postings are."""
import hashlib
import json
import threading
import time

import requests
from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from . import db

DetectorFactory.seed = 0
_gate = threading.Lock()
_last = [0.0]
MIN_GAP = 0.6   # seconds between requests; bursts get throttled
_cooldown_until = [0.0]
CHUNK = 3500


def detect(text):
    """ISO language code of `text`, or '' when unsure."""
    text = (text or "").strip()
    if len(text) < 20:
        return ""
    try:
        best = detect_langs(text[:1500])[0]
    except LangDetectException:
        return ""
    return best.lang if best.prob > 0.7 else ""


def _deepl(text, key):
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    try:
        r = requests.post(f"https://{host}/v2/translate", data={"text": text, "target_lang": "EN-US"},
                          headers={"Authorization": f"DeepL-Auth-Key {key}"}, timeout=25)
        if r.status_code == 200:
            return r.json()["translations"][0]["text"]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def _request(text):
    try:
        key = json.loads((db.DATA / "settings.json").read_text()).get("keys", {}).get("deepl_key", "")
    except (OSError, ValueError):
        key = ""
    if key:
        out = _deepl(text, key)
        if out is not None:
            return out
    if time.time() < _cooldown_until[0]:
        return None
    for attempt in range(3):
        with _gate:
            wait = MIN_GAP - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            r = requests.post("https://translate.googleapis.com/translate_a/single",
                              data={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text}, timeout=20)
            if r.status_code == 200:
                return "".join(part[0] for part in r.json()[0] if part and part[0])
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
        except (requests.RequestException, ValueError):
            time.sleep(1)
    _cooldown_until[0] = time.time() + 120  # throttled or offline: stop hammering, callers retry later
    return None


def cooling_down():
    """True while the translation service is refusing requests (retrying now would only waste time)."""
    return time.time() < _cooldown_until[0]


def to_english(text):
    """Translate (chunked on paragraph boundaries). Returns None if the service is unavailable."""
    text = (text or "").strip()
    if not text:
        return ""
    h = hashlib.sha1(text.encode()).hexdigest()
    cached = db.cache_get(h)
    if cached is not None:
        return cached
    chunks, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > CHUNK and cur:
            chunks.append(cur)
            cur = ""
        while len(para) > CHUNK:
            chunks.append(para[:CHUNK])
            para = para[CHUNK:]
        cur += para + "\n"
    if cur.strip():
        chunks.append(cur)
    out = []
    for c in chunks:
        t = _request(c)
        if t is None:
            return None
        out.append(t.strip("\n"))
    result = "\n".join(out)
    db.cache_put(h, result)
    return result


def translate_job(job):
    """Fill English title/description on a job dict in place. Keeps the original text.
    Returns True when the job is (now) in English."""
    if job.get("orig_title") or job.get("orig_description"):
        return True
    lang = job.get("lang") or detect(f"{job['title']}. {job['description'][:600]}")
    job["lang"] = lang or "en"
    if lang in ("", "en"):
        return True
    t = to_english(job["title"])
    d = to_english(job["description"]) if job["description"] else ""
    if t is None or d is None:
        return False
    job["orig_title"], job["orig_description"] = job["title"], job["description"]
    job["title"], job["description"] = t, d
    return True
