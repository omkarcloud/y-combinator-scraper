"""Live endpoint smoke tests: one call per /y-combinator/* route against a
running service, with example values proven to return data (2026-10-19).
The listing tooling reads each route's FIRST call from this file's AST as
its working example, so the values stay literals.

Skipped unless YCOMBINATOR_BASE points at a running service:

    ONLY_SCRAPER=y-combinator python run.py
    YCOMBINATOR_BASE=http://127.0.0.1:6002 python -m pytest ycombinator/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("YCOMBINATOR_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set YCOMBINATOR_BASE to run live endpoint tests")


def call(path, expect=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=300)
    assert resp.status_code == expect, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_company_search():
    page = call("/y-combinator/companies/search", query="ai fintech", per_page=5)
    assert page["count"] > 100 and len(page["companies"]) == 5 and page["next"]
    first = page["companies"][0]
    assert first["slug"] and first["link"].startswith("https://www.ycombinator.com/companies/") and first["batch"]["code"]
    filtered = call("/y-combinator/companies/search", batch="W24,S23", is_hiring="true", industry="Fintech", per_page=5)
    assert 0 < filtered["count"] < page["count"]
    assert all(c["batch"]["code"] in ("W24", "S23") and c["is_hiring"] for c in filtered["companies"])
    newest = call("/y-combinator/companies/search", sort="newest", launched_since="90d", per_page=5)["companies"]
    assert newest[0]["launched_at"] >= newest[-1]["launched_at"]
    big = call("/y-combinator/companies/search", team_size_min=1000, status="public")["companies"]
    assert big and all(c["team_size"] >= 1000 and c["status"] == "public" for c in big)
    assert call("/y-combinator/companies/search", region="United Kingdom", tag="SaaS", subindustry="Infrastructure")["companies"]


def test_company_views():
    top = call("/y-combinator/companies/top", per_page=10)
    assert top["count"] > 50 and all(c["is_top_company"] for c in top["companies"])
    new = call("/y-combinator/companies/new", since="7d", per_page=10)
    assert new["since"].endswith("Z") and new["companies"] and new["companies"][0]["launched_at"] >= new["since"]


def test_company_details():
    company = call("/y-combinator/companies/details", company="airbnb")["company"]
    assert company["id"] == 271 and company["batch"]["code"] == "W09" and company["status"] == "public"
    assert company["founders"][0]["name"] and company["founders"][0]["social"]["linkedin"]
    assert company["social"]["crunchbase"] and company["year_founded"] == 2008 and company["team_size"] > 1000
    assert company["group_partner"]["slug"] and company["news"] and company["location"]["regions"]
    by_link = call("/y-combinator/companies/details", company="https://www.ycombinator.com/companies/coris")["company"]
    assert by_link["slug"] == "coris" and by_link["jobs"] and by_link["launches"] and by_link["hiring_description"]["text"]
    assert by_link["founders"][0]["past_companies"] and by_link["is_hiring"] is True


def test_company_jobs_founders_launches():
    jobs = call("/y-combinator/companies/jobs", company="coris")
    assert jobs["company"]["slug"] == "coris" and jobs["jobs_count"] >= 1 and jobs["jobs"][0]["salary"]["currency"] == "USD"
    founders = call("/y-combinator/companies/founders", company="coris")
    assert founders["founders_count"] == 2 and founders["founders"][0]["slug"] and founders["founders"][0]["hacker_news_username"]
    launches = call("/y-combinator/companies/launches", company="asakana")
    assert launches["launches_count"] >= 1 and launches["launches"][0]["body"]["text"]


def test_company_lists():
    page = call("/y-combinator/companies/browse", industry="fintech", location="san-francisco-bay-area", page=2)
    assert page["current_page"] == 2 and page["count"] > 100 and len(page["companies"]) == 50
    assert page["list"]["industry"]["name"] == "Financial Technology and Services" and page["companies"][0]["social"]
    hiring = call("/y-combinator/companies/browse", industry="healthcare", hiring_only="true")
    assert hiring["list"]["is_hiring_only"] and hiring["companies"]
    assert call("/y-combinator/companies/browse", location="india")["companies"]
    dump = call("/y-combinator/companies/directory", page=1)
    assert dump["total_pages"] > 200 and len(dump["companies"]) == 25 and dump["companies"][0]["batch"]["code"]
    filtered = call("/y-combinator/companies/directory", batch="W24", is_hiring="true")
    assert all(c["batch"]["code"] == "W24" for c in filtered["companies"])
    women = call("/y-combinator/companies/highlights", group="women-founders", batch="W24", per_page=10)
    assert women["count"] > 10 and women["stats"] and all(c["batch"]["code"] == "W24" for c in women["companies"])


def test_founders():
    found = call("/y-combinator/founders/search", query="brian chesky")
    assert found["founders"][0]["slug"] == "brian-chesky" and found["founders"][0]["company"]["slug"] == "airbnb"
    ctos = call("/y-combinator/founders/search", batch="W24", title="CTO", per_page=10)
    assert ctos["count"] > 50 and all("W24" in [b["code"] for b in f["batches"]] for f in ctos["founders"])
    founder = call("/y-combinator/founders/details", founder="brian-chesky")["founder"]
    assert founder["id"] == 21981 and founder["bio"] and founder["social"]["linkedin"] and founder["company"]["name"] == "Airbnb"
    assert founder["cofounders"] and founder["past_companies"]
    assert call("/y-combinator/founders/details", founder="21981")["founder"]["slug"] == "brian-chesky"


def test_jobs_search():
    eng = call("/y-combinator/jobs/search", role="engineering", location="san francisco", per_page=10)
    assert eng["count"] > 20 and eng["facets"]["roles"] and eng["sources"] == ["https://www.ycombinator.com/jobs/role/software-engineer/san-francisco"]
    assert all(j["role"]["category"] == "eng" for j in eng["jobs"]) and eng["jobs"][0]["company"]["batch"]["code"]
    python = call("/y-combinator/jobs/search", query="python", per_page=10)
    assert python["jobs"] and len(python["sources"]) == 10
    paid = call("/y-combinator/jobs/search", is_remote="true", job_type="full-time", sort="salary", has_salary="true")
    assert paid["jobs"] and all("remote" in j["location"].lower() and j["salary"]["min"] for j in paid["jobs"])
    assert paid["jobs"][0]["salary"]["max"] >= paid["jobs"][-1]["salary"]["max"]
    assert call("/y-combinator/jobs/search", batch="S24,W25", skill="Python,TypeScript", visa="sponsor", min_experience="3")["count"] >= 0


def test_job_details():
    job = call("/y-combinator/jobs/details",
               job="https://www.ycombinator.com/companies/coris/jobs/h0nDly8-backend-engineer-ai-native-risk-infrastructure-integrations")["job"]
    assert job["id"] == 116108 and job["hash"] == "h0nDly8" and job["description"]["markdown"] and job["description"]["html"]
    assert job["salary"]["min"] == 160000 and job["equity"]["max_percent"] == 0.5 and job["skills"]
    assert job["company"]["founders"] and job["related_jobs"] and job["custom_questions"] and job["similar_jobs"]
    by_id = call("/y-combinator/jobs/details", job="116108")["job"]
    assert by_id["hash"] == "h0nDly8" and by_id["source"] == "ycombinator.com + workatastartup.com"


def test_launches():
    feed = call("/y-combinator/launches/search", per_page=10)
    assert feed["count"] > 3000 and feed["launches"][0]["company"]["batch"]["code"] and feed["launches"][0]["vote_count"] is not None
    robots = call("/y-combinator/launches/search", query="robot", batch="F26")
    assert robots["launches"] and all(l["company"]["batch"]["code"] == "F26" for l in robots["launches"])
    launch = call("/y-combinator/launches/details",
                  launch="VrR-asakana-automating-sales-and-the-entire-back-office-for-food-distributors")["launch"]
    assert launch["body"]["markdown"] and launch["author"]["name"] and launch["company"]["slug"] == "asakana"


def test_partners_blog_library():
    partners = call("/y-combinator/partners/list", group="partners")
    assert partners["people_count"] > 10 and partners["people"][0]["slug"] and len(partners["groups"]) > 10
    garry = call("/y-combinator/partners/details", partner="garry-tan")["partner"]
    assert garry["social"]["twitter"] and garry["companies"] and garry["library_articles"]
    posts = call("/y-combinator/blog/posts", page=1)
    assert posts["count"] > 2000 and posts["per_page"] == 10 and posts["posts"][0]["published_at"] and posts["featured"]
    assert call("/y-combinator/blog/posts", author="garry")["posts"]
    post = call("/y-combinator/blog/details", post="welcome-vivian-and-raphael")["post"]
    assert post["content"]["html"] and post["content"]["text"] and post["authors"][0]["slug"] == "garry"
    library = call("/y-combinator/library/search", query="sam altman", per_page=10)
    assert library["count"] > 5 and library["articles"][0]["video"]["youtube_id"] and library["carousels"]
    viewed = call("/y-combinator/library/search", sort="views", per_page=10)["articles"]
    assert viewed[0]["video"]["view_count"] >= viewed[1]["video"]["view_count"]
    article = call("/y-combinator/library/details", article="dx-ai-safety-fact-vs-fiction")["article"]
    assert article["transcript"] and article["has_transcript"] and article["related_articles"]


def test_meta():
    filters = call("/y-combinator/filters")
    assert filters["companies"]["batches"][0]["code"] and filters["companies"]["industries"] and filters["founders"]["titles"]
    assert filters["jobs"]["locations"] and filters["jobs"]["roles"]
    batches = call("/y-combinator/batches")
    assert batches["current_batch"]["code"] and batches["batches_count"] >= 50 and batches["batches"][0]["company_count"]
    stats = call("/y-combinator/stats")
    assert stats["companies"]["total_count"] > 6000 and stats["founders"]["total_count"] > 10000


def test_errors():
    # paths via variables so the listing tooling never reads an error case
    # as a route's working example
    details, browse, founder = "/y-combinator/companies/details", "/y-combinator/companies/browse", "/y-combinator/founders/details"
    job, launch, partner, search = "/y-combinator/jobs/details", "/y-combinator/launches/details", "/y-combinator/partners/details", "/y-combinator/companies/search"
    call(details, expect=404, company="zzzz-nonexistent-xyz")
    call(details, expect=400, company="https://boards.greenhouse.io/spotify")
    call(search, expect=400, batch="Q24")
    call(search, expect=400, bogus="1")
    call(browse, expect=404, industry="zzz-nonexistent")
    call(browse, expect=400)
    call(founder, expect=404, founder="zzzz-nonexistent-founder")
    call(founder, expect=400, founder="Brian Chesky")
    call(job, expect=404, job="1")
    call(job, expect=404, job="coris/zzzzzzz")
    call(launch, expect=404, launch="zzz-nonexistent")
    call(partner, expect=404, partner="brian-chesky")
