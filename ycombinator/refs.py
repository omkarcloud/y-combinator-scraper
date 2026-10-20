"""Y Combinator reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair).

  company   airbnb (the directory slug) | 271 (the numeric company id)
            | https://www.ycombinator.com/companies/airbnb[/jobs…]
            | https://www.workatastartup.com/companies/airbnb
            | https://bookface.ycombinator.com/company/271
  founder   brian-chesky (the founder slug) | 21981 (the numeric user id)
            | https://www.ycombinator.com/founders/brian-chesky
  job       116108 (the numeric posting id)
            | https://www.workatastartup.com/jobs/116108
            | https://www.ycombinator.com/companies/coris/jobs/h0nDly8-backend-engineer
            | coris/h0nDly8  (company slug + the posting's short hash)
  launch    VrR-asakana-automating-sales… (the launch slug)
            | https://www.ycombinator.com/launches/VrR-asakana-…
  partner   garry-tan | https://www.ycombinator.com/people/garry-tan
  post      welcome-vivian-and-raphael | https://www.ycombinator.com/blog/welcome-vivian-and-raphael
  article   dx-ai-safety-fact-vs-fiction | https://www.ycombinator.com/library/dx-ai-safety-…
  batch     W24 | w24 | W2024 | "Winter 2024" | winter-2024 | X25 / P25 / "Spring 2025"
            | F26 / "Fall 2026" -> {"code": "W24", "name": "Winter 2024"}
"""
import re
from urllib.parse import unquote, urlparse

YC_HOSTS = {"ycombinator.com", "www.ycombinator.com", "bookface.ycombinator.com"}
WAAS_HOSTS = {"workatastartup.com", "www.workatastartup.com"}
ALL_HOSTS = YC_HOSTS | WAAS_HOSTS

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$", re.I)
HASH_RE = re.compile(r"^[A-Za-z0-9]{5,12}$")
NOT_SLUGS = {"industry", "location", "founders", "jobs", "launches", "people", "blog", "library",
             "women-founders", "black-founders", "hispanic-latino-founders", "directory"}

SEASONS = {"W": "Winter", "S": "Summer", "F": "Fall", "P": "Spring"}
SEASON_CODES = {"winter": "W", "summer": "S", "fall": "F", "autumn": "F", "spring": "P"}
_BATCH_CODE_RE = re.compile(r"^([WSFPX])\s*(\d{2}|\d{4})$", re.I)
_BATCH_NAME_RE = re.compile(r"^(winter|summer|fall|autumn|spring)[\s_-]*(\d{2}|\d{4})$", re.I)


def _is_url(value):
    low = value.lower()
    return low.startswith(("http://", "https://", "//")) or any(
        low.startswith(h + "/") or low == h for h in ALL_HOSTS)


def _parsed(value):
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith("http"):
        url = "https://" + url
    return urlparse(url)


def _segments(value, what):
    """A YC / Work at a Startup link -> (host, [path segments]). ValueError
    for another site."""
    parsed = _parsed(value)
    host = (parsed.hostname or "").lower()
    if host not in ALL_HOSTS:
        raise ValueError(f"{what} link must be a ycombinator.com or workatastartup.com link")
    return host, [unquote(s) for s in parsed.path.split("/") if s]


def _slug(value, what):
    slug = value.strip()
    if not SLUG_RE.match(slug) or slug.lower() in NOT_SLUGS or "/" in slug:
        raise ValueError(f"'{value}' is not a {what} slug")
    return slug


# ---- links ------------------------------------------------------------------------

def company_link(slug):
    return f"https://www.ycombinator.com/companies/{slug}" if slug else None


def company_jobs_link(slug):
    return f"https://www.ycombinator.com/companies/{slug}/jobs" if slug else None


def founder_link(slug):
    return f"https://www.ycombinator.com/founders/{slug}" if slug else None


def job_link(slug, job_hash):
    return f"https://www.ycombinator.com/companies/{slug}/jobs/{job_hash}" if slug and job_hash else None


def waas_job_link(job_id):
    return f"https://www.workatastartup.com/jobs/{job_id}" if job_id else None


def waas_company_link(slug):
    return f"https://www.workatastartup.com/companies/{slug}" if slug else None


def launch_link(slug):
    return f"https://www.ycombinator.com/launches/{slug}" if slug else None


def partner_link(slug):
    return f"https://www.ycombinator.com/people/{slug}" if slug else None


def post_link(slug):
    return f"https://www.ycombinator.com/blog/{slug}" if slug else None


def article_link(slug):
    return f"https://www.ycombinator.com/library/{slug}" if slug else None


def absolute(path):
    """A site-relative href ('/companies/coris') -> absolute; absolute and
    protocol-relative links pass through; anything else -> None."""
    if not isinstance(path, str) or not path.strip():
        return None
    path = path.strip()
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("http"):
        return path
    if path.startswith("/"):
        return "https://www.ycombinator.com" + path
    return None


# ---- resolvers ----------------------------------------------------------------------

