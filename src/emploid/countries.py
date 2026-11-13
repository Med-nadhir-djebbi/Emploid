"""Countries and regions, and a gazetteer that turns location text into countries.

locate("Berlin, Germany")        -> countries {"DE"}
locate("San Francisco, CA")      -> {"US"}
locate("Remote - Europe")        -> remote restricted to the European countries
locate("Worldwide")              -> remote, open to everyone"""
import re
import unicodedata

import geonamescache

_gc = geonamescache.GeonamesCache()


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9&' ]+", " ", s)).strip()


# ----------------------------------------------------------------------------- regions

EU = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
EUROPE = EU + "GB CH NO IS LI AL AD BA BY XK MD MC ME MK RS SM UA VA TR".split()
REGIONS = {
    "eu": ("European Union", EU),
    "europe": ("Europe", EUROPE),
    "uk_ie": ("UK and Ireland", ["GB", "IE"]),
    "nordics": ("Nordics", "DK FI IS NO SE".split()),
    "dach": ("Germany, Austria, Switzerland", "DE AT CH".split()),
    "north_america": ("North America", ["US", "CA"]),
    "gulf": ("Gulf states", "SA AE QA KW BH OM".split()),
    "mena": ("Middle East and North Africa", "DZ BH EG IQ IR IL JO KW LB LY MA OM PS QA SA SY TN AE YE".split()),
    "africa": ("Africa", "DZ AO BJ BW BF BI CM CV CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW".split()),
    "apac": ("Asia-Pacific", "AU NZ JP KR CN HK TW SG MY TH VN PH ID IN PK BD LK".split()),
    "latam": ("Latin America", "MX GT BZ HN SV NI CR PA CO VE EC PE BO BR PY UY AR CL CU DO".split()),
}

# phrases used in postings -> region key (for remote jobs limited to an area)
REMOTE_AREAS = [
    (r"\b(eu|european union)\b", "eu"), (r"\beurope(an)?\b|\bemea\b", "europe"), (r"\bnordics?\b", "nordics"),
    (r"\buk and ireland\b|\buk\s*/\s*ireland\b", "uk_ie"), (r"\bnorth america\b|\bnoram\b|\busa? (and|&) canada\b", "north_america"),
    (r"\blatam\b|\blatin america\b", "latam"), (r"\bapac\b|\basia[- ]pacific\b", "apac"), (r"\bmena\b", "mena"),
    (r"\bafrica\b", "africa"), (r"\bgulf\b|\bgcc\b", "gulf"),
]
WORLDWIDE = re.compile(r"\b(worldwide|world wide|anywhere|global(ly)?|any ?where|international)\b", re.I)

# ------------------------------------------------------------------------------ names

ALIASES = {
    "uk": "GB", "u k": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "usa": "US", "u s a": "US", "u s": "US", "united states": "US", "united states of america": "US",
    "america": "US", "deutschland": "DE", "espana": "ES", "italia": "IT", "nederland": "NL", "the netherlands": "NL", "holland": "NL",
    "schweiz": "CH", "suisse": "CH", "svizzera": "CH", "osterreich": "AT", "belgique": "BE", "belgie": "BE", "turkiye": "TR",
    "czechia": "CZ", "czech republic": "CZ", "uae": "AE", "u a e": "AE", "korea": "KR", "south korea": "KR", "russia": "RU",
    "tunisie": "TN", "polska": "PL", "sverige": "SE", "danmark": "DK", "norge": "NO", "suomi": "FI", "brasil": "BR",
    "mexico": "MX", "republic of ireland": "IE", "eire": "IE", "viet nam": "VN", "hong kong sar": "HK", "taiwan": "TW",
    "ivory coast": "CI", "cote d ivoire": "CI", "macedonia": "MK", "north macedonia": "MK", "swaziland": "SZ", "burma": "MM",
}
NAME2CODE = {}
for _code, _c in _gc.get_countries().items():
    NAME2CODE[norm(_c["name"])] = _code
NAME2CODE.update(ALIASES)
CODE2NAME = {code: c["name"] for code, c in _gc.get_countries().items()}
CODE2NAME.update({"XK": "Kosovo", "GB": "United Kingdom", "US": "United States"})
CODES = set(CODE2NAME)

US_STATE_ABBR = set(_gc.get_us_states())
US_STATE_NAMES = {norm(s["name"]) for s in _gc.get_us_states().values()} - {"georgia", "washington"}  # also countries/cities
CA_PROV_ABBR = {"ON", "BC", "AB", "QC", "NS", "NB", "MB", "SK", "PE", "NL", "YT", "NT", "NU"}
CA_PROV_NAMES = {"ontario", "british columbia", "alberta", "quebec", "nova scotia", "new brunswick", "manitoba", "saskatchewan"}

