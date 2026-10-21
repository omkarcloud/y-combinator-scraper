"""Y Combinator transport: plain curl_cffi with browser-impersonated TLS. No
browser, no login, no cookies (validated 2026-10-19 from direct egress:
every surface below answers 200 with no anti-bot in front; the only moving
parts are two short-lived Algolia search keys minted from page HTML).

Surfaces (all public, all read without a session):

  * ALGOLIA   app 45BWZJ1SGC — the startup directory's own search.
              YCCompany_production (relevance) / YCCompany_By_Launch_Date_
              production (newest first) with the secured key embedded in
              https://www.ycombinator.com/companies; YCUsers_production
              (founders) with the separate key embedded in /founders. A key
              is valid ~24 h (`validUntil` inside its base64) and is
              re-minted here before it expires.
  * INERTIA   every ycombinator.com page ships its data model in a
              data-page="{…}" attribute (Rails + Inertia): company profiles
              (/companies/<slug>, founders, photos, news, launches, jobs),
              job listings (/jobs, /jobs/role/<r>[/<loc>], /jobs/location/<l>)
              and postings (/companies/<slug>/jobs/<hash>), partners
              (/people, /people/<slug>), the blog (/blog, /blog/<slug>) and
              the library (/library, /library/<slug>).
  * JSON      the curated company lists (/companies/industry/<slug>[/<loc>]
              [/hiring], /companies/location/<slug>[/hiring]) answer JSON
              with `Accept: application/json`; the launches feed is
              /launches.json?page=N[&query=…][&batch=Winter 2024] and one
              launch is /launches/<slug>.json.
  * PUBLIC    https://api.ycombinator.com/v0.1/companies — YC's own open
    API       directory dump: 25 rows a page (20 when filtered) by q /
              batch / status / industries / tags / regions / isHiring /
              nonprofit / top_company.
  * WAAS      www.workatastartup.com/jobs/<id> and /companies/<slug> are
              Inertia pages too (an `Accept: text/html` header is mandatory
              — the bare request answers 406); the directories behind them
              redirect to login and are not used.

Egress: in grow every session leaves through a sticky residential proxy exit
(config.ycombinator_proxy, YCOMBINATOR_REQUIRE_PROXY) — ycombinator.com and
workatastartup.com are never contacted from the server's own IP; with no
proxy the call fails instead of going direct. The open-source kit sets
YCOMBINATOR_REQUIRE_PROXY = False, so it runs direct unless YCOMBINATOR_PROXY
is set. A 403/429 (or HTML where JSON is expected) drops the worker's session,
so the next call opens on a fresh exit; a configured fallback proxy is used
for config.YCOMBINATOR_BLOCK_COOLDOWN seconds. The headful patchright
browser is deliberately NOT built: there is no challenge to clear.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  YCUpstreamError  transport failure / 5xx                 — retryable
  YCBlocked        403 / 429 / HTML where JSON expected    — retryable on a new exit
  YCBadRequest     upstream 400 / 422                      — never retried
  YCNotFound       page / entity does not exist            — never retried
"""
import base64
import html as html_lib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

YC_HOST = "https://www.ycombinator.com"
WAAS_HOST = "https://www.workatastartup.com"
API_HOST = "https://api.ycombinator.com/v0.1"
ALGOLIA_APP = "45BWZJ1SGC"
ALGOLIA_URL = f"https://{ALGOLIA_APP}-dsn.algolia.net/1/indexes/*/queries"
COMPANY_INDEX = "YCCompany_production"
COMPANY_BY_LAUNCH_INDEX = "YCCompany_By_Launch_Date_production"
FOUNDER_INDEX = "YCUsers_production"

IMPERSONATE = "chrome"
TIMEOUT = 40
LIBRARY_TIMEOUT = 120      # /library is a 20 MB page
FANOUT_WORKERS = 8
KEY_SAFETY_SECONDS = 600   # re-mint an Algolia key this long before `validUntil`

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "upgrade-insecure-requests": "1",
}
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
}

_DATA_PAGE_RE = re.compile(r'data-page="([^"]+)"')
_ALGOLIA_OPTS_RE = re.compile(r'AlgoliaOpts\s*=\s*(\{.*?\})\s*[;<]', re.S)
_VALID_UNTIL_RE = re.compile(r"validUntil=(\d+)")


class YCUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class YCBlocked(YCUpstreamError, Blocked):
    """403 / 429 or an HTML body where JSON was expected — retryable."""


class YCBadRequest(BadRequest):
    """Upstream 400 / 422 — the params were rejected. Never retried."""


class YCNotFound(NotFound):
    """Page / entity does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per worker thread. Direct egress by default; after a block
# the thread's sessions go through a sticky residential exit for a cooldown.
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy_for_new_session():
    """The exit for a new session. Raises when the config requires a proxy
    and none is available (never falls back to the server's own IP)."""
    forced = config.ycombinator_proxy()
    if forced:
        return forced
    if time.time() < _fallback_until:
        fallback = config.ycombinator_fallback_proxy()
        if fallback:
            return fallback
    if getattr(config, "YCOMBINATOR_REQUIRE_PROXY", False):
        raise YCUpstreamError("no Y Combinator proxy configured "
                              "(ycombinator.com is never contacted from the server's IP)")
    return None


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block(where):
    """A 403/429: drop the session (the next one opens on a fresh exit) and
    use the fallback proxy, if one is configured, for a while."""
    global _fallback_until
    with _fallback_lock:
        _fallback_until = time.time() + config.YCOMBINATOR_BLOCK_COOLDOWN
    _drop_session()
    print(f"ycombinator: blocked on {where}; the next session opens on a fresh exit")


def _attempts():
    return max(1, int(getattr(config, "YCOMBINATOR_MAX_ATTEMPTS", 3)))


def with_retries(fn, label):
    """Run fn() up to YCOMBINATOR_MAX_ATTEMPTS times. A transport failure, a
    block or a 5xx drops the thread's session so the next attempt opens on a
    fresh proxy exit; NotFound / BadRequest are final and never retried."""
    attempts = _attempts()
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (YCNotFound, YCBadRequest):
            raise
        except YCUpstreamError as e:
            if attempt == attempts:
                raise
            _drop_session()
            print(f"ycombinator: {label}: attempt {attempt}/{attempts} failed ({e}); retrying on a fresh exit")
            time.sleep(0.5 * attempt)


def dump_debug(name, text):
    """Write a raw body to $YCOMBINATOR_DEBUG_DIR/<name>.txt for post-mortems."""
    dbg = os.environ.get("YCOMBINATOR_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text)
        except OSError:
            pass


# ---- raw requests -----------------------------------------------------------------

def _request(method, url, params=None, headers=None, data=None, timeout=TIMEOUT, label=None, allow_404=False):
    label = label or url
    try:
        if method == "POST":
            resp = _session().post(url, params=params, headers=headers, data=data, timeout=timeout,
                                   allow_redirects=True)
        else:
            resp = _session().get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        _drop_session()
        raise YCUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
    status = resp.status_code
    if status == 404 or (status == 410):
        if allow_404:
            return resp
        raise YCNotFound(f"{label}: not found")
    if status in (400, 422):
        raise YCBadRequest(f"{label}: upstream rejected the request ({status}) {resp.text[:200]}")
    if status in (401, 403, 429, 503):
        dump_debug(f"blocked_{status}", resp.text)
        _note_block(label)
        raise YCBlocked(f"{label}: HTTP {status}")
    if status >= 500:
        raise YCUpstreamError(f"{label}: HTTP {status}")
    if status != 200:
        raise YCUpstreamError(f"{label}: unexpected HTTP {status}")
    return resp


def get_page(url, params=None, label=None, timeout=TIMEOUT):
    """A page's HTML -> (text, final url)."""
    def once():
        resp = _request("GET", url, params=params, headers=PAGE_HEADERS, timeout=timeout, label=label)
        text = resp.text or ""
        if "<html" not in text[:2000].lower() and "<!doctype" not in text[:200].lower():
            dump_debug("nonhtml", text)
            raise YCBlocked(f"{label or url}: non-HTML answer where a page was expected")
        return text, str(resp.url)
    return with_retries(once, label or url)


def get_json(url, params=None, label=None, headers=None, timeout=TIMEOUT):
    def once():
        resp = _request("GET", url, params=params, headers=headers or JSON_HEADERS, timeout=timeout, label=label)
        try:
            return resp.json()
        except Exception:
            dump_debug("nonjson", resp.text)
            raise YCBlocked(f"{label or url}: non-JSON answer where JSON was expected")
    return with_retries(once, label or url)


# ---- Inertia pages -----------------------------------------------------------------

def parse_data_page(page_html, label="page"):
    """The Inertia payload of a page -> {"component", "props", "url", …}."""
    match = _DATA_PAGE_RE.search(page_html or "")
    if not match:
        dump_debug("no_data_page", page_html)
        raise YCUpstreamError(f"{label}: no Inertia data-page payload in the HTML (layout change?)")
    try:
        return json.loads(html_lib.unescape(match.group(1)))
    except ValueError as e:
        raise YCUpstreamError(f"{label}: data-page is not JSON ({e})")


def page_props(path, params=None, host=YC_HOST, label=None, timeout=TIMEOUT):
    """GET a ycombinator.com / workatastartup.com page -> (component name,
    props dict, final url). A 404 page raises YCNotFound."""
    url = path if path.startswith("http") else f"{host}{path}"
    text, final = get_page(url, params=params, label=label or path, timeout=timeout)
    payload = parse_data_page(text, label or path)
    return payload.get("component") or "", payload.get("props") or {}, final


LIST_HEADERS = {
    # Rails content negotiation: a `*/*` in Accept gets the HTML page back,
    # a bare application/json gets the list as JSON.
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
}


def list_json(path, params=None, label=None):
    """The curated company lists / launches feed: JSON when asked for it."""
    return get_json(f"{YC_HOST}{path}", params=params, label=label or path, headers=LIST_HEADERS)


def page_payload(path, params=None, host=YC_HOST, label=None, timeout=TIMEOUT):
    """Like page_props but the whole Inertia payload (component, props, url,
    rails_context…)."""
    url = path if path.startswith("http") else f"{host}{path}"
    text, final = get_page(url, params=params, label=label or path, timeout=timeout)
    return parse_data_page(text, label or path)


# ---- Algolia ------------------------------------------------------------------------

_keys = {}
_keys_lock = threading.Lock()
_KEY_PAGES = {"companies": "/companies", "founders": "/founders"}


def _key_valid_until(key):
    try:
        decoded = base64.b64decode(key + "=" * (-len(key) % 4)).decode("latin-1")
    except Exception:
        return 0
    match = _VALID_UNTIL_RE.search(decoded)
    return int(match.group(1)) if match else 0


def _mint_key(kind):
    path = _KEY_PAGES[kind]
    text, _ = get_page(f"{YC_HOST}{path}", label=f"algolia key ({path})")
    match = _ALGOLIA_OPTS_RE.search(text)
    if not match:
        dump_debug(f"no_algolia_opts_{kind}", text)
        raise YCUpstreamError(f"{path}: no AlgoliaOpts in the page (layout change?)")
    try:
        opts = json.loads(match.group(1))
    except ValueError as e:
        raise YCUpstreamError(f"{path}: AlgoliaOpts is not JSON ({e})")
    key = opts.get("key")
    if not key or opts.get("app", ALGOLIA_APP) != ALGOLIA_APP:
        raise YCUpstreamError(f"{path}: unexpected AlgoliaOpts {str(opts)[:120]}")
    valid_until = opts.get("valid_until") or _key_valid_until(key) or int(time.time()) + 3600
    return key, int(valid_until)


def algolia_key(kind="companies", force=False):
    """The secured search key for the companies or founders index, minted
    from the page that embeds it and re-minted before it expires."""
    now = time.time()
    with _keys_lock:
        cached = _keys.get(kind)
        if cached and not force and cached[1] - KEY_SAFETY_SECONDS > now:
            return cached[0]
    key, valid_until = _mint_key(kind)
    with _keys_lock:
        _keys[kind] = (key, valid_until)
    return key


def algolia_search(index, params, kind="companies"):
    """One Algolia query -> the result block ({hits, nbHits, page, nbPages,
    hitsPerPage, facets?}). `params` is the dict of Algolia search params
    (query, hitsPerPage, page, facetFilters, numericFilters, facets…)."""
    return with_retries(lambda: _algolia_search_once(index, params, kind), f"algolia {index}")


def _algolia_search_once(index, params, kind):
    encoded = urlencode({k: (json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v)
                         for k, v in params.items()}, quote_via=quote)
    body = json.dumps({"requests": [{"indexName": index, "params": encoded}]})
    for attempt in (1, 2):
        key = algolia_key(kind, force=attempt == 2)
        headers = {
            "x-algolia-application-id": ALGOLIA_APP,
            "x-algolia-api-key": key,
            "content-type": "application/json",
            "accept": "application/json",
        }
        try:
            resp = _session().post(ALGOLIA_URL, data=body, headers=headers, timeout=TIMEOUT)
        except Exception as e:
            _drop_session()
            raise YCUpstreamError(f"algolia {index}: request failed: {type(e).__name__}: {e}")
        if resp.status_code in (400, 403) and attempt == 1:
            # an expired / rotated key: mint a fresh one and retry once
            continue
        if resp.status_code == 400:
            raise YCBadRequest(f"algolia {index}: {resp.text[:200]}")
        if resp.status_code in (403, 429):
            raise YCBlocked(f"algolia {index}: HTTP {resp.status_code} {resp.text[:120]}")
        if resp.status_code != 200:
            raise YCUpstreamError(f"algolia {index}: HTTP {resp.status_code}")
        try:
            doc = resp.json()
        except Exception:
            raise YCUpstreamError(f"algolia {index}: non-JSON answer")
        results = doc.get("results") if isinstance(doc, dict) else None
        if not results or not isinstance(results[0], dict):
            raise YCUpstreamError(f"algolia {index}: unexpected payload shape")
        return results[0]
    raise YCUpstreamError(f"algolia {index}: key refresh failed")


# ---- the public v0.1 API --------------------------------------------------------------

def api_companies(params):
    """https://api.ycombinator.com/v0.1/companies?… -> {companies, page,
    totalPages, nextPage}."""
    doc = get_json(f"{API_HOST}/companies", params=params, label="api v0.1 companies")
    if not isinstance(doc, dict) or not isinstance(doc.get("companies"), list):
        raise YCUpstreamError("api v0.1 companies: unexpected payload shape")
    return doc


# ---- launches --------------------------------------------------------------------------

def launches_feed(params):
    doc = list_json("/launches.json", params=params, label="launches feed")
    if not isinstance(doc, dict) or not isinstance(doc.get("hits"), list):
        raise YCUpstreamError("launches feed: unexpected payload shape")
    return doc


def launch_json(slug):
    doc = get_json(f"{YC_HOST}/launches/{quote(slug)}.json", label=f"launch {slug}")
    if not isinstance(doc, dict) or not doc.get("id"):
        raise YCUpstreamError(f"launch {slug}: unexpected payload shape")
    return doc


# ---- Work at a Startup --------------------------------------------------------------------

def waas_props(path, label=None):
    """A workatastartup.com Inertia page (Accept: text/html is mandatory)."""
    return page_props(path, host=WAAS_HOST, label=label or f"waas {path}")


# ---- fan-out ------------------------------------------------------------------------

_fanout = ThreadPoolExecutor(max_workers=FANOUT_WORKERS * 3, thread_name_prefix="ycombinator-fanout")


def run_parallel(fns):
    """Run callables concurrently (the first on this thread) -> results in order."""
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    futures = [_fanout.submit(fn) for fn in fns[1:]]
    first = fns[0]()
    return [first] + [f.result() for f in futures]


def or_not_found(fn, message):
    """Run fn(); a YCNotFound from the transport is re-raised with the
    endpoint's own wording (the transport only knows the URL)."""
    try:
        return fn()
    except YCNotFound:
        raise YCNotFound(message)


def soft(fn, default=None):
    """Wrap an optional lookup: any upstream failure yields `default`
    instead of failing the endpoint."""
    def run():
        try:
            return fn()
        except (UpstreamError, BadRequest, NotFound):
            return default
    return run


if __name__ == "__main__":
    # Smoke test: python ycombinator/fetch.py [slug]
    slug = sys.argv[1] if len(sys.argv) > 1 else "airbnb"
    print("companies key:", algolia_key("companies")[:16], "…")
    hits = algolia_search(COMPANY_INDEX, {"query": slug, "hitsPerPage": 2})
    print("algolia:", hits.get("nbHits"), [h.get("name") for h in hits.get("hits", [])])
    component, props, final = page_props(f"/companies/{slug}")
    print("page:", component, final, sorted((props.get("company") or {}).keys())[:8])
    feed = launches_feed({"page": 0})
    print("launches:", feed.get("nbHits"), feed["hits"][0].get("title") if feed["hits"] else None)
    print("api:", api_companies({"page": 1})["totalPages"], "pages")
