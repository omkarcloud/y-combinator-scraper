"""The Algolia-backed directory searches (companies + founders) and the
facet vocabulary they filter on.

Facet values are canonicalized against the live vocabulary (cached
in-process for FACET_TTL seconds): `industry=fintech` becomes the
"Fintech" the index knows, `region=united kingdom` becomes "United
Kingdom"; an unknown value is passed through verbatim (it just matches
nothing) rather than rejected, so a brand-new tag works the day YC adds
it. /y-combinator/filters exposes the vocabulary.
"""
import threading
import time

from ycombinator import parsers as P
from ycombinator import refs
from ycombinator.fetch import COMPANY_BY_LAUNCH_INDEX, COMPANY_INDEX, FOUNDER_INDEX, algolia_search

FACET_TTL = 3600
COMPANY_FACETS = ["batch", "industries", "industry", "subindustry", "tags", "regions", "status", "isHiring",
                  "top_company", "nonprofit", "app_video_public", "demo_day_video_public"]
FOUNDER_FACETS = ["batches", "yc_titles", "yc_parent_industries", "yc_subindustries", "current_region", "top_company"]
PAGINATION_LIMIT = 1000   # Algolia's paginationLimitedTo on these indices

_facets = {}
_facets_lock = threading.Lock()


def _epoch(iso):
    """'2026-10-01T00:00:00Z' -> unix seconds."""
    from datetime import datetime, timezone
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())


def facets(kind="companies", force=False):
    """{facet name: {value: count}} for the companies or founders index."""
    now = time.time()
    with _facets_lock:
        cached = _facets.get(kind)
        if cached and not force and cached[1] > now:
            return cached[0]
    if kind == "companies":
        result = algolia_search(COMPANY_INDEX, {"query": "", "hitsPerPage": 0, "facets": COMPANY_FACETS,
                                                "maxValuesPerFacet": 1000}, kind="companies")
    else:
        result = algolia_search(FOUNDER_INDEX, {"query": "", "hitsPerPage": 0, "facets": FOUNDER_FACETS,
                                                "maxValuesPerFacet": 1000}, kind="founders")
    values = result.get("facets") or {}
    values["_total"] = result.get("nbHits")
    with _facets_lock:
        _facets[kind] = (values, now + FACET_TTL)
    return values


def canonical(kind, facet, value):
    """The index's own spelling of a facet value (case-insensitive match),
    else the value as given."""
    if value is None:
        return None
    try:
        known = facets(kind).get(facet) or {}
    except Exception:
        return value
    low = str(value).strip().lower()
    for candidate in known:
        if candidate.lower() == low:
            return candidate
    # a subindustry may be given without its parent ("Infrastructure" for "B2B -> Infrastructure")
    if facet in ("subindustry", "yc_subindustries"):
        for candidate in known:
            if "->" in candidate and candidate.split("->", 1)[1].strip().lower() == low:
                return candidate
    return value


def _or_group(facet, values, kind):
    return [f"{facet}:{canonical(kind, facet, v)}" for v in values] if values else None


def _bool_group(facet, value):
    return [f"{facet}:{'true' if value else 'false'}"] if value is not None else None


def _groups(*groups):
    return [g for g in groups if g]


def _page_window(result, page, per_page):
    total = P.to_int(result.get("nbHits")) or 0
    total_pages = P.to_int(result.get("nbPages")) or 0
    return P.pagination(page, per_page, total, total_pages=total_pages)


# ---- companies ------------------------------------------------------------------------

def company_search(query=None, batch=None, industry=None, subindustry=None, tag=None, region=None, status=None,
                   is_hiring=None, is_top_company=None, is_nonprofit=None, has_demo_day_video=None,
                   has_app_video=None, team_size_min=None, team_size_max=None, launched_since=None,
                   sort="relevance", page=1, per_page=20):
    facet_filters = _groups(
        _or_group("batch", [b["name"] for b in batch] if batch else None, "companies"),
        _or_group("industries", industry, "companies"),
        _or_group("subindustry", subindustry, "companies"),
        _or_group("tags", tag, "companies"),
        _or_group("regions", region, "companies"),
        _or_group("status", [status.capitalize()] if status else None, "companies"),
        _bool_group("isHiring", is_hiring),
        _bool_group("top_company", is_top_company),
        _bool_group("nonprofit", is_nonprofit),
        _bool_group("demo_day_video_public", has_demo_day_video),
        _bool_group("app_video_public", has_app_video),
    )
    numeric = []
    if team_size_min is not None:
        numeric.append(f"team_size>={team_size_min}")
    if team_size_max is not None:
        numeric.append(f"team_size<={team_size_max}")
    if launched_since:
        numeric.append(f"launched_at>={_epoch(launched_since)}")
    params = {"query": query or "", "hitsPerPage": per_page, "page": page - 1}
    if facet_filters:
        params["facetFilters"] = facet_filters
    if numeric:
        params["numericFilters"] = numeric
    index = COMPANY_BY_LAUNCH_INDEX if sort == "newest" else COMPANY_INDEX
    result = algolia_search(index, params, kind="companies")
    return {
        "query": query,
        "filters": {
            "batch": [b["code"] for b in batch] if batch else None,
            "industry": industry, "subindustry": subindustry, "tag": tag, "region": region, "status": status,
            "is_hiring": is_hiring, "is_top_company": is_top_company, "is_nonprofit": is_nonprofit,
            "has_demo_day_video": has_demo_day_video, "has_app_video": has_app_video,
            "team_size_min": team_size_min, "team_size_max": team_size_max, "launched_since": launched_since,
            "sort": sort,
        },
        "pagination": _page_window(result, page, per_page),
        "companies": [P.company_from_hit(h) for h in result.get("hits") or [] if isinstance(h, dict)],
    }


