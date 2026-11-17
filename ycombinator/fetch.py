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

Egress: in grow every session leaves through the exit config.ycombinator_proxy
names (YCOMBINATOR_REQUIRE_PROXY): the shared gateway exit since 2026-11-11
(knob YCOMBINATOR_EXIT = "gateway": a fresh gateway address per request; a call's
last retry, and the rest of a call the gateway itself failed, on the sticky
residential exit), with YCOMBINATOR_EXIT = None a sticky residential proxy
exit — ycombinator.com and
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
import fastjson
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
import identity_pool
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import debug, fanout, sessions

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
    "accept-language": egress.accept_language(),
    "upgrade-insecure-requests": "1",
}
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": egress.accept_language(),
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
    if getattr(_local, "residential", False):
        # the rest of a call whose gateway attempts failed (with_retries):
        # the proxy exit behind the gateway
        forced = config.ycombinator_proxy(fallback=True)
    else:
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
        proxy = _proxy_for_new_session()
        sess = egress.new_session(proxy, impersonate=IMPERSONATE)     # a proxy URL, None, or the gateway exit ("gateway")
        _local.session = sess
        _local.on_gateway = bool(egress.gateway_country(proxy))
    return sess


def _drop_session():
    sessions.drop(_local)


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


def _gateway_failed(error):
    """the gateway's own failure, as _request wraps it (exit_gateway's
    GatewayError / GatewayMissing): its 29 s limit, its 10 MB body cap
    (/library is 7.4 MB gzipped and 6-14 s through it, 2026-11-11) or its
    throttling. Another gateway address would meet the same limit, so only the
    exit that can wait (TIMEOUT / LIBRARY_TIMEOUT) will do."""
    return "request failed: Gateway" in str(error)


def with_retries(fn, label):
    """Run fn() up to YCOMBINATOR_MAX_ATTEMPTS times. A transport failure, a
    block or a 5xx drops the thread's session so the next attempt opens on a
    fresh proxy exit; NotFound / BadRequest are final and never retried.
    With the gateway exit as the exit (config.YCOMBINATOR_EXIT) the LAST
    attempt, and every attempt after a failure of the gateway itself (its
    29 s timeout, its 10 MB cap), rides the proxy
    exit (config.ycombinator_proxy(fallback=True)), so a gateway problem
    degrades to the residential path instead of an error; the thread's next
    call starts on the gateway again.
    A call nested inside another (the Algolia key mint's get_page inside
    algolia_search) runs once: the outer loop owns the retry budget, so the
    tries do not multiply."""
    if getattr(_local, "retrying", False):
        return fn()
    attempts = _attempts()
    _local.retrying = True
    try:
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except (YCNotFound, YCBadRequest):
                raise
            except YCUpstreamError as e:
                if attempt == attempts:
                    raise
                _drop_session()
                if getattr(_local, "on_gateway", False) and (attempt + 1 == attempts or _gateway_failed(e)):
                    _local.residential = True
                print(f"ycombinator: {label}: attempt {attempt}/{attempts} failed ({e}); retrying on a fresh exit")
                time.sleep(0.5 * attempt)
    finally:
        _local.retrying = False
        if getattr(_local, "residential", False):
            _local.residential = False
            _drop_session()             # the fallback exit served this call only


def dump_debug(name, text):
    """Write a raw body to $YCOMBINATOR_DEBUG_DIR/<name>.txt for post-mortems."""
    debug.dump("YCOMBINATOR_DEBUG_DIR", name, text)


# ---- raw requests -----------------------------------------------------------------

# YC's own hosts: a redirect between them is followed on the gateway exit too
# (_request). Never a host taken from the page (a company's website).
_OWN_HOSTS = {"www.ycombinator.com", "www.workatastartup.com", "api.ycombinator.com", "account.ycombinator.com"}
_REDIRECTS = (301, 302, 303, 307, 308)


