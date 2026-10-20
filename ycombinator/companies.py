"""/y-combinator/companies/* — the startup directory: Algolia search (+ the
top-companies and newest views), one company's full profile, its open
jobs, founders and launches, the curated industry / location lists, YC's
open-API directory dump and the women / black / hispanic-latino founder
highlight lists.
"""
import re

from ycombinator import directory
from ycombinator import parsers as P
from ycombinator import refs
from ycombinator.fetch import YCNotFound, api_companies, or_not_found, page_props, run_parallel, soft, waas_props

API_DEFAULT_PAGE_SIZE = 25
LIST_PAGE_SIZE = 50
_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9]+")


# ---- search views --------------------------------------------------------------------

def search(**params):
    return directory.company_search(**params)


def top(query=None, batch=None, industry=None, page=1, per_page=20):
    """The companies YC marks as top companies."""
    out = directory.company_search(query=query, batch=batch, industry=industry, is_top_company=True,
                                   page=page, per_page=per_page)
    out["filters"] = {"batch": out["filters"]["batch"], "industry": industry}
    return out


def new(since, batch=None, industry=None, tag=None, region=None, page=1, per_page=20):
    """Companies by launch date (newest first) that launched since `since`."""
    out = directory.company_search(batch=batch, industry=industry, tag=tag, region=region, launched_since=since,
                                   sort="newest", page=page, per_page=per_page)
    out.pop("query", None)
    out["since"] = since
    out["filters"] = {k: out["filters"][k] for k in ("batch", "industry", "tag", "region")}
    return out


# ---- one company ------------------------------------------------------------------------

def _profile(company):
    """The /companies/<slug-or-id> page -> (profile, props)."""
    missing = f"company '{company}' not found in the Y Combinator directory"
    component, props, final = or_not_found(lambda: page_props(f"/companies/{company}", label=f"company {company}"), missing)
    if "Companies/ShowPage" not in component or not isinstance(props.get("company"), dict):
        raise YCNotFound(missing)
    return P.company_from_page(props), props


def _index_extras(slug, profile):
    """What only the search index knows about a company (hiring flag,
    regions, stage, launch date, former names, industries)."""
    hit = directory.company_lookup(slug) or directory.company_lookup(str(profile.get("id") or ""))
    if not hit:
        return {}
    extras = {k: hit.get(k) for k in ("former_names", "launched_at", "stage", "industries", "primary_industry",
                                      "subindustry", "is_hiring", "is_top_company", "is_nonprofit",
                                      "has_demo_day_video", "has_app_video")}
    extras["regions"] = (hit.get("location") or {}).get("regions") or []
    return extras


def details(company):
    """Full profile: the company page (founders, photos, news, launches,
    open jobs, group partner, socials) + the index facts (hiring flag,
    regions, stage, launch date) + the Work at a Startup blurbs."""
    profile, props = _profile(company)
    slug = profile["slug"] or company
    extras, waas = run_parallel([
        soft(lambda: _index_extras(slug, profile), default={}),
        soft(lambda: P.company_from_waas(waas_props(f"/companies/{slug}")[1].get("company")), default=None),
    ])
    extras = extras or {}
    profile["location"]["regions"] = extras.pop("regions", [])
    for key in ("former_names", "launched_at", "stage", "industries", "primary_industry", "subindustry",
                "is_hiring", "is_top_company", "is_nonprofit", "has_demo_day_video", "has_app_video"):
        profile[key] = extras.get(key, [] if key in ("former_names", "industries") else None)
    waas = waas or {}
    profile["hiring_description"] = waas.get("hiring_description")
    profile["tech_description"] = waas.get("tech_description")
    past = {f.get("name"): f.get("past_companies") for f in waas.get("founders") or []}
    for founder in profile.get("founders") or []:
        founder["past_companies"] = past.get(founder.get("name"))
    return {"company": profile}


def jobs(company):
    """Every open role of one company (the /companies/<slug>/jobs page)."""
    missing = f"company '{company}' not found in the Y Combinator directory"
    component, props, final = or_not_found(lambda: page_props(f"/companies/{company}/jobs", label=f"company jobs {company}"), missing)
    raw = props.get("company") if isinstance(props.get("company"), dict) else None
    if not raw:
        raise YCNotFound(missing)
    block = P.company_from_list_row(raw)
    block.pop("logo_large", None)
    hiring = P.plain(raw.get("hiring_description"))
    block["hiring_description"] = {"html": None, "text": hiring} if hiring else None
    block["shows_founder_contact"] = P.flag(raw.get("show_founder_contact"))
    block["work_at_a_startup_link"] = refs.waas_company_link(block["slug"])
    ref = {"id": block["id"], "slug": block["slug"], "name": block["name"], "link": block["link"]}
    rows = [P.job_card(j, ref) for j in props.get("jobPostings") or [] if isinstance(j, dict)]
    return {"company": block, "jobs_count": len(rows), "jobs": rows,
            "testimonials": [t for t in props.get("testimonials") or []] if isinstance(props.get("testimonials"), list) else []}


