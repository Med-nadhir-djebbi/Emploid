import io

import pytest

from emploid import db, server

H = {"Host": "127.0.0.1:8765"}


@pytest.fixture()
def client():
    server.app.testing = True
    return server.app.test_client()


def job(**kw):
    from emploid.classify import make_job
    return make_job(kw.pop("source", "t"), kw.pop("title", "Software Intern"), kw.pop("company", "Acme"),
                    kw.pop("url", "https://boards.greenhouse.io/acme/jobs/1"), kw.pop("location", "Berlin, Germany"), **kw)


def test_health_and_index(client):
    assert client.get("/api/health", headers=H).get_json() == {"ok": True}
    r = client.get("/", headers=H)
    assert r.status_code == 200 and b"<html" in r.data.lower()
    assert r.headers["X-Frame-Options"] == "DENY"


def test_rejects_foreign_host(client):
    assert client.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 403


def test_rejects_cross_site_writes(client):
    r = client.post("/api/settings", json={"home_country": "FR"}, headers={**H, "Origin": "https://evil.example.com"})
    assert r.status_code == 403
    r = client.post("/api/settings", json={"home_country": "FR"}, headers={**H, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.get("/api/settings", headers=H).get_json()["home_country"] != "FR"


def test_same_origin_writes_work(client):
    r = client.post("/api/settings", json={"home_country": "FR"}, headers={**H, "Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200
    assert client.get("/api/settings", headers=H).get_json()["home_country"] == "FR"


def test_job_lifecycle(client):
    j = job()
    db.upsert([(j, 5.0)], 1.0)
    rows = client.get("/api/jobs?tab=results", headers=H).get_json()["jobs"]
    assert [r["id"] for r in rows] == [j["id"]]
    client.post("/api/jobs/status", json={"ids": [j["id"]], "status": "applied"}, headers=H)
    assert client.get("/api/jobs?tab=results", headers=H).get_json()["jobs"] == []
    applied = client.get("/api/jobs?tab=applied", headers=H).get_json()["jobs"]
    assert applied[0]["stage"] == "applied"
    # a re-run of the same search must not bring an applied job back
    db.upsert([(j, 5.0)], 2.0)
    assert client.get("/api/jobs?tab=results", headers=H).get_json()["jobs"] == []
    assert client.get("/api/export/applied.csv", headers=H).data.startswith(b"Company,")


def test_bad_inputs(client):
    assert client.get("/api/jobs?tab=nope", headers=H).status_code == 400
    assert client.post("/api/jobs/status", json={"ids": ["x"], "status": "bogus"}, headers=H).status_code == 400
    assert client.post("/api/presets", json={"name": " ", "params": {}}, headers=H).status_code == 400
    r = client.post("/api/profile/resume", data={"file": (io.BytesIO(b"x"), "evil.exe")}, headers=H,
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_resume_name_is_sanitised(client):
    r = client.post("/api/profile/resume", data={"file": (io.BytesIO(b"%PDF-1.4"), "../../etc/cv.pdf")}, headers=H,
                    content_type="multipart/form-data")
    assert r.status_code == 200
    from emploid import apply
    assert apply.RESUME_DIR in __import__("pathlib").Path(r.get_json()["resume"]).parents


def test_presets_round_trip(client):
    r = client.post("/api/presets", json={"name": "Europe", "params": {"query": "python"}}, headers=H).get_json()
    assert r[0]["name"] == "Europe"
    pid = r[0]["id"]
    assert client.delete(f"/api/presets/{pid}", headers=H).get_json() == []


def test_auto_apply_is_opt_in(client):
    from emploid import apply
    apply.save_profile({**apply.load_profile(), "first_name": "A", "last_name": "B", "email": "a@b.c", "phone": "1",
                        "resume": str(apply.RESUME_DIR / "x.pdf")})
    (apply.RESUME_DIR / "x.pdf").write_bytes(b"%PDF")
    j = job(title="Intern Opt In", company="OptCo")
    db.upsert([(j, 1.0)], 1.0)
    client.post("/api/settings", json={"auto_apply": False}, headers=H)
    r = client.post("/api/apply", json={"ids": [j["id"]]}, headers=H).get_json()
    assert "switched off" in r["error"]
    chk = client.post("/api/apply/check", json={"ids": [j["id"]]}, headers=H).get_json()
    assert chk["auto_enabled"] is False


def test_manual_only_batch_needs_no_opt_in(client):
    j = job(title="Intern Manual", company="ManCo", url="https://example.com/careers/1")
    db.upsert([(j, 1.0)], 1.0)
    client.post("/api/settings", json={"auto_apply": False}, headers=H)
    r = client.post("/api/apply", json={"ids": [j["id"]]}, headers=H).get_json()
    assert r.get("queued") == {j["id"]: "manual"}
