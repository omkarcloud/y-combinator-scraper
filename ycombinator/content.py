"""/y-combinator/partners/*, /blog/*, /library/* — the people who run YC,
the YC blog (Ghost, paged 10 a page, by author / tag) and the YC Startup
Library (one 20 MB page listing every video / essay, held in-process for
LIBRARY_TTL seconds and searched locally).
"""
import threading
import time
from urllib.parse import quote

from ycombinator import parsers as P
from ycombinator.fetch import LIBRARY_TIMEOUT, YCNotFound, or_not_found, page_props

LIBRARY_TTL = 6 * 3600
BLOG_PAGE_SIZE = 10

_library = {"rows": None, "carousels": None, "until": 0.0}
_library_lock = threading.Lock()


# ---- partners -------------------------------------------------------------------------

def partners(query=None, group=None):
    component, props, final = page_props("/people", label="people")
    sections = props.get("sections") if isinstance(props.get("sections"), list) else []
    needle = (query or "").lower()
    group_needle = (group or "").lower()
    out, groups = [], []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = P.text(section.get("title"))
        people = [p for p in section.get("people") or [] if isinstance(p, dict)]
        groups.append({"name": title, "people_count": len(people)})
        if group_needle and group_needle not in (title or "").lower():
            continue
        for person in people:
            card = P.partner_card(person, title)
            if needle and needle not in " ".join(filter(None, [card["name"], card["title"], card["bio"]])).lower():
                continue
            out.append(card)
    return {"query": query, "group": group, "groups": groups, "people_count": len(out), "people": out}


def partner(partner):
    component, props, final = or_not_found(lambda: page_props(f"/people/{partner}", label=f"partner {partner}"),
                                           f"'{partner}' is not a Y Combinator partner page")
    if not isinstance(props.get("partner"), dict):
        raise YCNotFound(f"'{partner}' is not a Y Combinator partner page")
    return {"partner": P.partner_from_page(props)}


# ---- blog --------------------------------------------------------------------------------

def posts(author=None, tag=None, page=1):
    if author and tag:
        raise ValueError("pass either author or tag, not both (the blog filters on one)")
    # free text goes into the path: one escaped segment (no "/", "?" or spaces leaking through)
    path = f"/blog/author/{quote(author, safe='')}" if author else f"/blog/tag/{quote(tag, safe='')}" if tag else "/blog"
    component, props, final = or_not_found(lambda: page_props(path, params={"page": page} if page > 1 else None,
                                                              label=f"blog {path}"), f"no blog posts at {path}")
    rows = props.get("posts") if isinstance(props.get("posts"), list) else []
    pagination = props.get("pagination") if isinstance(props.get("pagination"), dict) else {}
    filt = props.get("filter") if isinstance(props.get("filter"), dict) else None
    featured = props.get("featured") if isinstance(props.get("featured"), dict) else None
    if not rows and page == 1:
        raise YCNotFound(f"no blog posts at {path}")
    return {
        "filter": {"author": author, "tag": tag,
                   "name": P.text((filt or {}).get("name")), "description": P.text((filt or {}).get("description"))},
        "link": f"https://www.ycombinator.com{path}",
        "featured": P.post_card(featured) if featured and page == 1 else None,
        "pagination": P.pagination(page, P.to_int(pagination.get("limit")) or BLOG_PAGE_SIZE,
                                   pagination.get("total"), total_pages=P.to_int(pagination.get("pages")) or 0),
        "posts": [P.post_card(p) for p in rows if isinstance(p, dict)],
    }


def post(post):
    component, props, final = or_not_found(lambda: page_props(f"/blog/{post}", label=f"blog post {post}"),
                                           f"blog post '{post}' not found")
    if not isinstance(props.get("post"), dict):
        raise YCNotFound(f"blog post '{post}' not found")
    return {"post": P.post_from_page(props)}


# ---- library ------------------------------------------------------------------------------

def _library_index(force=False):
    now = time.time()
    with _library_lock:
        if _library["rows"] is not None and not force and _library["until"] > now:
            return _library["rows"], _library["carousels"]
    component, props, final = page_props("/library", label="library", timeout=LIBRARY_TIMEOUT)
    carousels = [P.library_carousel(c) for c in props.get("carousels") or [] if isinstance(c, dict)]
    rows, seen = [], set()
    featured = props.get("featured")
    if isinstance(featured, dict):
        card = P.article_card(featured)
        card["carousels"] = ["Featured"]
        rows.append(card)
        seen.add(card["slug"])
    for carousel in carousels:
        for article in carousel["articles"]:
            if article["slug"] in seen:
                for row in rows:
                    if row["slug"] == article["slug"]:
                        row["carousels"].append(carousel["name"])
                continue
            article["carousels"] = [carousel["name"]]
            rows.append(article)
            seen.add(article["slug"])
    summary = [{"id": c["id"], "name": c["name"], "description": c["description"], "articles_count": len(c["articles"])}
               for c in carousels]
    with _library_lock:
        _library.update(rows=rows, carousels=summary, until=now + LIBRARY_TTL)
    return rows, summary


def library(query=None, category=None, series=None, author=None, sort="relevance", page=1, per_page=20):
    rows, carousels = _library_index()
    needle = (query or "").lower()
    terms = needle.split()
    out = []
    for row in rows:
        blob = " ".join(filter(None, [row.get("title"), row.get("description"), row.get("author"),
                                      " ".join(a.get("name") or "" for a in row.get("authors") or []),
                                      " ".join(row.get("categories") or []), row.get("series")])).lower()
        if terms and not all(t in blob for t in terms):
            continue
        if category and category.lower() not in " ".join([*(row.get("categories") or []), *(row.get("carousels") or [])]).lower():
            continue
        if series and series.lower() not in (row.get("series") or "").lower():
            continue
        if author and author.lower() not in " ".join([row.get("author") or "",
                                                      *(a.get("name") or "" for a in row.get("authors") or [])]).lower():
            continue
        out.append(row)
    if sort == "newest":
        out.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    elif sort == "views":
        out.sort(key=lambda r: ((r.get("video") or {}).get("view_count") or 0), reverse=True)
    start = (page - 1) * per_page
    return {
        "query": query,
        "filters": {"category": category, "series": series, "author": author, "sort": sort},
        "carousels": carousels,
        "pagination": P.pagination(page, per_page, len(out)),
        "articles": out[start:start + per_page],
    }


def article(article, include_transcript=True):
    component, props, final = or_not_found(lambda: page_props(f"/library/{article}", label=f"library article {article}"),
                                           f"library article '{article}' not found")
    if not isinstance(props.get("article"), dict):
        raise YCNotFound(f"library article '{article}' not found")
    return {"article": P.article_from_page(props, include_transcript=include_transcript)}