def founders(company):
    """A company's founders: the profile's founder blocks (bio, title,
    socials) merged with the founders index (slug, HN username, batches)
    and Work at a Startup (past companies)."""
    profile, props = _profile(company)
    slug = profile["slug"]
    hits, waas = run_parallel([
        soft(lambda: directory.founders_of_company(slug, profile.get("name")), default=[]),
        soft(lambda: P.company_from_waas(waas_props(f"/companies/{slug}")[1].get("company")), default=None),
    ])
    by_name = {(h.get("name") or "").lower(): h for h in hits or []}
    past = {(f.get("name") or "").lower(): f.get("past_companies") for f in (waas or {}).get("founders") or []}
    out = []
    for founder in profile.get("founders") or []:
        key = (founder.get("name") or "").lower()
        hit = by_name.get(key) or {}
        row = {
            "id": founder.get("id") or hit.get("id"),
            "slug": hit.get("slug"),
            "name": founder.get("name"),
            "link": hit.get("link"),
            "avatar": hit.get("avatar") or founder.get("avatar"),
            "hacker_news_username": hit.get("hacker_news_username"),
            "title": founder.get("title") or hit.get("title"),
            "titles": hit.get("titles") or [],
            "bio": founder.get("bio"),
            "past_companies": past.get(key),
            "is_active": founder.get("is_active"),
            "has_email": founder.get("has_email"),
            "batches": hit.get("batches") or [profile["batch"]] if profile.get("batch", {}).get("code") else hit.get("batches") or [],
            "region": hit.get("region"),
            "is_top_company": hit.get("is_top_company", profile.get("is_top_company")),
            "social": founder.get("social"),
        }
        out.append(row)
    company_block = {k: profile.get(k) for k in ("id", "slug", "name", "link", "batch", "one_liner", "logo", "website")}
    return {"company": company_block, "founders_count": len(out), "founders": out}


def launches(company):
    """A company's Launch YC posts (full bodies, from its profile page)."""
    profile, props = _profile(company)
    company_block = {k: profile.get(k) for k in ("id", "slug", "name", "link", "batch", "one_liner", "logo", "website")}
    rows = profile.get("launches") or []
    return {"company": company_block, "launches_count": len(rows), "launches": rows}


# ---- curated lists --------------------------------------------------------------------------

def _list_slug(value):
    value = str(value or "").strip().lower()
    if value.startswith("http"):
        value = value.rstrip("/").rsplit("/", 1)[-1]
    return _SLUG_CLEAN_RE.sub("-", value).strip("-")


def browse(industry=None, location=None, hiring_only=False, page=1):
    """The curated SEO lists: /companies/industry/<slug>[/<location>][/hiring]
    and /companies/location/<slug>[/hiring] — 50 companies a page with
    socials and founding year (fields the search index lacks). The HTML
    page's Inertia props (not the JSON variant) carry the list's title,
    description and total."""
    if not industry and not location:
        raise ValueError("pass industry (e.g. fintech, b2b, healthcare) and/or location "
                         "(e.g. san-francisco-bay-area, new-york, india, london)")
    industry_slug, location_slug = _list_slug(industry), _list_slug(location)
    if industry_slug:
        path = f"/companies/industry/{industry_slug}" + (f"/{location_slug}" if location_slug else "")
    else:
        path = f"/companies/location/{location_slug}"
    if hiring_only:
        path += "/hiring"
    component, doc, final = page_props(path, params={"page": page} if page > 1 else None, label=f"company list {path}")
    if "CompanyListPage" not in component or not isinstance(doc.get("companies"), list):
        raise YCNotFound(f"no curated list at {path}")
    rows = [P.company_from_list_row(c) for c in doc["companies"] if isinstance(c, dict)]
    total_pages = P.to_int(doc.get("totalPages")) or 0
    if not rows and page == 1:
        raise YCNotFound(f"Y Combinator has no curated list for industry={industry!r} location={location!r}"
                         + (" (hiring only)" if hiring_only else "") + "; see /y-combinator/filters for the slugs")
    return {
        "list": {
            "title": P.text(doc.get("title")),
            "description": P.text(doc.get("description")),
            "industry": {"slug": P.text(doc.get("industrySlug")) or industry_slug or None, "name": P.text(doc.get("industryName"))},
            "location": {"slug": P.text(doc.get("locationSlug")) or location_slug or None, "name": P.text(doc.get("locationName"))},
            "is_hiring_only": bool(doc.get("hiring")) or bool(hiring_only),
            "link": f"https://www.ycombinator.com{path}",
        },
        "pagination": P.pagination(page, LIST_PAGE_SIZE, _count_from_description(doc.get("description")),
                                   total_pages=total_pages),
        "companies": rows,
    }


