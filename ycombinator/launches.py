"""/y-combinator/launches/* — Launch YC: the feed (newest first, full-text
search, batch filter) and one launch with its full markdown body.
"""
from ycombinator import parsers as P
from ycombinator.fetch import YCNotFound, launch_json, launches_feed, or_not_found, page_props, run_parallel, soft


def search(query=None, batch=None, page=1, per_page=20):
    params = {"page": page - 1, "hitsPerPage": per_page}
    if query:
        params["query"] = query
    if batch:
        params["batch"] = batch["name"]
    doc = launches_feed(params)
    total = P.to_int(doc.get("nbHits")) or 0
    total_pages = P.to_int(doc.get("nbPages")) or 0
    return {
        "query": query,
        "filters": {"batch": batch["code"] if batch else None},
        "pagination": P.pagination(page, per_page, total, total_pages=total_pages),
        "launches": [P.launch_card(h) for h in doc.get("hits") or [] if isinstance(h, dict)],
    }


def details(launch):
    doc, post = run_parallel([
        lambda: or_not_found(lambda: launch_json(launch), f"launch '{launch}' not found on Launch YC"),
        soft(lambda: page_props(f"/launches/{launch}", label=f"launch page {launch}")[1].get("post"), default=None),
    ])
    if not doc:
        raise YCNotFound(f"launch '{launch}' not found")
    return {"launch": P.launch_from_json(doc, post)}
