"""The 25 Y Combinator endpoints. Every path is served with and without the
`/y-combinator` prefix, so code generated against the hosted API on RapidAPI
(paths like /companies/details) runs unchanged against this server.

Each request is validated by the marshmallow schema in ycombinator/schemas.py
(unknown params are rejected, one param per input: `company` takes a slug, an
id or a link), then the endpoint function runs and errors map to HTTP:
bad params -> 400, missing entity -> 404, transport failure / block -> 500.
List endpoints answer with count / per_page / current_page / total_pages /
next / previous first, the next / previous links built from your own params.
"""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from ycombinator import companies, content, founders, jobs, launches, meta
from ycombinator import schemas as S

PREFIX = "/y-combinator"

# (path, schema, endpoint function, paginated) — in the API's documented order
ENDPOINTS = [
    ("/companies/details", S.CompanySchema, companies.details, False),
    ("/companies/search", S.CompanySearchSchema, companies.search, True),
    ("/companies/top", S.CompaniesTopSchema, companies.top, True),
    ("/companies/new", S.CompaniesNewSchema, companies.new, True),
    ("/companies/browse", S.CompanyBrowseSchema, companies.browse, True),
    ("/companies/highlights", S.CompanyHighlightsSchema, companies.highlights, True),
    ("/companies/directory", S.CompanyDirectorySchema, companies.directory_dump, True),
    ("/companies/founders", S.CompanySchema, companies.founders, False),
    ("/companies/jobs", S.CompanySchema, companies.jobs, False),
    ("/companies/launches", S.CompanySchema, companies.launches, False),
    ("/founders/search", S.FounderSearchSchema, founders.search, True),
    ("/founders/details", S.FounderSchema, founders.details, False),
    ("/jobs/search", S.JobsSearchSchema, jobs.search, True),
    ("/jobs/details", S.JobSchema, jobs.details, False),
    ("/launches/search", S.LaunchesSearchSchema, launches.search, True),
    ("/launches/details", S.LaunchSchema, launches.details, False),
    ("/partners/list", S.PartnersSchema, content.partners, False),
    ("/partners/details", S.PartnerSchema, content.partner, False),
    ("/blog/posts", S.BlogPostsSchema, content.posts, True),
    ("/blog/details", S.PostSchema, content.post, False),
    ("/library/search", S.LibrarySearchSchema, content.library, True),
    ("/library/details", S.ArticleSchema, content.article, False),
    ("/filters", S.FiltersSchema, meta.filters, False),
    ("/batches", S.BatchesSchema, meta.batches, False),
    ("/stats", S.StatsSchema, meta.stats, False),
]


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(base, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    return f"{base}?{urlencode(query, doseq=True)}"


def paginate(result, raw_params):
    """Lift the endpoint's `pagination` block into the flat list shape."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(raw_params.get("page")) or 1
    total_pages = max(_as_int(pagination.get("total_pages")), 0)
    parts = request.urlparts
    base = f"{parts.scheme}://{parts.netloc}{parts.path}"
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(base, raw_params, page + 1 if page < total_pages else None),
        "previous": _page_link(base, raw_params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def _error(message, exc):
    body = {"error": message}
    reason = getattr(exc, "reason", None)
    if reason:
        body["reason"] = reason
    return body


def make_handler(path, schema_cls, impl, paginated):
    label = f"y-combinator {path.strip('/')}"

    def handler():
        raw = query_dict()
        data, error = load_query(schema_cls, raw)
        if error:
            return json_response(error, 400)
        data.pop("refresh", None)          # no cache here: every call is live
        try:
            result = impl(**data)
        except ValueError as e:            # bad combination of params
            return json_response({"error": str(e)}, 400)
        except BadRequest as e:            # upstream rejected the request
            return json_response(_error(f"y-combinator rejected the request: {e}", e), 400)
        except NotFound as e:
            return json_response(_error(str(e) or "not found", e), 404)
        except Blocked as e:               # retries exhausted / blocked
            return json_response({"error": f"y-combinator blocked the request, retry later: {e}"}, 500)
        except UpstreamError as e:
            return json_response({"error": f"{label} failed: {e}"}, 500)
        except Exception as e:
            return json_response({"error": f"{label} failed: {type(e).__name__}: {e}"}, 500)
        if paginated:
            result = paginate(result, raw)
        return json_response(result)

    handler.__name__ = "ycombinator_" + path.strip("/").replace("/", "_").replace("-", "_")
    return handler


for _path, _schema, _impl, _paginated in ENDPOINTS:
    _handler = make_handler(_path, _schema, _impl, _paginated)
    route(_path, method="GET")(_handler)
    route(PREFIX + _path, method="GET")(_handler)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