def resolve_company(value):
    """Slug, numeric id or any YC / Work at a Startup company link -> the
    path token (slug or id) the company page accepts."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("company is required")
    if _is_url(value):
        host, segments = _segments(value, "company")
        if len(segments) >= 2 and segments[0] in ("companies", "company") and segments[1] not in NOT_SLUGS:
            return _slug(segments[1], "company")
        if len(segments) >= 2 and segments[0] == "founders":
            raise ValueError("that is a founder link — pass it to the founders endpoints")
        raise ValueError("company link must look like https://www.ycombinator.com/companies/airbnb")
    if value.isdigit():
        return value
    return _slug(value, "company")


def resolve_founder(value):
    """Founder slug, numeric user id or a /founders/<slug> link ->
    {"slug": str | None, "id": int | None}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("founder is required")
    if _is_url(value):
        host, segments = _segments(value, "founder")
        if len(segments) >= 2 and segments[0] == "founders":
            return {"slug": _slug(segments[1], "founder"), "id": None}
        raise ValueError("founder link must look like https://www.ycombinator.com/founders/brian-chesky")
    if value.isdigit():
        return {"slug": None, "id": int(value)}
    if " " in value:
        raise ValueError("founder must be a founder slug (brian-chesky), a numeric id or a /founders/ link; "
                         "to look a founder up by name use /founders/search?query=")
    return {"slug": _slug(value, "founder").lower(), "id": None}


def resolve_job(value):
    """Posting id, Work at a Startup link, YC posting link or
    '<company>/<hash>' -> {"id": int | None, "company": str | None,
    "hash": str | None}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("job is required")
    if _is_url(value):
        host, segments = _segments(value, "job")
        if host in WAAS_HOSTS and len(segments) >= 2 and segments[0] == "jobs" and segments[1].isdigit():
            return {"id": int(segments[1]), "company": None, "hash": None}
        if len(segments) >= 4 and segments[0] == "companies" and segments[2] == "jobs":
            job_hash = segments[3].split("-", 1)[0]
            if HASH_RE.match(job_hash):
                return {"id": None, "company": _slug(segments[1], "company"), "hash": job_hash}
        raise ValueError("job link must look like https://www.ycombinator.com/companies/<company>/jobs/<id>-<title> "
                         "or https://www.workatastartup.com/jobs/<id>")
    if value.isdigit():
        return {"id": int(value), "company": None, "hash": None}
    if "/" in value:
        company, _, rest = value.partition("/")
        job_hash = rest.split("-", 1)[0]
        if company and HASH_RE.match(job_hash):
            return {"id": None, "company": _slug(company, "company"), "hash": job_hash}
    raise ValueError("job must be a posting id (116108), a Work at a Startup link, a YC posting link or <company>/<hash>")


def _slug_from(value, what, marker, example):
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{what} is required")
    if _is_url(value):
        host, segments = _segments(value, what)
        if len(segments) >= 2 and segments[0] == marker:
            return _slug(segments[1].split("?")[0], what)
        raise ValueError(f"{what} link must look like {example}")
    return _slug(value.split("?")[0], what)


def resolve_launch(value):
    return _slug_from(value, "launch", "launches", "https://www.ycombinator.com/launches/<slug>")


def resolve_partner(value):
    return _slug_from(value, "partner", "people", "https://www.ycombinator.com/people/garry-tan").lower()


def resolve_post(value):
    return _slug_from(value, "post", "blog", "https://www.ycombinator.com/blog/<slug>")


def resolve_article(value):
    return _slug_from(value, "article", "library", "https://www.ycombinator.com/library/<slug>")


# ---- batches ------------------------------------------------------------------------

def normalize_batch(value):
    """Any spelling of a batch -> {"code": "W24", "name": "Winter 2024"}.
    Accepts W24 / w24 / W2024 / "Winter 2024" / winter-2024 / X25 (YC's
    older code for Spring 2025, canonical P25) / F26 / "Fall 2026".
    ValueError for anything else."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("batch is required")
    match = _BATCH_CODE_RE.match(raw.replace(" ", ""))
    if match:
        season, year = match.group(1).upper(), match.group(2)
        season = "P" if season == "X" else season
    else:
        match = _BATCH_NAME_RE.match(raw)
        if not match:
            raise ValueError(f"'{value}' is not a YC batch (use W24, S23, F26, X25 or 'Winter 2024')")
        season, year = SEASON_CODES[match.group(1).lower()], match.group(2)
    year = int(year)
    if year < 100:
        year += 2000
    if not 2005 <= year <= 2099:
        raise ValueError(f"'{value}' is not a YC batch year")
    code = f"{season}{year % 100:02d}"
    return {"code": code, "name": f"{SEASONS[season]} {year}"}


def batch_code(name_or_code):
    """'Winter 2024' / 'W24' / 'w2024' -> 'W24'; None when unparseable."""
    try:
        return normalize_batch(name_or_code)["code"]
    except ValueError:
        return None


def batch_name(name_or_code):
    """'W24' / 'Winter 2024' -> 'Winter 2024'; None when unparseable."""
    try:
        return normalize_batch(name_or_code)["name"]
    except ValueError:
        return None


def batch_block(value):
    """Upstream batch spelling -> {"code", "name"} (both None when absent or
    'Unspecified')."""
    if not value or str(value).strip().lower() == "unspecified":
        return {"code": None, "name": None}
    try:
        return normalize_batch(value)
    except ValueError:
        return {"code": None, "name": str(value).strip()}


def resolve_batches(value):
    """Comma-separated batches -> [{"code", "name"}, …] (deduped)."""
    out = []
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        block = normalize_batch(raw)
        if block not in out:
            out.append(block)
    if not out:
        raise ValueError("batch is required")
    if len(out) > 10:
        raise ValueError("at most 10 batches per call")
    return out
