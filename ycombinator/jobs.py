"""/y-combinator/jobs/* — Work at a Startup postings as ycombinator.com
shows them to visitors: search across the role / location listing pages
(YC has no public cross-site job search; each listing page carries 20-50
postings and no paging), and one posting in full.

Search strategy: the pages fetched depend on the filters —
  role + known location  /jobs/role/<role>/<location>
  role                   /jobs/role/<role>
  known location         /jobs/location/<location>
  neither                every role page (9) in parallel
plus /jobs?query=… (the site's own 20 relevance hits) whenever a query is
given; `?query=` is also appended to the role pages, which re-rank on it.
Rows are de-duplicated by id, then filtered, sorted and paged locally.
"""
import re

from ycombinator import parsers as P
from ycombinator import refs
from ycombinator.fetch import YCNotFound, YCUpstreamError, or_not_found, page_props, run_parallel, soft, waas_props

ROLE_PAGES = {"eng": "software-engineer", "design": "designer", "product": "product-manager",
              "recruiting": "recruiting-hr", "sales": "sales-manager", "marketing": "marketing",
              "support": "support", "operations": "operations", "science": "science"}
LOCATION_PAGES = {"san-francisco": "san-francisco", "sf": "san-francisco", "san francisco": "san-francisco",
                  "bay area": "san-francisco", "new-york": "new-york", "new york": "new-york", "nyc": "new-york",
                  "los-angeles": "los-angeles", "los angeles": "los-angeles", "la": "los-angeles",
                  "seattle": "seattle", "austin": "austin", "chicago": "chicago", "india": "india",
                  "bangalore": "india", "bengaluru": "india"}
_AGO_RE = re.compile(r"(?:about|over|almost|less than)?\s*(\d+|an?)\s*(minute|hour|day|week|month|year)s?", re.I)
_AGO_UNITS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}


def _ago_days(value):
    """'6 days' | 'about 1 year' | 'less than a minute' -> days (float)."""
    match = _AGO_RE.search(value or "")
    if not match:
        return None
    amount = match.group(1).lower()
    amount = 1 if amount in ("a", "an") else int(amount)
    return amount * _AGO_UNITS[match.group(2).lower()]


def _postings(path, params=None):
    component, props, final = page_props(path, params=params, label=f"jobs {path}")
    rows = props.get("jobPostings") if isinstance(props.get("jobPostings"), list) else []
    return [P.job_card(r) for r in rows if isinstance(r, dict)], props


def _pages_for(role, location, query):
    params = {"query": query} if query else None
    location_slug = LOCATION_PAGES.get((location or "").strip().lower())
    pages = []
    if role and role in ROLE_PAGES:
        base = f"/jobs/role/{ROLE_PAGES[role]}"
        pages.append((base + (f"/{location_slug}" if location_slug else ""), params))
    elif location_slug:
        pages.append((f"/jobs/location/{location_slug}", params))
    else:
        pages.extend((f"/jobs/role/{slug}", params) for slug in ROLE_PAGES.values())
    if query:
        pages.append(("/jobs", {"query": query}))
    return pages


def _in_location(job, location_slug):
    """A /jobs?query= hit (that page is not scoped to a location) against a
    known location: its location text must name the place."""
    loc = (job.get("location") or "").lower()
    names = {alias.replace("-", " ") for alias, slug in LOCATION_PAGES.items() if slug == location_slug and len(alias) > 2}
    return any(name in loc for name in names)


def _matches(job, query, role, location, job_type, is_remote, batch_codes, skills, min_salary, has_salary,
             has_equity, visa, min_experience):
    blob = " ".join(filter(None, [job.get("title"), (job.get("company") or {}).get("name"),
                                  (job.get("company") or {}).get("one_liner"), job.get("location"),
                                  (job.get("role") or {}).get("specialty"), " ".join(job.get("skills") or [])])).lower()
    if query and not all(term in blob for term in query.lower().split()):
        return False
    if role and (job.get("role") or {}).get("category") != role:
        return False
    loc = (job.get("location") or "").lower()
    if location and location.strip().lower() not in LOCATION_PAGES and location.strip().lower() not in loc:
        return False
    if job_type and job_type.replace("-", " ") not in (job.get("job_type") or "").lower().replace("-", " "):
        return False
    if is_remote is not None and ("remote" in loc) != is_remote:
        return False
    if batch_codes and ((job.get("company") or {}).get("batch") or {}).get("code") not in batch_codes:
        return False
    if skills:
        have = {s.lower() for s in job.get("skills") or []}
        if not any(s.lower() in have for s in skills):
            return False
    salary = job.get("salary") or {}
    if min_salary is not None and (salary.get("max") or salary.get("min") or 0) < min_salary:
        return False
    if has_salary is not None and bool(salary.get("min")) != has_salary:
        return False
    equity = job.get("equity") or {}
    if has_equity is not None and bool(equity.get("max_percent") or equity.get("min_percent")) != has_equity:
        return False
    if visa and visa.lower() not in (job.get("visa") or "").lower():
        return False
    if min_experience and min_experience.lower().replace(" ", "") not in (job.get("min_experience") or "").lower().replace(" ", ""):
        return False
    return True


def _sort(rows, key):
    if key == "newest":
        return sorted(rows, key=lambda j: (_ago_days(j.get("posted_ago")) if _ago_days(j.get("posted_ago")) is not None else 1e9,
                                           j.get("title") or ""))
    if key == "salary":
        return sorted(rows, key=lambda j: -((j.get("salary") or {}).get("max") or (j.get("salary") or {}).get("min") or 0))
    return rows


