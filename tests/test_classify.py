import datetime as dt

from emploid import classify, eligibility


def test_internship_detection():
    assert classify.detect_type("Software Engineering Intern", "", "") == "internship"
    assert classify.detect_type("Praktikant (m/w/d) Softwareentwicklung", "", "") == "internship"
    assert classify.detect_type("Senior Software Engineer", "", "") != "internship"


def test_start_and_season():
    starts, label, _ = classify.extract_start("Software Intern, Summer 2027", "", "")
    assert starts == [{"season": "Summer", "year": 2027}] and "2027" in label
    starts, _, _ = classify.extract_start("Intern - 2027 - Summer", "", "")
    assert {"season": "Summer", "year": 2027} in starts


def test_deadline_needs_a_cue():
    today = dt.date(2026, 1, 10)
    assert classify.extract_deadline("Application deadline: 15 March 2026", today) == "2026-03-15"
    assert classify.extract_deadline("Apply by March 15, 2026", today) == "2026-03-15"
    assert classify.extract_deadline("We were founded on 15 March 2020", today) == ""


def test_make_job_is_stable_and_detects_ats():
    a = classify.make_job("t", "Intern", "Acme", "https://boards.greenhouse.io/acme/jobs/123", "Berlin")
    b = classify.make_job("other", "Intern", "Acme", "https://example.com", "Berlin")
    assert a["id"] == b["id"]
    assert a["ats"] == "greenhouse" and b["ats"] is None


def _flags(text, title="Intern"):
    return set(eligibility.classify({"title": title, "description": text, "extra": {}}))


def test_visa_signals():
    assert "visa_offered" in _flags("We offer visa sponsorship and relocation assistance.")
    assert "relocation" in _flags("We offer visa sponsorship and relocation assistance.")
    assert "no_sponsorship" in _flags("We are unable to sponsor work visas.")
    assert "citizens_only" in _flags("US citizenship is required.")
    assert "clearance" in _flags("Active secret clearance needed.")


def test_blocking_rules():
    assert eligibility.is_blocked(["no_sponsorship"])
    assert not eligibility.is_blocked(["no_sponsorship", "visa_offered"])
    assert not eligibility.is_blocked(["relocation"])
