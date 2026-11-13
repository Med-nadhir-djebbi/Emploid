import json
import os

import pytest

from emploid import store


def test_round_trip_and_no_leftovers(tmp_path):
    f = tmp_path / "a.json"
    store.write_json(f, {"a": [1, 2], "é": "ü"}, indent=2)
    assert store.read_json(f) == {"a": [1, 2], "é": "ü"}
    assert os.listdir(tmp_path) == ["a.json"]


def test_failed_write_keeps_old_file(tmp_path):
    f = tmp_path / "a.json"
    store.write_json(f, {"ok": 1})
    with pytest.raises(TypeError):
        store.write_json(f, {"bad": object()})
    assert json.loads(f.read_text()) == {"ok": 1}
    assert os.listdir(tmp_path) == ["a.json"]


def test_read_tolerates_missing_and_corrupt(tmp_path):
    assert store.read_json(tmp_path / "none.json", []) == []
    (tmp_path / "bad.json").write_text("{not json")
    assert store.read_json(tmp_path / "bad.json", {}) == {}


def test_files_are_private(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permissions")
    f = tmp_path / "p.json"
    store.write_json(f, {})
    assert (f.stat().st_mode & 0o077) == 0