def company_lookup(value):
    """One company by slug or numeric id from the index -> card or None."""
    value = str(value or "").strip()
    if not value:
        return None
    if value.isdigit():
        params = {"query": "", "hitsPerPage": 1, "filters": f"objectID:{value}"}
    else:
        params = {"query": value.replace("-", " "), "hitsPerPage": 5}
    result = algolia_search(COMPANY_INDEX, params, kind="companies")
    for hit in result.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        if value.isdigit() or str(hit.get("slug") or "").lower() == value.lower():
            return P.company_from_hit(hit)
    return None


# ---- founders ------------------------------------------------------------------------

def founder_search(query=None, batch=None, title=None, industry=None, subindustry=None, region=None,
                   is_top_company=None, page=1, per_page=20):
    facet_filters = _groups(
        _or_group("batches", [b["code"] for b in batch] if batch else None, "founders"),
        _or_group("yc_titles", title, "founders"),
        _or_group("yc_parent_industries", industry, "founders"),
        _or_group("yc_subindustries", subindustry, "founders"),
        _or_group("current_region", region, "founders"),
        _bool_group("top_company", is_top_company),
    )
    params = {"query": query or "", "hitsPerPage": per_page, "page": page - 1}
    if facet_filters:
        params["facetFilters"] = facet_filters
    result = algolia_search(FOUNDER_INDEX, params, kind="founders")
    return {
        "query": query,
        "filters": {
            "batch": [b["code"] for b in batch] if batch else None,
            "title": title, "industry": industry, "subindustry": subindustry, "region": region,
            "is_top_company": is_top_company,
        },
        "pagination": _page_window(result, page, per_page),
        "founders": [P.founder_from_hit(h) for h in result.get("hits") or [] if isinstance(h, dict)],
    }


def founder_by_id(user_id):
    result = algolia_search(FOUNDER_INDEX, {"query": "", "hitsPerPage": 1, "filters": f"objectID:{int(user_id)}"},
                            kind="founders")
    hits = result.get("hits") or []
    return P.founder_from_hit(hits[0]) if hits and isinstance(hits[0], dict) else None


def founder_by_slug(slug):
    """The index has no slug filter: search the slug's words and keep the
    hit whose url_slug matches."""
    slug = str(slug or "").strip().lower()
    result = algolia_search(FOUNDER_INDEX, {"query": slug.replace("-", " "), "hitsPerPage": 20}, kind="founders")
    for hit in result.get("hits") or []:
        if isinstance(hit, dict) and str(hit.get("url_slug") or "").lower() == slug:
            return P.founder_from_hit(hit)
    return None


def founders_of_company(slug, name=None):
    """Index hits whose company_slug is `slug` (searched by company name)."""
    needle = (name or slug or "").replace("-", " ")
    result = algolia_search(FOUNDER_INDEX, {"query": needle, "hitsPerPage": 50}, kind="founders")
    out = []
    for hit in result.get("hits") or []:
        if isinstance(hit, dict) and str(hit.get("company_slug") or "").lower() == str(slug or "").lower():
            out.append(P.founder_from_hit(hit))
    return out


def vocabulary():
    """Everything a caller can filter on, with counts."""
    companies = facets("companies")
    founders = facets("founders")

    def counted(values, key=None):
        rows = sorted((values or {}).items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"value": v, "count": c} if key is None else {key: v, "count": c} for v, c in rows]

    def batches(values):
        rows = []
        for value, count in (values or {}).items():
            block = refs.batch_block(value)
            if block["code"]:
                rows.append({"code": block["code"], "name": block["name"], "company_count": count})
        return sorted(rows, key=lambda r: (int(r["code"][1:]), "WPSF".index(r["code"][0])), reverse=True)

    return {
        "companies": {
            "total_count": companies.get("_total"),
            "batches": batches(companies.get("batch")),
            "industries": counted(companies.get("industries")),
            "primary_industries": counted(companies.get("industry")),
            "subindustries": counted(companies.get("subindustry")),
            "tags": counted(companies.get("tags")),
            "regions": counted(companies.get("regions")),
            "statuses": [{"value": v.lower(), "count": c} for v, c in sorted((companies.get("status") or {}).items(),
                                                                             key=lambda kv: -kv[1])],
            "hiring_count": (companies.get("isHiring") or {}).get("true"),
            "top_company_count": (companies.get("top_company") or {}).get("true"),
            "nonprofit_count": (companies.get("nonprofit") or {}).get("true"),
            "demo_day_video_count": (companies.get("demo_day_video_public") or {}).get("true"),
            "app_video_count": (companies.get("app_video_public") or {}).get("true"),
        },
        "founders": {
            "total_count": founders.get("_total"),
            "batches": [{"code": v, "name": refs.batch_name(v), "founder_count": c}
                        for v, c in sorted((founders.get("batches") or {}).items(), key=lambda kv: -kv[1])],
            "titles": counted(founders.get("yc_titles")),
            "industries": counted(founders.get("yc_parent_industries")),
            "subindustries": counted(founders.get("yc_subindustries")),
            "regions": counted(founders.get("current_region")),
            "top_company_count": (founders.get("top_company") or {}).get("true"),
        },
    }