def search(query=None, role=None, location=None, job_type=None, is_remote=None, batch=None, skill=None,
           min_salary=None, has_salary=None, has_equity=None, visa=None, min_experience=None, sort="relevance",
           page=1, per_page=20):
    pages = _pages_for(role, location, query)
    results = run_parallel([soft(lambda p=p: _postings(p[0], p[1]), default=None) for p in pages])
    if all(r is None for r in results):
        # every listing page failed: an error, not an empty (and cached) result
        raise YCUpstreamError(f"jobs search: every listing page failed ({', '.join(path for path, _ in pages)})")
    location_slug = LOCATION_PAGES.get((location or "").strip().lower())
    seen, rows, facets, unscoped = set(), [], {}, set()
    for (path, _), result in zip(pages, results):
        found, props = result or ([], {})
        if props and not facets:
            facets = {
                "roles": [P.slug_name(r) for r in props.get("jobRoles") or [] if isinstance(r, dict)],
                "locations": [P.slug_name(l) for l in props.get("jobLocations") or [] if isinstance(l, dict)],
                "role_categories": [P.job_role_option(r) for r in props.get("roleOptions") or [] if isinstance(r, dict)],
            }
        for job in found:
            if job.get("id") in seen:
                continue
            seen.add(job.get("id"))
            rows.append(job)
            if location_slug and path == "/jobs":
                unscoped.add(len(rows) - 1)
    codes = {b["code"] for b in batch} if batch else None
    matched = [j for i, j in enumerate(rows)
               if (i not in unscoped or _in_location(j, location_slug))
               and _matches(j, query, role, location, job_type, is_remote, codes, skill, min_salary,
                            has_salary, has_equity, visa, min_experience)]
    matched = _sort(matched, sort)
    start = (page - 1) * per_page
    return {
        "query": query,
        "filters": {"role": role, "location": location, "job_type": job_type, "is_remote": is_remote,
                    "batch": sorted(codes) if codes else None, "skill": skill, "min_salary": min_salary,
                    "has_salary": has_salary, "has_equity": has_equity, "visa": visa,
                    "min_experience": min_experience, "sort": sort},
        "sources": [f"https://www.ycombinator.com{path}" + (f"?query={params['query']}" if params else "")
                    for path, params in pages],
        "facets": facets,
        "pagination": P.pagination(page, per_page, len(matched)),
        "jobs": matched[start:start + per_page],
    }


# ---- one posting ---------------------------------------------------------------------

def _yc_posting(company, job_hash):
    missing = f"job '{company}/{job_hash}' not found on Work at a Startup (closed, or the company / hash is wrong)"
    component, props, final = or_not_found(lambda: page_props(f"/companies/{company}/jobs/{job_hash}",
                                                              label=f"job {company}/{job_hash}"), missing)
    if "WaasShowJobPage" not in component or not isinstance(props.get("job"), dict):
        raise YCNotFound(missing)
    return P.job_from_page(props)


def _waas_posting(job_id):
    missing = f"job '{job_id}' not found on Work at a Startup (closed, or the id is wrong)"
    component, props, final = or_not_found(lambda: waas_props(f"/jobs/{job_id}", label=f"waas job {job_id}"), missing)
    if not isinstance(props.get("job"), dict):
        raise YCNotFound(missing)
    return P.job_from_waas(props)


def _hash_for(job_id, company_slug):
    """The YC posting hash of a numeric id, from the company's jobs page."""
    component, props, final = page_props(f"/companies/{company_slug}/jobs", label=f"company jobs {company_slug}")
    for raw in props.get("jobPostings") or []:
        if isinstance(raw, dict) and P.to_int(raw.get("id")) == job_id:
            return P.job_card(raw).get("hash")
    return None


def details(job):
    """One posting in full. A YC link / <company>/<hash> reads the YC
    posting page (markdown description, interview process, hiring manager,
    related jobs, application questions) and the Work at a Startup page
    (HTML twin, the company's hiring / tech blurbs, other open roles,
    similar jobs); a bare id starts from Work at a Startup and finds the YC
    page through the company's jobs list."""
    if job.get("hash"):
        yc = _yc_posting(job["company"], job["hash"])
        waas = soft(lambda: _waas_posting(yc["id"]), default=None)() if yc.get("id") else None
    else:
        waas = _waas_posting(job["id"])
        slug = (waas.get("company") or {}).get("slug")
        job_hash = soft(lambda: _hash_for(job["id"], slug), default=None)() if slug else None
        yc = soft(lambda: _yc_posting(slug, job_hash), default=None)() if job_hash else None
    return {"job": _merge(yc, waas)}


def _with_html(block, twin):
    """The YC markdown block + the Work at a Startup HTML twin -> one block
    {markdown, text, html}."""
    if not block and not twin:
        return None
    out = dict(block or {"markdown": None, "text": (twin or {}).get("text")})
    out["html"] = (twin or {}).get("html")
    return out


def _merge(yc, waas):
    if yc is None:
        return dict(waas, source="workatastartup.com")
    out = dict(yc)
    out["source"] = "ycombinator.com"
    if not waas:
        return out
    out["source"] += " + workatastartup.com"
    out["description"] = _with_html(out.get("description"), waas.get("description"))
    out["interview_process"] = _with_html(out.get("interview_process"), waas.get("interview_process"))
    out["other_jobs"] = waas.get("other_jobs") or []
    out["similar_jobs"] = waas.get("similar_jobs") or []
    company = waas.get("company") or {}
    out["company"]["hiring_description"] = company.get("hiring_description") or out["company"].get("hiring_description")
    out["company"]["tech_description"] = company.get("tech_description")
    out["company"]["work_at_a_startup_link"] = refs.waas_company_link(out["company"].get("slug"))
    if not out.get("custom_questions"):
        out["custom_questions"] = waas.get("custom_questions") or []
    return out