# cities of 100k+ people (and their alternate spellings) -> country; the largest city wins a shared name
CITY2CODE = {}
_best = {}
for _city in _gc.get_cities().values():
    if _city["population"] < 100000:
        continue
    for _name in [_city["name"], *_city.get("alternatenames", [])[:12]]:
        n = norm(_name)
        if len(n) < 3 or n in NAME2CODE:
            continue
        if _best.get(n, 0) < _city["population"]:
            _best[n], CITY2CODE[n] = _city["population"], _city["countrycode"]
CITY2CODE.update({"nyc": "US", "sf": "US", "silicon valley": "US", "bay area": "US", "munchen": "DE", "wien": "AT",
                  "zurich": "CH", "geneve": "CH", "koln": "DE", "praha": "CZ", "warszawa": "PL", "lisboa": "PT",
                  "kobenhavn": "DK", "bruxelles": "BE", "brussel": "BE", "tunis": "TN", "sfax": "TN", "sousse": "TN"})
for _generic in ("remote", "hybrid", "onsite", "global", "worldwide", "anywhere", "home", "office", "main", "central", "north", "south"):
    CITY2CODE.pop(_generic, None)

_SPLIT = re.compile(r"[,;/|()–—]|\s+-\s+|\s+or\s+|\s+and\s+|\s*\+\s*")


def locate(text):
    """-> {"countries": [codes], "remote": bool-ish hint, "remote_countries": [codes] or [] (= open)}"""
    raw = text or ""
    codes = set()      # stated outright: a country, state, province or country-code token
    guessed = set()    # inferred from a city name: only used when nothing is stated outright
    m = re.match(r"^([A-Z]{2})-", raw.strip())  # "PL-Warsaw", "DE-Berlin": a country prefix
    if m and m.group(1) in CODES:
        codes.add(m.group(1))
    low = norm(raw)
    is_remote = bool(re.search(r"\bremote|work from home|anywhere|telecommut|distributed\b", raw, re.I))
    restricted = set()
    if is_remote:
        for pat, key in REMOTE_AREAS:
            if re.search(pat, raw, re.I):
                restricted |= set(REGIONS[key][1])
    for part in _SPLIT.split(raw):
        tok = part.strip()
        if not tok:
            continue
        n = norm(tok)
        if not n:
            continue
        if tok.isupper() and len(tok) == 2:
            if tok in US_STATE_ABBR and "canada" not in low and "united kingdom" not in low:
                codes.add("US")
            elif tok in CA_PROV_ABBR:
                codes.add("CA")
            elif tok in CODES and tok not in ("IN", "DE", "AL", "AR", "ID", "IL", "MA", "ME", "MD", "MT", "PA", "CA", "CO", "CH", "LA", "NO"):
                codes.add(tok)
            elif tok in CODES and tok in ("DE", "IN", "CH", "NO", "AL", "AR", "ID", "IL", "MA", "ME", "MT", "CO", "LA", "PA", "MD"):
                if tok not in US_STATE_ABBR or re.search(r"germany|india|switzerland|norway|albania|argentina|indonesia|israel|morocco|montenegro|malta|colombia|laos|pakistan|moldova", low):
                    codes.add(tok)
                else:
                    codes.add("US")
            continue
        if n in NAME2CODE:
            codes.add(NAME2CODE[n])
        elif n in US_STATE_NAMES:
            codes.add("US")
        elif n in CA_PROV_NAMES:
            codes.add("CA")
        elif n in CITY2CODE:
            guessed.add(CITY2CODE[n])
        else:  # "Berlin Germany", "Remote Europe": try the first and last word group
            words = n.split()
            for k in (3, 2, 1):
                tail, head = " ".join(words[-k:]), " ".join(words[:k])
                if len(words) > k and (tail in NAME2CODE or head in NAME2CODE):
                    codes.add(NAME2CODE.get(tail) or NAME2CODE.get(head))
                    break
                if len(words) > k and (tail in CITY2CODE or head in CITY2CODE):
                    guessed.add(CITY2CODE.get(tail) or CITY2CODE.get(head))
                    break
    if not codes:  # "San Mateo, California" is the US even though a Philippine city shares the name
        codes = guessed
    if is_remote and not WORLDWIDE.search(raw):
        restricted |= codes  # "Remote, United States" means remote within the US
        codes = set()
    return {"countries": sorted(codes), "remote": is_remote, "remote_countries": sorted(restricted)}


def region_codes(keys):
    out = set()
    for k in keys:
        out |= set(REGIONS[k][1]) if k in REGIONS else {k}
    return out
