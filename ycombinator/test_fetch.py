"""ycombinator/fetch.py's secured Algolia keys on identity_pool: no network,
the key mint is faked. The pool's own rules live in tests/test_identity_pool.py.

    python -m pytest ycombinator/test_fetch.py -q
"""
import json
import threading
import time

import pytest

import identity_pool
from ycombinator import fetch
from scraper_utils.testing import hosted_only


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.text = json.dumps(body if body is not None else {})

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, accepted):
        self.accepted = accepted

    def post(self, url, data=None, headers=None, timeout=None):
        if headers["x-algolia-api-key"] not in self.accepted:
            return FakeResponse(400, {"message": "Invalid Application-ID or API key"})
        return FakeResponse(200, {"results": [{"hits": [], "nbHits": 0, "page": 0, "nbPages": 0}]})


@pytest.fixture
def keys(monkeypatch):
    """The module's pool with a counting fake mint (k1, k2, ...)."""
    pool = fetch._keys
    pool.clear()
    pool._last_mint.clear()
    pool._mint_times.clear()
    mints = []

    def mint(kind, hint):
        time.sleep(0.05)                     # let the wave pile up behind one mint
        mints.append(kind)
        return identity_pool.Identity(f"k{len(mints)}", expires_at=time.time() + 3600)

    monkeypatch.setattr(pool, "_mint_fn", mint)
    pool.mints = mints
    yield pool
    pool.clear()
    pool._last_mint.clear()
    pool._mint_times.clear()


def test_a_rejection_wave_costs_one_mint_and_a_genuine_400_never_loops(keys, monkeypatch):
    accepted = {"k2"}
    monkeypatch.setattr(fetch, "_session", lambda: FakeSession(accepted))
    monkeypatch.setattr(fetch, "_drop_session", lambda: None)

    # the first request mints the key (k1); it is then rotated server-side.
    # The interval since that mint has passed, so a rejection may re-mint.
    assert fetch.algolia_key("companies") == "k1" and keys.mints == ["companies"]
    keys._last_mint["companies"] -= fetch.KEY_REFRESH_INTERVAL + 1

    results, errors = [], []

    def worker():
        try:
            results.append(fetch._algolia_search_once("YCCompany_production", {"query": "ai"}, "companies"))
        except Exception as e:                # pragma: no cover - the assert below reports it
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors and len(results) == 8 and all(r["nbHits"] == 0 for r in results)
    assert keys.mints == ["companies", "companies"], "a rejection wave across threads: ONE mint"
    assert fetch.algolia_key("companies") == "k2"

    # a 400 on the key minted seconds ago is a genuine bad request: the pool
    # hands the same key back, the second attempt fails, nothing is minted
    accepted.clear()
    with pytest.raises(fetch.YCBadRequest):
        fetch._algolia_search_once("YCCompany_production", {"query": "ai"}, "companies")
    assert keys.mints == ["companies", "companies"]

    # the other kind has its own identity
    assert fetch.algolia_key("founders") == "k3" and keys.mints[-1] == "founders"


# ---- the gateway exit (config.YCOMBINATOR_EXIT) -----------------------------------

DI = "http://u__cr.us:p@exit:1"


class ExitSession:
    """A session that only records which exit it was built on."""
    built = []

    def __init__(self, proxy, pages=None):
        self.proxy, self.pages, self.headers = proxy, pages or {}, {}
        ExitSession.built.append(proxy)

    def get(self, url, **kwargs):
        status, location = self.pages.get(url, (200, None))
        resp = FakeResponse(status, {"url": url})
        resp.headers = {"location": location} if location else {}
        resp.url = url
        return resp

    def close(self):
        pass


@pytest.fixture
def exits(monkeypatch):
    import config
    monkeypatch.setattr(config, "YCOMBINATOR_PROXY_COUNTRY", "us")
    monkeypatch.setattr(config, "YCOMBINATOR_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "residential_proxy", lambda country, states=None: f"http://u__cr.{country}:p@exit:1")
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    pages = {}
    monkeypatch.setattr(fetch.egress, "new_session", lambda proxy, impersonate=None: ExitSession(proxy, pages))
    fetch._drop_session()
    del ExitSession.built[:]
    ExitSession.pages = pages
    yield ExitSession
    fetch._drop_session()
    fetch._local.residential = False


@hosted_only
def test_gateway_first_residential_exit_on_the_last_retry(exits, monkeypatch):
    import config
    monkeypatch.setattr(config, "YCOMBINATOR_EXIT", None)
    assert config.ycombinator_proxy() == DI
    monkeypatch.setattr(config, "YCOMBINATOR_EXIT", "gateway")
    assert config.ycombinator_proxy() == "gateway" and config.ycombinator_proxy(fallback=True) == DI

    def failing(message):
        def fn():
            fetch._session()
            fetch._drop_session()                # what _request does on a failure
            raise fetch.YCUpstreamError(message)
        return fn

    # a block / 5xx: the gateway twice (a fresh gateway address each), the last try on the residential exit
    with pytest.raises(fetch.YCUpstreamError):
        fetch.with_retries(failing("x: HTTP 500"), "x")
    assert exits.built == ["gateway", "gateway", DI]

    # the gateway's own failure (29 s timeout, 10 MB cap): the residential exit at once
    del exits.built[:]
    with pytest.raises(fetch.YCUpstreamError):
        fetch.with_retries(failing("x: request failed: GatewayError: gateway 504 InternalServerErrorException for https://www.ycombinator.com/library"), "x")
    assert exits.built == ["gateway", DI, DI]

    # the fallback exit served that call only: the thread's next call is on the gateway again
    del exits.built[:]
    assert fetch.with_retries(lambda: fetch._session().proxy, "x") == "gateway"

    # YCOMBINATOR_EXIT = None: every attempt on a fresh residential exit, as before
    monkeypatch.setattr(config, "YCOMBINATOR_EXIT", None)
    fetch._drop_session()
    del exits.built[:]
    with pytest.raises(fetch.YCUpstreamError):
        fetch.with_retries(failing("x: HTTP 500"), "x")
    assert exits.built == [DI, DI, DI]


@hosted_only
def test_a_redirect_between_ycs_own_hosts_is_followed_on_the_gateway(exits, monkeypatch):
    """workatastartup.com/companies/<slug> of a company with no open jobs
    redirects to ycombinator.com; the gateway hands that 302 back (another
    site), a curl session follows it. A foreign host is never followed."""
    import config
    monkeypatch.setattr(config, "YCOMBINATOR_EXIT", "gateway")
    waas, yc = "https://www.workatastartup.com/companies/brex", "https://www.ycombinator.com/companies/brex"
    exits.pages[waas] = (302, yc)
    assert fetch._request("GET", waas).url == yc
    exits.pages[waas] = (302, "https://brex.com/careers")
    with pytest.raises(fetch.YCUpstreamError, match="unexpected HTTP 302"):
        fetch._request("GET", waas)
