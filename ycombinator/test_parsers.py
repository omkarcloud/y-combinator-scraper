"""Offline tests for the Y Combinator normalizers, resolvers and schemas
against the trimmed raw payloads in fixtures/ (captured 2026-10-19).

    python -m pytest ycombinator/test_parsers.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ycombinator import parsers as P  # noqa: E402
from ycombinator import refs  # noqa: E402
from ycombinator import schemas  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def props(name):
    return fixture(name)["props"]


# ---- value helpers ------------------------------------------------------------------

def test_batch_normalization():
    assert refs.normalize_batch("W24") == {"code": "W24", "name": "Winter 2024"}
    assert refs.normalize_batch("winter-2024")["code"] == "W24"
    assert refs.normalize_batch("W2024")["code"] == "W24"
    assert refs.normalize_batch("X25") == {"code": "P25", "name": "Spring 2025"}
    assert refs.normalize_batch("Spring 2025")["code"] == "P25"
    assert refs.normalize_batch("Fall 2026")["code"] == "F26"
    assert refs.batch_block("w2012") == {"code": "W12", "name": "Winter 2012"}
    assert refs.batch_block("Unspecified") == {"code": None, "name": None}
    assert refs.batch_block(None) == {"code": None, "name": None}
    for bad in ("Q24", "2024", "W1999", "hello", ""):
        with pytest.raises(ValueError):
            refs.normalize_batch(bad)
    assert [b["code"] for b in refs.resolve_batches("W24, s23,W24")] == ["W24", "S23"]


def test_resolvers():
    assert refs.resolve_company("airbnb") == "airbnb"
    assert refs.resolve_company("271") == "271"
    assert refs.resolve_company("https://www.ycombinator.com/companies/airbnb/jobs") == "airbnb"
    assert refs.resolve_company("https://www.workatastartup.com/companies/coris") == "coris"
    assert refs.resolve_company("bookface.ycombinator.com/company/271") == "271"
    assert refs.resolve_founder("brian-chesky") == {"slug": "brian-chesky", "id": None}
    assert refs.resolve_founder("21981") == {"slug": None, "id": 21981}
    assert refs.resolve_founder("https://www.ycombinator.com/founders/brian-chesky")["slug"] == "brian-chesky"
    assert refs.resolve_job("116108") == {"id": 116108, "company": None, "hash": None}
    assert refs.resolve_job("https://www.workatastartup.com/jobs/116108")["id"] == 116108
    link = "https://www.ycombinator.com/companies/coris/jobs/h0nDly8-backend-engineer-ai-native"
    assert refs.resolve_job(link) == {"id": None, "company": "coris", "hash": "h0nDly8"}
    assert refs.resolve_job("coris/h0nDly8")["hash"] == "h0nDly8"
    assert refs.resolve_launch("https://www.ycombinator.com/launches/VrR-asakana-x") == "VrR-asakana-x"
    assert refs.resolve_partner("https://www.ycombinator.com/people/Garry-Tan") == "garry-tan"
    assert refs.resolve_post("welcome-vivian-and-raphael") == "welcome-vivian-and-raphael"
    assert refs.resolve_article("https://www.ycombinator.com/library/dx-ai-safety") == "dx-ai-safety"
    for fn, bad in ((refs.resolve_company, "https://boards.greenhouse.io/x"), (refs.resolve_job, "abc"),
                    (refs.resolve_founder, "Brian Chesky"), (refs.resolve_company, ""),
                    (refs.resolve_company, "https://www.ycombinator.com/founders/brian-chesky")):
        with pytest.raises(ValueError):
            fn(bad)


def test_money_and_percent():
    assert P.money_range("$160 - $175") == {"min": 160000, "max": 175000, "currency": "USD", "raw": "$160 - $175"}
    assert P.money_range("$120K - $150K")["max"] == 150000
    assert P.money_range("₹6M - ₹8M INR") == {"min": 6000000, "max": 8000000, "currency": "INR", "raw": "₹6M - ₹8M INR"}
    assert P.money_range("₹10L - ₹20L")["min"] == 1000000
    assert P.money_range("$80K+") == {"min": 80000, "max": None, "currency": "USD", "raw": "$80K+"}
    assert P.money_range("€60K - €80K")["currency"] == "EUR"
    assert P.money_range("Competitive") == {"min": None, "max": None, "currency": None, "raw": "Competitive"}
    assert P.money_range("") is None and P.money_range(None) is None
    assert P.percent_range("0.25% - 0.50%") == {"min_percent": 0.25, "max_percent": 0.5, "raw": "0.25% - 0.50%"}
    assert P.percent_range("0.1%")["max_percent"] == 0.1
    assert P.percent_range("") is None


def test_dates_and_text():
    assert P.iso_utc("2026-10-01T09:52:00.000-07:00") == "2026-10-01T16:52:00Z"
    assert P.iso_utc("2026-10-16T19:00:00.208Z") == "2026-10-16T19:00:00Z"
    assert P.iso_utc(1367523459) == "2013-05-02T19:37:39Z"
    assert P.iso_utc(None) is None and P.iso_utc("") is None and P.iso_utc(0) is None
    assert P.iso_date("May 09, 2023") == "2023-05-09" and P.iso_date("2023-05-09T10:00:00Z") == "2023-05-09"
    text = P.markdown_text("**TL;DR:** Food [x](http://a) <https://b>\n\n## Head\n- item")
    assert text == "TL;DR: Food x https://b\n\nHead\n- item"
    assert P.markdown_block(None) is None and P.html_block("<p>&nbsp;</p>") is None
    assert P.html_block("<p>Hi <b>there</b></p>") == {"html": "<p>Hi <b>there</b></p>", "text": "Hi there"}
    assert P.pagination(2, 20, 45) == {"page": 2, "items_per_page": 20, "total_pages": 3, "total_count": 45}
    assert P.pagination(1, 50, None, total_pages=4)["total_count"] is None


# ---- companies ---------------------------------------------------------------------------

def test_company_from_hit():
    hit = fixture("algolia_companies_airbnb.json")["hits"][0]
    card = P.company_from_hit(hit)
    assert card["id"] == 271 and card["slug"] == "airbnb" and card["link"] == "https://www.ycombinator.com/companies/airbnb"
    assert card["batch"] == {"code": "W09", "name": "Winter 2009"} and card["status"] == "public"
    assert card["team_size"] > 1000 and card["launched_at"].endswith("Z") and card["logo"].startswith("https://")
    assert card["primary_industry"] == "Consumer" and card["subindustry"] == "Travel, Leisure and Tourism"
    assert "Consumer" in card["industries"] and card["location"]["regions"] and card["location"]["all"]
    assert card["is_top_company"] is True and card["is_nonprofit"] is False and isinstance(card["is_hiring"], bool)
    assert "_highlightResult" not in card and "objectID" not in card
    assert P.company_from_hit({})["id"] is None and P.company_from_hit(None)["batch"] == {"code": None, "name": None}


def test_company_from_api_row():
    row = fixture("api_v01_companies_w24.json")["companies"][0]
    card = P.company_from_api(row)
    assert card["batch"]["code"] == "W24" and card["slug"] and card["industries"] and card["location"]["cities"]
    assert card["status"] in ("active", "inactive", "acquired", "public") and "badges" in card


def test_company_from_page():
    page = props("company_page_coris.json")
    company = P.company_from_page(page)
    assert company["id"] == 26882 and company["slug"] == "coris" and company["batch"]["code"] == "S22"
    assert company["year_founded"] == 2022 and company["status"] == "active" and company["website"] == "https://coris.ai/"
    assert company["social"]["linkedin"] and company["social"]["facebook"] is None
    assert company["group_partner"]["slug"] and company["group_partner"]["link"].startswith("https://www.ycombinator.com/people/")
    assert len(company["founders"]) == 2 and company["founders"][0]["social"]["linkedin"] and company["founders"][0]["company"]["slug"] == "coris"
    assert company["launches"][0]["body"]["text"] and company["launches"][0]["company"]["slug"] == "coris"
    assert company["jobs"][0]["hash"] and company["jobs"][0]["salary"]["currency"] == "USD" and company["jobs"][0]["company"]["id"] == 26882
    assert company["news"][0]["date"] == "2024-02-01" and company["jobs_link"].endswith("/companies/coris/jobs")
    assert company["videos"] == {"demo_day": None, "application": None}
    empty = P.company_from_page({})
    assert empty["founders"] == [] and empty["jobs"] == [] and empty["slug"] is None


def test_company_from_list_row_and_waas():
    page = props("company_list_page_fintech_sf.json")
    rows = [P.company_from_list_row(c) for c in page["companies"]]
    assert rows and rows[0]["slug"] and rows[0]["batch"]["code"] and "social" in rows[0] and rows[0]["location"]["country"]
    assert page["industryName"] == "Financial Technology and Services" and page["totalPages"] >= 1
    waas = P.company_from_waas(props("waas_company_coris.json")["company"])
    assert waas["slug"] == "coris" and waas["hiring_description"]["text"] and waas["tech_description"]["html"]
    assert waas["founders"][0]["past_companies"] and waas["founders"][0]["social"]["linkedin"]
    assert waas["primary_industry"] == "B2B" and waas["subindustry"] == "Infrastructure"


# ---- founders ----------------------------------------------------------------------------

def test_founder_from_hit():
    hit = fixture("algolia_founders_chesky.json")["hits"][0]
    founder = P.founder_from_hit(hit)
    assert founder["id"] == 21981 and founder["slug"] == "brian-chesky" and founder["name"] == "Brian Chesky"
    assert founder["link"] == "https://www.ycombinator.com/founders/brian-chesky" and founder["hacker_news_username"] == "brianchesky"
    assert founder["company"] == {"slug": "airbnb", "name": "Airbnb", "link": "https://www.ycombinator.com/companies/airbnb"}
    assert founder["batches"] == [{"code": "W09", "name": "Winter 2009"}] and founder["is_top_company"] is True
    assert founder["industries"] == ["Consumer"] and founder["subindustries"] == ["Travel, Leisure and Tourism"]
    assert "_tags" not in founder and P.founder_from_hit({})["name"] is None


# ---- jobs ----------------------------------------------------------------------------------

def test_job_card():
    page = props("jobs_role_page_eng_sf.json")
    jobs = [P.job_card(j) for j in page["jobPostings"]]
    assert len(jobs) == 3
    job = jobs[0]
    assert job["id"] and job["hash"] and job["link"].startswith("https://www.ycombinator.com/companies/")
    assert job["work_at_a_startup_link"] == f"https://www.workatastartup.com/jobs/{job['id']}"
    assert job["company"]["slug"] and job["company"]["link"] and job["role"]["category"] == "eng" and job["role"]["name"] == "Engineering"
    assert job["salary"] is None or job["salary"]["raw"]
    assert isinstance(job["skills"], list) and isinstance(job["can_ask_questions"], bool)
    assert "ctaText" not in job and "ctaUrl" not in job
    assert P.job_card({})["company"]["slug"] is None


def test_job_from_page_and_waas():
    job = P.job_from_page(props("job_page_coris_h0nDly8.json"))
    assert job["id"] == 116108 and job["hash"] == "h0nDly8" and job["company"]["id"] == 26882 and job["company"]["founders"]
    assert job["description"]["markdown"].startswith("## ") and job["description"]["text"].startswith("🧠 About Coris")
    assert job["interview_process"]["text"].startswith("1. Initial screen")
    assert job["hiring_manager"]["name"] == "Shyam Maddali" and job["custom_questions"][0]["is_required"] is True
    assert len(job["related_jobs"]) == 2 and job["related_jobs"][0]["company"]["slug"]
    assert job["company"]["hiring_description"]["text"] and job["company"]["shows_founder_contact"] is True
    waas = P.job_from_waas(props("waas_job_116108.json"))
    assert waas["id"] == 116108 and waas["description"]["html"].startswith("<h2>") and waas["skills"] == ["Django", "JavaScript", "PostgreSQL", "Python", "TypeScript"]
    assert waas["company"]["slug"] == "coris" and waas["other_jobs"][0]["salary"]["min"] == 120000
    assert waas["similar_jobs"][0]["company"]["slug"] and waas["custom_questions"]


# ---- launches ---------------------------------------------------------------------------

def test_launches():
    feed = fixture("launches_feed.json")
    card = P.launch_card(feed["hits"][0])
    assert card["id"] and card["slug"] and card["link"] == f"https://www.ycombinator.com/launches/{card['slug']}"
    assert card["created_at"].endswith("Z") and card["vote_count"] >= 0 and card["company"]["batch"]["code"]
    assert "body" not in card
    launch = P.launch_from_json(fixture("launch_json.json"), props("launch_page.json")["post"])
    assert launch["body"]["markdown"] and launch["body"]["text"] and launch["author"]["name"] and launch["state"] == "public"
    assert launch["approved_at"] and launch["published_at"] and launch["company"]["slug"] and launch["upvote_embed_link"]
    assert P.launch_from_json({}, None)["author"] is None


# ---- partners / blog / library ----------------------------------------------------------

def test_partners():
    people = props("people_page.json")
    cards = [P.partner_card(p, s["title"]) for s in people["sections"] for p in s["people"]]
    assert cards[0]["slug"] == "garry-tan" and cards[0]["group"] == "President & CEO" and cards[0]["photo"].startswith("https://")
    partner = P.partner_from_page(props("partner_page_garry_tan.json"))
    assert partner["slug"] == "garry-tan" and partner["social"]["twitter"] == "https://twitter.com/garrytan"
    assert partner["companies"][0]["name"] and partner["press"][0]["publisher"] and partner["tweets"][0]["date"]
    assert partner["library_articles"][0]["video"]["youtube_id"] and partner["blog_posts"][0]["link"]


def test_blog():
    listing = props("blog_list.json")
    post = P.post_card(listing["posts"][0])
    assert post["slug"] and post["link"] == f"https://www.ycombinator.com/blog/{post['slug']}" and post["published_at"].endswith("Z")
    assert post["feature_image"].startswith("https://www.ycombinator.com/blog/content/") and post["authors"][0]["slug"]
    assert post["tags"][0]["link"].startswith("https://www.ycombinator.com/blog/tag/") and "html" not in post
    assert listing["pagination"]["total"] > 2000
    full = P.post_from_page(props("blog_post.json"))
    assert full["content"]["html"].startswith("<p>") and full["content"]["text"] and full["related_posts"][0]["title"]
    assert "uuid" not in full and "og_image" not in full


def test_library():
    article = P.article_from_page(props("library_article.json"))
    assert article["slug"] == "dx-ai-safety-fact-vs-fiction" and article["video"]["youtube_id"] == "X7oI4Umt3DU"
    assert article["series"] == "Paper Club" and article["has_transcript"] is True and article["transcript"]
    assert article["cover_photo"].startswith("https://www.ycombinator.com/media?")
    assert article["related_articles"][0]["link"].startswith("https://www.ycombinator.com/library/")
    no_transcript = P.article_from_page(props("library_article.json"), include_transcript=False)
    assert no_transcript["transcript"] is None and no_transcript["has_transcript"] is True


# ---- schemas -------------------------------------------------------------------------------

def test_schemas():
    data = schemas.CompanySearchSchema().load({"batch": "W24,s23", "industry": "fintech", "is_hiring": "true",
                                              "launched_since": "2026-01-01", "per_page": "50"})
    assert [b["code"] for b in data["batch"]] == ["W24", "S23"] and data["industry"] == ["fintech"]
    assert data["is_hiring"] is True and data["launched_since"] == "2026-01-01T00:00:00Z" and data["per_page"] == 50
    assert schemas.JobsSearchSchema().load({"role": "software-engineer"})["role"] == "eng"
    assert schemas.JobSchema().load({"job": "coris/h0nDly8"})["job"]["hash"] == "h0nDly8"
    assert schemas.CompanyHighlightsSchema().load({"group": "Women Founders"})["group"] == "women-founders"
    assert schemas.LaunchesSearchSchema().load({"batch": "Fall 2026"})["batch"]["name"] == "Fall 2026"
    assert schemas.ArticleSchema().load({"article": "x", "refresh": "true"})["refresh"] is True
    from marshmallow import ValidationError
    for schema, bad in ((schemas.CompanySearchSchema, {"batch": "Q24"}), (schemas.CompanySearchSchema, {"bogus": "1"}),
                        (schemas.JobsSearchSchema, {"role": "astronaut"}), (schemas.CompanyHighlightsSchema, {}),
                        (schemas.FounderSchema, {"founder": "Brian Chesky"}), (schemas.CompanySearchSchema, {"per_page": "500"})):
        with pytest.raises(ValidationError):
            schema().load(bad)
