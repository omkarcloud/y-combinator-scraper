"""/y-combinator/founders/* — the founders directory (Algolia
YCUsers_production) and one founder's merged profile.
"""
from ycombinator import directory
from ycombinator import parsers as P
from ycombinator.fetch import YCNotFound, page_props, run_parallel, soft, waas_props


def search(**params):
    return directory.founder_search(**params)


def _page_founder(company_slug, name):
    """The founder block of the company page whose name matches."""
    component, props, final = page_props(f"/companies/{company_slug}", label=f"company {company_slug}")
    if not isinstance(props.get("company"), dict):
        # not a company profile: keep the index's company block, not an all-null one
        return None, None
    profile = P.company_from_page(props)
    needle = (name or "").lower()
    for founder in profile.get("founders") or []:
        if (founder.get("name") or "").lower() == needle:
            return founder, profile
    return None, profile


def details(founder):
    """Index card (slug, HN username, batches, region, industries) + the
    company page's founder block (bio, title, LinkedIn, Twitter, active
    flag) + Work at a Startup's past-companies line, with the company
    summarized."""
    hit = directory.founder_by_id(founder["id"]) if founder.get("id") else directory.founder_by_slug(founder["slug"])
    if not hit:
        ref = founder.get("slug") or founder.get("id")
        raise YCNotFound(f"founder '{ref}' not found in the Y Combinator founders directory")
    company_slug = (hit.get("company") or {}).get("slug")
    block, profile, waas = None, None, None
    if company_slug:
        (block, profile), waas = run_parallel([
            soft(lambda: _page_founder(company_slug, hit.get("name")), default=(None, None)),
            soft(lambda: P.company_from_waas(waas_props(f"/companies/{company_slug}")[1].get("company")), default=None),
        ])
    block = block or {}
    profile = profile or {}
    past = {(f.get("name") or "").lower(): f.get("past_companies") for f in (waas or {}).get("founders") or []}
    out = dict(hit)
    out.update({
        "title": block.get("title") or hit.get("title"),
        "bio": block.get("bio"),
        "past_companies": past.get((hit.get("name") or "").lower()),
        "avatar": hit.get("avatar") or block.get("avatar"),
        "is_active": block.get("is_active"),
        "has_email": block.get("has_email"),
        "social": block.get("social") or {"linkedin": None, "twitter": None},
    })
    if profile:
        out["company"] = {k: profile.get(k) for k in ("id", "slug", "name", "link", "website", "logo", "one_liner",
                                                       "batch", "status", "team_size", "location")}
        out["cofounders"] = [{k: f.get(k) for k in ("id", "name", "title", "avatar", "social")}
                             for f in profile.get("founders") or [] if (f.get("name") or "").lower() != (hit.get("name") or "").lower()]
    else:
        out["cofounders"] = []
    return {"founder": out}
