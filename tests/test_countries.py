import pytest
from emploid import countries


@pytest.mark.parametrize("text,expected", [
    ("Berlin, Germany", ["DE"]),
    ("Paris", ["FR"]),
    ("San Mateo, California", ["US"]),
    ("Cambridge, MA", ["US"]),
    ("Cambridge, United Kingdom", ["GB"]),
    ("NY, USA", ["US"]),
    ("Toronto, ON", ["CA"]),
    ("PL-Warsaw", ["PL"]),
    ("Dublin, Ireland", ["IE"]),
    ("Zurich", ["CH"]),
])
def test_places(text, expected):
    r = countries.locate(text)
    assert r["countries"] == expected and not r["remote"]


def test_worldwide_remote_is_open():
    r = countries.locate("Remote - Worldwide")
    assert r["remote"] and r["remote_countries"] == []


def test_remote_in_a_place_is_limited_to_it():
    r = countries.locate("Remote, United States")
    assert r["remote"] and r["countries"] == [] and r["remote_countries"] == ["US"]


def test_remote_region():
    r = countries.locate("Remote - Europe")
    assert r["remote"] and "DE" in r["remote_countries"] and "US" not in r["remote_countries"]


def test_gibberish_is_unplaced():
    assert countries.locate("")["countries"] == []
    assert countries.locate("Somewhere Cozy")["countries"] == []


def test_region_codes():
    assert {"DE", "FR"} <= countries.region_codes(["eu"])
    assert countries.region_codes(["TN"]) == {"TN"}
