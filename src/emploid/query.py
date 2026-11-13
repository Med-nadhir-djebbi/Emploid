"""Understand a free-text query such as "software engineering google" or "data science at Stripe, ml".

parse() splits it into role phrases and target companies. Role matching is stem- and synonym-aware,
so "software engineering" also finds "Software Engineer" and "Software Developer"."""
import re
import unicodedata

# Words that are never a company even when a company shares the name.
GENERIC = {
    "remote", "data", "software", "engineering", "engineer", "developer", "intern", "internship", "design",
    "designer", "product", "research", "science", "scientist", "marketing", "finance", "sales", "support",
    "security", "cloud", "mobile", "web", "backend", "frontend", "fullstack", "machine", "learning", "ai", "ml",
    "analyst", "analytics", "business", "operations", "hardware", "devops", "qa", "ux", "ui", "student",
    "summer", "part", "time", "job", "jobs", "stage", "work", "scale", "ramp", "wave", "wise", "split",
    "later", "writer", "census", "segment", "heap", "drift", "outreach", "apollo", "gamma", "tome", "orca",
    "neon", "render", "fly", "king", "sea", "ro", "arm", "tide", "ledger", "tier", "voi", "lime", "flink",
    "mercury", "planet", "spire", "convoy", "tomorrow", "orange", "remote", "oyster", "papaya", "lever",
    "greenhouse", "sorare", "raisin", "comet", "v7", "eleven", "slack", "target", "snap",
}

# Big employers that are meant when written plainly, with the names their postings use.
ALIASES = {
    "google": ["google", "alphabet", "deepmind"],
    "meta": ["meta", "facebook", "instagram", "whatsapp"],
    "amazon": ["amazon", "aws"],
    "microsoft": ["microsoft", "linkedin", "github"],
    "apple": ["apple"],
    "netflix": ["netflix"],
    "nvidia": ["nvidia"],
    "tesla": ["tesla"],
    "ibm": ["ibm"],
    "oracle": ["oracle"],
    "intel": ["intel"],
    "adobe": ["adobe"],
    "salesforce": ["salesforce"],
    "uber": ["uber"],
    "airbnb": ["airbnb"],
    "spotify": ["spotify"],
    "stripe": ["stripe"],
    "openai": ["openai"],
    "anthropic": ["anthropic"],
    "cisco": ["cisco"],
    "paypal": ["paypal"],
    "bloomberg": ["bloomberg"],
    "palantir": ["palantir"],
    "databricks": ["databricks"],
    "snowflake": ["snowflake"],
    "samsung": ["samsung"],
    "sap": ["sap"],
    "siemens": ["siemens"],
    "bosch": ["bosch"],
    "capgemini": ["capgemini"],
}

SYNONYMS = [
    {"engineer", "engineering", "developer", "development", "programmer", "swe", "sde", "ingenieur", "ingénieur",
     "entwickler", "developpeur", "développeur", "desarrollador", "ingeniero"},
    {"ml", "machine learning", "maschinelles lernen", "apprentissage automatique"},
    {"ai", "artificial intelligence", "kuenstliche intelligenz", "intelligence artificielle"},
    {"data", "daten", "données", "donnees", "datos"},
    {"frontend", "front-end", "front end"},
    {"backend", "back-end", "back end"},
    {"ux", "user experience"},
    {"devops", "site reliability", "sre", "platform engineer"},
    {"marketing", "growth"},
]


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def stem(w):
    w = norm(w)
    for suf in ("ations", "ation", "ments", "ment", "ings", "ing", "ers", "er", "ions", "ion", "ies", "es", "s"):
        if len(w) - len(suf) >= 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def word_pattern(word):
    """Regex source matching `word` in any form or synonym."""
    w = norm(word)
    alts = {w}
    for group in SYNONYMS:
        if w in {norm(x) for x in group} or stem(w) in {stem(x) for x in group if " " not in x}:
            alts |= {norm(x) for x in group}
    parts = []
    for a in alts:
        s = stem(a) if " " not in a else a
        parts.append(re.escape(s))
    return r"\b(?:" + "|".join(sorted(parts, key=len, reverse=True)) + ")"


def phrase_regexes(phrase):
    """One compiled regex per word of the phrase; the phrase matches when all of them match."""
    return [re.compile(word_pattern(w)) for w in re.findall(r"[\w+#.-]+", norm(phrase)) if w not in ("at", "in", "for", "and")]


def clean_company(name):
    n = norm(name)
    n = re.sub(r"\b(inc|llc|ltd|gmbh|corp|corporation|co|company|plc|sa|ag|the)\b\.?", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def company_terms(name):
    """Names a company may appear under in postings."""
    n = clean_company(name)
    return ALIASES.get(n, [n]) if n else []


def parse(query, explicit_companies, known):
    """-> {"roles": [phrase], "companies": [name]}
    `known` is a set of cleaned company names we may recognise without a cue word."""
    companies = [c.strip() for c in re.split(r"[,;]", explicit_companies or "") if c.strip()]
    roles = []
    for phrase in [p.strip() for p in re.split(r"[,\n;]", query or "") if p.strip()]:
        m = re.search(r"\s(?:@|at|for|within|from)\s+(.+)$", " " + phrase, re.I) or re.match(r"^@\s*(.+)$", phrase)
        if m:  # "software engineer at google"
            companies.append(m.group(1).strip())
            phrase = re.sub(r"\s*(?:@|\bat\b|\bfor\b|\bwithin\b|\bfrom\b)\s+.+$", "", phrase, flags=re.I).strip()
        else:  # "software engineering google": a known company as first/last 1-3 words
            words = phrase.split()
            found = None
            for n in (3, 2, 1):
                if len(words) > n:  # something must remain as the role
                    for cand, rest in ((" ".join(words[-n:]), words[:-n]), (" ".join(words[:n]), words[n:])):
                        c = clean_company(cand)
                        if c and c in known and c not in GENERIC and not (n == 1 and len(c) < 3):
                            found = (cand, rest)
                            break
                if found:
                    break
            if found:
                companies.append(found[0])
                phrase = " ".join(found[1])
        if phrase.strip():
            roles.append(phrase.strip())
        elif not roles and not phrase.strip():
            pass
    # lone company, e.g. query "google"
    if not companies and len(roles) == 1:
        c = clean_company(roles[0])
        if c in known and c not in GENERIC:
            companies.append(roles.pop())
    dedup = list(dict.fromkeys(c for c in companies if c))
    return {"roles": roles, "companies": dedup}


def company_matches(job_company, targets):
    """True when the job's company is one of `targets` (list of raw names)."""
    jc = " " + clean_company(job_company) + " "
    for t in targets:
        for term in company_terms(t):
            if term and (" " + term + " ") in jc or (term and jc.strip().startswith(term + " ")) or jc.strip() == term:
                return True
    return False