def _request(method, url, params=None, headers=None, data=None, timeout=TIMEOUT, label=None, allow_404=False):
    label = label or url
    try:
        if method == "POST":
            resp = _session().post(url, params=params, headers=headers, data=data, timeout=timeout,
                                   allow_redirects=True)
        else:
            resp = _session().get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
        # A curl session never gets here with a redirect (it followed it). The
        # gateway exit follows one inside a site only, and YC's two sites
        # redirect to each other: workatastartup.com/companies/<slug> of a
        # company with no open jobs -> ycombinator.com/companies/<slug>
        # (2026-11-11: brex, twitch). Follow it the way curl does.
        for _ in range(3):
            location = resp.headers.get("location") or ""
            if resp.status_code not in _REDIRECTS or urlsplit(location).hostname not in _OWN_HOSTS \
                    or not location.startswith("https://"):
                break
            resp = _session().get(location, headers=headers, timeout=timeout, allow_redirects=True)
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
        return fastjson.loads(html_lib.unescape(match.group(1)))
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
    "accept-language": egress.accept_language(),
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
# The secured search key per index kind (pool key = kind) lives in a shared
# identity_pool (replaced the `_keys` dict + lock on 2026-11-09): the mint's
# `valid_until` minus KEY_SAFETY_SECONDS is the identity's expires_at, a
# rejection wave across the 64 request threads costs ONE mint (the other
# threads get the winner's key), and a second forced re-mint inside
# KEY_REFRESH_INTERVAL returns the same key, so a genuine 400 never loops.
_KEY_PAGES = {"companies": "/companies", "founders": "/founders"}
KEY_REFRESH_INTERVAL = 30      # seconds between two rejection-driven re-mints per kind


def _key_valid_until(key):
    try:
        decoded = base64.b64decode(key + "=" * (-len(key) % 4)).decode("latin-1")
    except Exception:
        return 0
    match = _VALID_UNTIL_RE.search(decoded)
    return int(match.group(1)) if match else 0


def _mint_key(kind, hint=None):
    """The pool's mint: the key embedded in the companies / founders page,
    valid until its own `valid_until` (minus the safety margin). Raises
    YCUpstreamError (or get_page's own errors)."""
    path = _KEY_PAGES[kind]
    text, _ = get_page(f"{YC_HOST}{path}", label=f"algolia key ({path})")
    match = _ALGOLIA_OPTS_RE.search(text)
    if not match:
        dump_debug(f"no_algolia_opts_{kind}", text)
        raise YCUpstreamError(f"{path}: no AlgoliaOpts in the page (layout change?)")
    try:
        opts = fastjson.loads(match.group(1))
    except ValueError as e:
        raise YCUpstreamError(f"{path}: AlgoliaOpts is not JSON ({e})")
    key = opts.get("key")
    if not key or opts.get("app", ALGOLIA_APP) != ALGOLIA_APP:
        raise YCUpstreamError(f"{path}: unexpected AlgoliaOpts {str(opts)[:120]}")
    valid_until = opts.get("valid_until") or _key_valid_until(key) or int(time.time()) + 3600
    return identity_pool.Identity(key, expires_at=int(valid_until) - KEY_SAFETY_SECONDS)


_keys = identity_pool.Pool("ycombinator-algolia-key", _mint_key, min_interval=KEY_REFRESH_INTERVAL)


def algolia_key(kind="companies", force=False):
    """The secured search key for the companies or founders index, minted
    from the page that embeds it and re-minted before it expires. force=True
    (the key was just rejected) asks the pool to replace the current one:
    one mint per wave, and inside the interval the same key comes back."""
    ident = _keys.get(kind)
    if force:
        ident = _keys.get(kind, replace=ident)
    return ident.value


def algolia_search(index, params, kind="companies"):
    """One Algolia query -> the result block ({hits, nbHits, page, nbPages,
    hitsPerPage, facets?}). `params` is the dict of Algolia search params
    (query, hitsPerPage, page, facetFilters, numericFilters, facets…)."""
    return with_retries(lambda: _algolia_search_once(index, params, kind), f"algolia {index}")


def _algolia_search_once(index, params, kind):
    encoded = urlencode({k: (json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v)
                         for k, v in params.items()}, quote_via=quote)
    body = json.dumps({"requests": [{"indexName": index, "params": encoded}]})
    key_ident = None
    for attempt in (1, 2):
        # attempt 2 replaces the key attempt 1 sent: one re-mint per rejection
        # wave, none inside KEY_REFRESH_INTERVAL (the same key, so a genuine
        # 400 fails below instead of minting again)
        key_ident = _keys.get(kind, replace=key_ident if attempt == 2 else None)
        headers = {
            "x-algolia-application-id": ALGOLIA_APP,
            "x-algolia-api-key": key_ident.value,
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
    return fanout.on_pool_caller_first(_fanout, fns)


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
    return fanout.soft(fn, default, (UpstreamError, BadRequest, NotFound))


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