def _count_from_description(description):
    match = re.search(r"Browse\s+([\d,]+)", description or "")
    return int(match.group(1).replace(",", "")) if match else None


def directory_dump(query=None, batch=None, status=None, industry=None, tag=None, region=None, is_hiring=None,
                   is_nonprofit=None, is_top_company=None, page=1):
    """YC's own open API (api.ycombinator.com/v0.1/companies): the whole
    directory for bulk export, 25 rows a page (20 when a filter is set)."""
    params = {"page": page}
    if query:
        params["q"] = query
    if batch:
        params["batch"] = batch["code"]
    if status:
        params["status"] = status.capitalize()
    if industry:
        params["industries"] = directory.canonical("companies", "industries", industry)
    if tag:
        params["tags"] = directory.canonical("companies", "tags", tag)
    if region:
        params["regions"] = directory.canonical("companies", "regions", region)
    if is_hiring is not None:
        params["isHiring"] = "true" if is_hiring else "false"
    if is_nonprofit is not None:
        params["nonprofit"] = "true" if is_nonprofit else "false"
    if is_top_company:
        params["top_company"] = "true"
    doc = api_companies(params)
    rows = [P.company_from_api(c) for c in doc.get("companies") or [] if isinstance(c, dict)]
    total_pages = P.to_int(doc.get("totalPages")) or 0
    per_page = len(rows) if rows and page < total_pages else (20 if len(params) > 1 else API_DEFAULT_PAGE_SIZE)
    return {
        "query": query,
        "filters": {"batch": batch["code"] if batch else None, "status": status, "industry": params.get("industries"),
                    "tag": params.get("tags"), "region": params.get("regions"), "is_hiring": is_hiring,
                    "is_nonprofit": is_nonprofit, "is_top_company": is_top_company},
        "source": "https://api.ycombinator.com/v0.1/companies",
        "pagination": P.pagination(page, per_page, None, total_pages=total_pages),
        "companies": rows,
    }


# ---- highlight lists --------------------------------------------------------------------------

_HIGHLIGHT_TITLES = {"women-founders": "Companies founded by women", "black-founders": "Companies with Black founders",
                     "hispanic-latino-founders": "Companies with Hispanic & Latino founders"}


def highlights(group, query=None, batch=None, page=1, per_page=20):
    """The three founder-highlight directories, filtered and paged locally
    (the page ships the whole list)."""
    component, props, final = page_props(f"/companies/{group}", label=f"highlights {group}")
    rows = [P.company_from_list_row(c) for c in props.get("companies") or [] if isinstance(c, dict)]
    needle = (query or "").lower()
    codes = {b["code"] for b in batch} if batch else None
    matched = []
    for row in rows:
        if needle and needle not in " ".join(filter(None, [row.get("name"), row.get("one_liner"), row.get("description"),
                                                             " ".join(row.get("tags") or [])])).lower():
            continue
        if codes and (row.get("batch") or {}).get("code") not in codes:
            continue
        matched.append(row)
    start = (page - 1) * per_page
    stats = props.get("bigStats") if isinstance(props.get("bigStats"), list) else []
    return {
        "group": group,
        "title": P.text(props.get("listHeader")) or _HIGHLIGHT_TITLES.get(group),
        "link": f"https://www.ycombinator.com/companies/{group}",
        "stats": [{"label": P.text(s[1]) if len(s) > 1 else None, "value": s[0]} if isinstance(s, list) and s else s
                  for s in stats],
        "query": query,
        "filters": {"batch": [b["code"] for b in batch] if batch else None},
        "pagination": P.pagination(page, per_page, len(matched)),
        "companies": matched[start:start + per_page],
    }
