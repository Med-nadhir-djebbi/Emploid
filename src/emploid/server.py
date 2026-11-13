"""Local web app for the Emploid. Run: emploid"""
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort

from . import apply, countries, db, logos, query, search, sources

STATIC = Path(__file__).resolve().parent / "static"
app = Flask(__name__, static_folder=str(STATIC), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # resumes only


@app.before_request
def guard():
    """The app listens on localhost only, but any web page you visit can still send requests to localhost.
    Refuse requests addressed to some other hostname (DNS rebinding) and writes started from another site (CSRF)."""
    host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        abort(403, "Unexpected host")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin") or ""
        if origin and origin.split("://", 1)[-1].rsplit(":", 1)[0].strip("[]").lower() not in ("127.0.0.1", "localhost", "::1"):
            abort(403, "Cross-site request refused")
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403, "Cross-site request refused")


@app.after_request
def headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if resp.mimetype == "text/html":
        resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/jobs")
def jobs():
    tab = request.args.get("tab", "results")
    if tab not in ("results", "saved", "applied", "dismissed"):
        abort(400)
    hidden = {query.clean_company(n) for n in search.load_hidden()}
    shown = lambda rows: [r for r in rows if query.clean_company(r["company"]) not in hidden]
    rows = shown(db.list_jobs("results")) if tab == "results" else db.list_jobs(tab)
    for r in rows:
        r["apply_state"] = apply.apply_state.get(r["id"])
    counts = db.counts()
    counts["results"] = len(rows) if tab == "results" else len(shown(db.list_jobs("results"))) if hidden else counts["results"]
    return jsonify(jobs=rows, counts=counts, run_started=search.state["started"])


@app.post("/api/jobs/status")
def set_status():
    body = request.get_json(force=True)
    if body.get("status") not in ("new", "saved", "dismissed", "applied", "manual", "failed"):
        abort(400)
    for jid in body.get("ids", []):
        db.set_status(jid, body["status"], body.get("note"))
    return jsonify(counts=db.counts())


@app.get("/api/search")
def get_search():
    return jsonify(params=search.load_search(), saved=search.saved_search_exists(), state=search.state,
                   settings_sources=list(search.load_settings()["sources"].items()))


@app.post("/api/search")
def post_search():
    params = request.get_json(force=True)
    search.save_search(params)
    started = search.start_search(params)
    return jsonify(started=started)


@app.post("/api/search/run")
def run_saved():
    started = search.start_search(search.load_search(), daily=bool(request.args.get("daily")))
    return jsonify(started=started)


@app.post("/api/jobs/<job_id>/track")
def track_job(job_id):
    b = request.get_json(force=True)
    db.track(job_id, b.get("stage"), b.get("user_note"), b.get("follow_up"))
    return jsonify(ok=True)


@app.get("/api/hidden")
def get_hidden():
    return jsonify(search.load_hidden())


@app.post("/api/hidden")
def post_hidden():
    return jsonify(search.hide_company(request.get_json(force=True).get("company", "")))


@app.delete("/api/hidden")
def delete_hidden():
    return jsonify(search.unhide_company(request.args.get("company", "")))


@app.get("/api/logo")
def logo():
    path = logos.resolve(request.args.get("company", ""), request.args.get("url", ""))
    if not path:
        resp = app.response_class("", 204)  # not an error: the page falls back to initials, and the console stays quiet
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp
    resp = send_from_directory(path.parent, path.name)
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@app.get("/api/export/applied.csv")
def export_applied():
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Company", "Title", "Location", "Stage", "Applied on", "Follow up", "Link", "Notes"])
    for j in db.list_jobs("applied"):
        applied = time.strftime("%Y-%m-%d", time.localtime(j["status_at"])) if j["status_at"] else ""
        w.writerow([j["company"], j["title"], j["location"], j["stage"], applied, j["follow_up"], j["apply_url"], j["user_note"]])
    resp = app.response_class(out.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=applications.csv"
    return resp


@app.get("/api/regions")
def get_regions():
    return jsonify(regions=[{"key": k, "name": n, "codes": c} for k, (n, c) in countries.REGIONS.items()],
                   names=countries.CODE2NAME)


@app.get("/api/sources/health")
def sources_health():
    health = search.load_health()
    settings = search.load_settings()
    return jsonify(sources=[{"key": k, "enabled": bool(settings["sources"].get(k, True)), **v} for k, v in sorted(health.items())])


@app.get("/api/presets")
def get_presets():
    return jsonify(search.load_presets())


@app.post("/api/presets")
def post_preset():
    body = request.get_json(force=True)
    if not (body.get("name") or "").strip():
        abort(400, "A preset needs a name")
    return jsonify(search.save_preset(body["name"], body["params"]))


@app.delete("/api/presets/<preset_id>")
def remove_preset(preset_id):
    return jsonify(search.delete_preset(preset_id))


@app.post("/api/presets/<preset_id>/run")
def run_preset(preset_id):
    preset = next((p for p in search.load_presets() if p["id"] == preset_id), None)
    if not preset:
        abort(404)
    search.save_search(preset["params"])  # the daily run repeats whatever was run last
    return jsonify(started=search.start_search(preset["params"], preset_id=preset_id), params=preset["params"])


@app.get("/api/search/status")
def search_status():
    return jsonify(search.state)


@app.get("/api/profile")
def get_profile():
    p = apply.load_profile()
    p["_missing"] = apply.missing_profile_fields(p)
    p["_questions"] = apply.FIXED_QUESTIONS
    p["_unanswered"] = [{"label": k, "count": n} for k, n in
                        sorted(apply.load_unanswered().items(), key=lambda x: -x[1])]
    return jsonify(p)


@app.post("/api/profile/unanswered/dismiss")
def dismiss_unanswered():
    apply.forget_unanswered(request.get_json(force=True).get("label", ""))
    return jsonify(ok=True)


@app.post("/api/profile")
def post_profile():
    p = request.get_json(force=True)
    for k in ("_missing", "_questions", "_unanswered", "answers"):
        p.pop(k, None)
    apply.save_profile({**apply.load_profile(), **p})
    return jsonify(ok=True)


@app.post("/api/profile/resume")
def upload_resume():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith((".pdf", ".doc", ".docx")):
        abort(400, "Upload a PDF or Word file")
    from werkzeug.utils import secure_filename
    dest = apply.RESUME_DIR / (secure_filename(f.filename) or "resume.pdf")
    f.save(dest)
    p = apply.load_profile()
    p["resume"] = str(dest)
    apply.save_profile(p)
    return jsonify(resume=str(dest))


@app.get("/api/settings")
def get_settings():
    return jsonify(search.load_settings())


@app.post("/api/settings")
def post_settings():
    search.save_settings({**search.load_settings(), **request.get_json(force=True)})
    return jsonify(ok=True)


@app.post("/api/apply/check")
def apply_check():
    return jsonify(apply.check(request.get_json(force=True).get("ids", [])))


@app.post("/api/apply/install-browser")
def apply_install_browser():
    return jsonify(apply.install_browser())


@app.get("/api/apply/install-browser")
def apply_install_status():
    return jsonify(apply.install_status())


@app.post("/api/apply")
def apply_jobs():
    return jsonify(apply.enqueue(request.get_json(force=True).get("ids", [])))


@app.get("/api/apply/status")
def apply_status():
    return jsonify(apply.apply_state)


@app.post("/api/jobs/<job_id>/translate")
def translate_now(job_id):
    from . import translate
    job = db.get(job_id)
    if not job:
        abort(404)
    if translate.translate_job(job) and job["orig_title"]:
        db.set_translation(job_id, job["title"], job["description"], job["orig_title"], job["orig_description"], job["lang"])
        job = db.get(job_id)
    return jsonify(job=job, ok=bool(job["translated"] or job["lang"] in ("", "en")))


@app.get("/api/jobs/<job_id>/screenshot")
def screenshot(job_id):
    for suffix in ("_done", "_after", ""):
        p = apply.SHOT_DIR / f"{job_id}{suffix}.png"
        if p.exists():
            return send_from_directory(apply.SHOT_DIR, p.name)
    abort(404)


def serve(port=8765, host="127.0.0.1"):
    threading.Thread(target=sources.prune_cache, daemon=True).start()
    try:
        from waitress import serve as wserve
        wserve(app, host=host, port=port, threads=8, ident="emploid")
    except ImportError:
        app.run(host, port, threaded=True)


def main():
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)


if __name__ == "__main__":
    main()
