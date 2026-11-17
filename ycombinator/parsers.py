"""Y Combinator normalizers: Algolia hits, the public v0.1 API rows, the
Inertia page props and the Work at a Startup props -> one clean
snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for page
URLs (always absolute), `*_count` for counters, `is_*`/`has_*` for
booleans, ISO-8601 UTC timestamps ("2026-10-16T19:00:00Z") and ISO
dates, numbers as numbers, money as amount + `currency`, null for missing.

Shapes:

  company card   {id, slug, name, link, website, logo, one_liner, description,
                  batch{code, name}, status, stage, team_size, launched_at,
                  industries[], primary_industry, subindustry, tags[],
                  location{all, city, country, regions[]}, is_hiring,
                  is_top_company, is_nonprofit, has_demo_day_video,
                  has_app_video}
  company        card + {year_founded, logo_large, social{linkedin, twitter,
                  facebook, crunchbase, github}, group_partner{…},
                  founders[], photos[], videos{demo_day, application},
                  application_answers[], news[], launches[], jobs[]}
  founder        {id, slug, name, first_name, last_name, link, avatar, title,
                  bio, company{…}, companies_text, batches[], region,
                  industries[], is_top_company, is_active, social{…}}
  job            {id, hash, title, link, apply_link, company{…}, location,
                  job_type, role{category, name, specialty}, salary{min, max,
                  currency, raw}, equity{min_percent, max_percent, raw},
                  min_experience, min_school_year, visa, skills[],
                  hiring_manager{…}, posted_ago, last_active_ago,
                  can_ask_questions, is_incomplete}
                 + details: description{markdown, text}, interview_process{…},
                  custom_questions[], related_jobs[]
  launch         {id, slug, title, tagline, link, created_at, vote_count,
                  company{…}} + details: body{markdown, text}, author, …
  partner        {slug, name, link, title, bio, photo} + details
  post           {id, slug, title, link, excerpt, feature_image, is_featured,
                  published_at, updated_at, reading_time_minutes, authors[],
                  tags[]} + details: content{html, text}
  article        {id, slug, title, link, description, author, authors[],
                  categories[], series, video{…}, spotify_id, cover_photo,
                  published_at, view_access} + details: content, transcript

Deliberately dropped as noise or duplicates:
  * Algolia `_highlightResult`, `tags_highlighted`, `objectID` (= id),
    `_tags` (the ycdc_public ACL tag), `app_answers` / `question_answers`
    (booleans about gated content a visitor cannot read);
  * presigned S3 `X-Amz-*` query strings are KEPT on the large logo /
    avatar / photo links (the bucket is private; the link works ~1 h) but
    the small unsigned logo is the default `logo`;
  * page plumbing: currentUser, editUrl, createProfileUrl, signupUrl,
    loginUrl, waasDirectoryUrl, showDirectApply, userCanRequestEmails,
    investorSubdomain, debugInfo, isMobile, formUrl, carousel, videos
    (marketing), peopleImgUrls, events, flashes, nav, footerLogoPath,
    variantChrome, roleOptions (echoed via /filters), ctaText/ctaUrl
    (= "Apply" + apply_link);
  * Ghost internals on blog posts: uuid, comment_id, visibility,
    email_recipient_filter, codeinjection_*, custom_template,
    canonical_url, og_* / twitter_* / meta_* (null on every post),
    email_subject, frontmatter, access, the ghost.prod.ycinside.com `url`;
  * library bookkeeping: bookmarked, video_progress_seconds,
    carousel_sort_order, title_in_thumbnail, feature_score, ranking,
    root_id, sus_curriculum.
"""
import re
from datetime import datetime, timezone

import html as html_lib

from ycombinator import refs
from scraper_utils.text import squashed as text
from scraper_utils.values import bool_or_none as flag, to_int

STATUS_MAP = {"active": "active", "inactive": "inactive", "acquired": "acquired", "public": "public"}
ROLE_NAMES = {"eng": "Engineering", "design": "Design", "product": "Product", "science": "Science",
              "sales": "Sales", "marketing": "Marketing", "support": "Support", "operations": "Operations",
              "recruiting": "Recruiting & HR", "finance": "Finance", "legal": "Legal"}
CURRENCY_SYMBOLS = {"$": "USD", "US$": "USD", "C$": "CAD", "CA$": "CAD", "A$": "AUD", "AU$": "AUD",
                    "£": "GBP", "€": "EUR", "₹": "INR", "¥": "JPY", "₩": "KRW", "R$": "BRL", "S$": "SGD",
                    "CHF": "CHF", "kr": "SEK", "zł": "PLN", "₪": "ILS", "₱": "PHP", "₦": "NGN", "MX$": "MXN"}
_MONEY_RE = re.compile(r"(US\$|CA\$|AU\$|MX\$|C\$|A\$|R\$|S\$|CHF|kr|zł|[$£€₹¥₩₪₱₦])?\s*([\d][\d,]*(?:\.\d+)?)\s*([KkMmLl])?")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_AUTOLINK_RE = re.compile(r"<(https?://[^>]+)>")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_MARK_RE = re.compile(r"(\*\*|__|~~|`{1,3})")
_MD_HEADER_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.M)
_MD_QUOTE_RE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.M)
_MD_LIST_RE = re.compile(r"^[ \t]*[-*+][ \t]+", re.M)
_MD_EMPH_RE = re.compile(r"(?<![\w*])[*_]([^*_\n]+)[*_](?![\w*])")
_NEWS_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d")


# ---- text / number helpers (same behaviour as lever.parsers; the generic ones
# come from scraper_utils) ---------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"<\s*(?:br\s*/?|/p|/div|/li|/h[1-6]|/tr)\s*>", re.I)
_LI_RE = re.compile(r"<\s*li[^>]*>", re.I)


def to_float(value):
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def clean_html(value):
    """Rich text -> plain text with paragraph / list breaks kept."""
    if not isinstance(value, str) or not value.strip():
        return None
    out = _LI_RE.sub("- ", value)
    out = _BREAK_RE.sub("\n", out)
    out = html_lib.unescape(_TAG_RE.sub("", out)).replace("\xa0", " ").replace("\r", "")
    lines = [" ".join(line.split()) for line in out.split("\n")]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or None


def plain(value):
    """Already-plain text with stray nbsp / CRs and ragged whitespace cleaned."""
    if not isinstance(value, str):
        return None
    out = value.replace("\xa0", " ").replace("\r", "")
    lines = [" ".join(line.split()) for line in out.split("\n")]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or None


# ---- value helpers ------------------------------------------------------------

def link(value):
    """Absolute https link or None (empty strings and bare '/' die here)."""
    out = refs.absolute(value) if isinstance(value, str) else None
    return out if out and out not in ("https://www.ycombinator.com/",) else None


def website(value):
    value = text(value)
    if not value:
        return None
    if not value.lower().startswith(("http://", "https://")):
        value = "https://" + value
    return value


def iso_utc(value):
    """'2026-10-16T19:00:00.208Z' | '2026-10-01T09:52:00.000-07:00' | unix
    seconds -> '2026-10-16T19:00:00Z'."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.isdigit():
        return iso_utc(int(raw))
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value):
    """'May 09, 2023' | '2023-05-09T…' -> '2023-05-09'."""
    value = text(value)
    if not value:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    for fmt in _NEWS_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def str_list(values):
    if not isinstance(values, list):
        return []
    out = []
    for v in values:
        if isinstance(v, list):          # founders' yc_industries are nested pairs
            out.extend(str_list(v))
            continue
        v = text(v) if isinstance(v, str) else None
        if v and v not in out:
            out.append(v)
    return out


def status(value):
    value = text(value)
    return STATUS_MAP.get(value.lower()) if value else None


def markdown_text(value):
    """Launch bodies / job descriptions are markdown; a plain-text twin."""
    if not isinstance(value, str) or not value.strip():
        return None
    out = _MD_IMAGE_RE.sub("", value)
    out = _MD_AUTOLINK_RE.sub(r"\1", out)
    out = _MD_LINK_RE.sub(r"\1", out)
    out = _MD_HEADER_RE.sub("", out)
    out = _MD_QUOTE_RE.sub("", out)
    out = _MD_LIST_RE.sub("- ", out)
    out = _MD_MARK_RE.sub("", out)
    out = _MD_EMPH_RE.sub(r"\1", out)
    return plain(out)


def markdown_block(value):
    value = value if isinstance(value, str) and value.strip() else None
    return {"markdown": value, "text": markdown_text(value)} if value else None


def html_block(value):
    value = value if isinstance(value, str) and clean_html(value) else None
    return {"html": value, "text": clean_html(value)} if value else None


def pagination(page, per_page, total, total_pages=None):
    """total=None with total_pages given = the upstream paginates but never
    says how many rows there are (total_count stays null)."""
    total = to_int(total)
    if total_pages is None:
        total = total or 0
        total_pages = (total + per_page - 1) // per_page if total else 0
    return {"page": page, "items_per_page": per_page, "total_pages": total_pages, "total_count": total}


def _subindustry(value):
    """'B2B -> Infrastructure' -> 'Infrastructure'; 'Fintech' -> None (no
    sub-industry)."""
    value = text(value)
    if not value:
        return None
    if "->" in value:
        return text(value.split("->", 1)[1])
    return None


def _primary(value, industries):
    value = text(value)
    if value and "->" in value:
        value = text(value.split("->", 1)[0])
    return value or (industries[0] if industries else None)


# ---- money ------------------------------------------------------------------------

def money_range(raw):
    """'$160K - $175K' | '$160 - $175' (K implied) | '₹10L - ₹20L' | '$80K+'
    -> {min, max, currency, raw}."""
    raw = text(raw)
    if not raw:
        return None
    amounts, currency = [], None
    for symbol, number, suffix in _MONEY_RE.findall(raw):
        if not number:
            continue
        try:
            value = float(number.replace(",", ""))
        except ValueError:
            continue
        suffix = (suffix or "").upper()
        if suffix == "K":
            value *= 1_000
        elif suffix == "M":
            value *= 1_000_000
        elif suffix == "L":
            value *= 100_000
        elif value < 1_000:
            value *= 1_000            # "$160 - $175" is written in thousands
        amounts.append(int(round(value)))
        if symbol and not currency:
            currency = CURRENCY_SYMBOLS.get(symbol.strip())
    if not amounts:
        return {"min": None, "max": None, "currency": currency, "raw": raw}
    low = min(amounts)
    high = max(amounts) if len(amounts) > 1 else (None if raw.rstrip().endswith("+") else low)
    return {"min": low, "max": high, "currency": currency or ("USD" if "$" in raw else None), "raw": raw}


def percent_range(raw):
    """'0.25% - 0.50%' -> {min_percent, max_percent, raw}."""
    raw = text(raw)
    if not raw:
        return None
    values = [float(v) for v in _PERCENT_RE.findall(raw)]
    if not values:
        return {"min_percent": None, "max_percent": None, "raw": raw}
    return {"min_percent": min(values), "max_percent": max(values) if len(values) > 1 else min(values), "raw": raw}


# ---- companies ----------------------------------------------------------------------

def _company_base(raw):
    slug = text(raw.get("slug"))
    return {
        "id": to_int(raw.get("id")),
        "slug": slug,
        "name": text(raw.get("name")),
        "link": refs.company_link(slug),
    }


def company_from_hit(hit):
    """An Algolia YCCompany_production hit -> company card."""
    hit = hit if isinstance(hit, dict) else {}
    industries = str_list(hit.get("industries"))
    out = _company_base(hit)
    out.update({
        "former_names": str_list(hit.get("former_names")),
        "website": website(hit.get("website")),
        "logo": link(hit.get("small_logo_thumb_url")),
        "one_liner": text(hit.get("one_liner")),
        "description": plain(hit.get("long_description")),
        "batch": refs.batch_block(hit.get("batch")),
        "status": status(hit.get("status")),
        "stage": text(hit.get("stage")),
        "team_size": to_int(hit.get("team_size")),
        "launched_at": iso_utc(hit.get("launched_at")),
        "industries": industries,
        "primary_industry": _primary(hit.get("industry"), industries),
        "subindustry": _subindustry(hit.get("subindustry")),
        "tags": str_list(hit.get("tags")),
        "location": {
            "all": text(hit.get("all_locations")),
            "regions": str_list(hit.get("regions")),
        },
        "is_hiring": flag(hit.get("isHiring")),
        "is_top_company": flag(hit.get("top_company")),
        "is_nonprofit": flag(hit.get("nonprofit")),
        "has_demo_day_video": flag(hit.get("demo_day_video_public")),
        "has_app_video": flag(hit.get("app_video_public")),
    })
    return out


def company_from_api(row):
    """A row of api.ycombinator.com/v0.1/companies -> company card."""
    row = row if isinstance(row, dict) else {}
    industries = str_list(row.get("industries"))
    out = _company_base(row)
    out.update({
        "website": website(row.get("website")),
        "logo": link(row.get("smallLogoUrl")),
        "one_liner": text(row.get("oneLiner")),
        "description": plain(row.get("longDescription")),
        "batch": refs.batch_block(row.get("batch")),
        "status": status(row.get("status")),
        "team_size": to_int(row.get("teamSize")),
        "industries": industries,
        "primary_industry": industries[0] if industries else None,
        "subindustry": industries[1] if len(industries) > 1 else None,
        "tags": str_list(row.get("tags")),
        "location": {
            "all": ", ".join(str_list(row.get("locations"))) or None,
            "cities": str_list(row.get("locations")),
            "regions": str_list(row.get("regions")),
        },
        # badges are camelCase tokens (the fixture's "isHiring"): match "topCompany" and "Top Company"
        "is_top_company": any(b.replace(" ", "").lower() == "topcompany" for b in str_list(row.get("badges"))) or None,
        "badges": str_list(row.get("badges")),
    })
    return out


def _social(raw, keys):
    return {public: link(raw.get(key)) or None for public, key in keys.items()}


_COMPANY_SOCIAL = {"linkedin": "linkedin_url", "twitter": "twitter_url", "facebook": "fb_url",
                   "crunchbase": "cb_url", "github": "github_url"}


def company_from_list_row(row):
    """A row of the curated list pages (/companies/industry/<slug>…) and
    the highlight pages (women / black / hispanic-latino founders)."""
    row = row if isinstance(row, dict) else {}
    out = _company_base(row)
    out.update({
        "website": website(row.get("website")),
        "logo": link(row.get("small_logo_url")),
        "logo_large": link(row.get("logo_url")),
        "one_liner": text(row.get("one_liner")),
        "description": plain(row.get("long_description")),
        "batch": refs.batch_block(row.get("batch_name") or row.get("batch")),
        "status": status(row.get("ycdc_status")),
        "team_size": to_int(row.get("team_size")),
        "year_founded": to_int(row.get("year_founded")),
        "tags": str_list(row.get("tags")),
        "location": {
            "all": text(row.get("location")),
            "city": text(row.get("city")),
            "city_slug": text(row.get("city_tag")),
            "country": text(row.get("country")),
        },
        "social": _social(row, _COMPANY_SOCIAL),
    })
    return out


def founder_from_company(raw, company=None):
    """A founder block of a company page -> founder."""
    raw = raw if isinstance(raw, dict) else {}
    latest = raw.get("latest_yc_company") if isinstance(raw.get("latest_yc_company"), dict) else {}
    name = text(raw.get("full_name"))
    return {
        "id": to_int(raw.get("user_id")),
        "name": name,
        "title": text(raw.get("title")),
        "bio": plain(raw.get("founder_bio")),
        "avatar": link(raw.get("avatar_thumb_url")),
        "is_active": flag(raw.get("is_active")),
        "has_email": flag(raw.get("has_email")),
        "company": company or {"name": text(latest.get("name")), "link": link(latest.get("href"))},
        "social": {"linkedin": link(raw.get("linkedin_url")), "twitter": link(raw.get("twitter_url"))},
    }


def group_partner(raw):
    raw = raw if isinstance(raw, dict) else {}
    if not raw:
        return None
    partner_url = link(raw.get("url"))
    return {
        "id": to_int(raw.get("id")),
        "name": text(raw.get("full_name")),
        "slug": partner_url.rstrip("/").rsplit("/", 1)[-1] if partner_url else None,
        "link": partner_url,
        "avatar": link(raw.get("avatar_thumb_url")),
    }


def news_item(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {"title": text(raw.get("title")), "link": link(raw.get("url")), "date": iso_date(raw.get("date"))}


def company_photo(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {"id": to_int(raw.get("id")), "link": link(raw.get("url")), "type": text(raw.get("photo_type"))}


def application_answer(raw):
    raw = raw if isinstance(raw, dict) else {}
    question = text(raw.get("question") or raw.get("label") or raw.get("title"))
    answer = raw.get("answer") or raw.get("response") or raw.get("body")
    return {"question": question, "answer": plain(answer) if isinstance(answer, str) else answer}


def company_from_page(props):
    """The /companies/<slug> Inertia props -> full company profile."""
    props = props if isinstance(props, dict) else {}
    raw = props.get("company") if isinstance(props.get("company"), dict) else {}
    out = company_from_list_row(raw)
    slug = out["slug"]
    out["batch"] = refs.batch_block(raw.get("batch_name") or raw.get("batch"))
    company_ref = {"id": out["id"], "slug": slug, "name": out["name"], "link": out["link"]}
    out.update({
        "group_partner": group_partner(raw.get("primary_group_partner")),
        "founders": [founder_from_company(f, company_ref) for f in raw.get("founders") or [] if isinstance(f, dict)],
        "photos": [company_photo(p) for p in raw.get("company_photos") or [] if isinstance(p, dict)],
        "videos": {"demo_day": link(raw.get("dday_video_url")), "application": link(raw.get("app_video_url"))},
        "application_answers": [application_answer(a) for a in (raw.get("app_answers") or []) +
                                (raw.get("free_response_question_answers") or []) if isinstance(a, dict)],
        "news": [news_item(n) for n in props.get("newsItems") or [] if isinstance(n, dict)],
        "launches": [launch_card(l) for l in props.get("launches") or [] if isinstance(l, dict)],
        "jobs": [job_card(j, company_ref) for j in props.get("jobPostings") or [] if isinstance(j, dict)],
        "jobs_link": refs.company_jobs_link(slug),
        "work_at_a_startup_link": refs.waas_company_link(slug),
    })
    return out


def company_from_waas(raw):
    """The workatastartup.com company block (hiring blurb, tech blurb, the
    founders' past companies)."""
    raw = raw if isinstance(raw, dict) else {}
    slug = text(raw.get("slug"))
    industries = str_list(raw.get("industries"))
    return {
        "slug": slug,
        "name": text(raw.get("name")),
        "link": refs.waas_company_link(slug),
        "batch": refs.batch_block(raw.get("batch")),
        "one_liner": text(raw.get("description")),
        "logo": link(raw.get("logoUrl")),
        "website": website(raw.get("url")),
        "location": text(raw.get("location")),
        "team_size": to_int(raw.get("teamSize")),
        "industries": industries,
        "primary_industry": _primary(raw.get("industry"), industries),
        "subindustry": _subindustry(raw.get("industry")),
        "hiring_description": html_block(raw.get("hiringDescriptionHtml")),
        "tech_description": html_block(raw.get("techDescriptionHtml")),
        "social": {"twitter": link(raw.get("twitterUrl")), "facebook": link(raw.get("facebookUrl"))},
        "founders": [{
            "name": text(f.get("name")),
            "avatar": link(f.get("avatarUrl")),
            "bio": plain(f.get("bio")),
            "past_companies": text(f.get("pastCompanies")),
            "social": {"linkedin": link(f.get("linkedin"))},
        } for f in raw.get("founders") or [] if isinstance(f, dict)],
    }


# ---- founders -------------------------------------------------------------------------

def founder_from_hit(hit):
    """An Algolia YCUsers_production hit -> founder card."""
    hit = hit if isinstance(hit, dict) else {}
    first, last = text(hit.get("first_name")), text(hit.get("last_name"))
    slug = text(hit.get("url_slug"))
    company_slug = text(hit.get("company_slug"))
    return {
        "id": to_int(hit.get("id")),
        "slug": slug,
        "name": " ".join(p for p in (first, last) if p) or None,
        "first_name": first,
        "last_name": last,
        "link": refs.founder_link(slug),
        "avatar": link(hit.get("avatar_thumb")),
        "hacker_news_username": text(hit.get("hnid")),
        "title": text(hit.get("current_title")),
        "titles": str_list(hit.get("yc_titles")),
        "company": {
            "slug": company_slug,
            "name": text(hit.get("current_company")),
            "link": refs.company_link(company_slug),
        },
        "companies_text": text(hit.get("all_companies_text")),
        "batches": [refs.batch_block(b) for b in str_list(hit.get("batches"))],
        "region": text(hit.get("current_region")) if text(hit.get("current_region")) != "Unspecified" else None,
        "industries": str_list(hit.get("yc_parent_industries")),
        "subindustries": [s for s in (_subindustry(v) for v in str_list(hit.get("yc_subindustries"))) if s],
        "is_top_company": flag(hit.get("top_company")),
    }


# ---- jobs ------------------------------------------------------------------------------

def _job_hash(url):
    """'/companies/coris/jobs/h0nDly8-backend-engineer' -> 'h0nDly8'."""
    if not isinstance(url, str):
        return None
    tail = url.rstrip("/").rsplit("/jobs/", 1)
    return tail[1].split("-", 1)[0] if len(tail) == 2 and tail[1] else None


def _company_slug_from_url(url):
    if not isinstance(url, str):
        return None
    match = re.search(r"/companies/([^/?#]+)", url)
    return match.group(1) if match else None


def hiring_manager(raw):
    raw = raw if isinstance(raw, dict) else {}
    if not raw:
        return None
    first, last = text(raw.get("first_name")), text(raw.get("last_name"))
    return {
        "id": to_int(raw.get("id")),
        "name": " ".join(p for p in (first, last) if p) or None,
        "avatar": link(raw.get("avatar_medium") or raw.get("avatar_thumb")),
    }


def job_card(raw, company=None):
    """A jobPostings row of any YC jobs page -> job."""
    raw = raw if isinstance(raw, dict) else {}
    slug = _company_slug_from_url(raw.get("companyUrl") or raw.get("url"))
    job_hash = _job_hash(raw.get("url"))
    role = text(raw.get("role"))
    company_block = {
        "id": (company or {}).get("id"),
        "slug": slug,
        "name": text(raw.get("companyName")) or (company or {}).get("name"),
        "link": refs.company_link(slug),
        "logo": link(raw.get("companyLogoUrl")),
        "batch": refs.batch_block(raw.get("companyBatchName")),
        "one_liner": text(raw.get("companyOneLiner")),
    }
    return {
        "id": to_int(raw.get("id")),
        "hash": job_hash,
        "title": text(raw.get("title")),
        "link": link(raw.get("url")),
        "apply_link": link(raw.get("applyUrl") or raw.get("ctaUrl")),
        "work_at_a_startup_link": refs.waas_job_link(to_int(raw.get("id"))),
        "company": company_block,
        "location": text(raw.get("location")),
        "job_type": text(raw.get("type")),
        "role": {
            "category": role,
            "name": text(raw.get("prettyRole")) or ROLE_NAMES.get(role or ""),
            "specialty": text(raw.get("roleSpecificType")),
        },
        "salary": money_range(raw.get("salaryRange")),
        "equity": percent_range(raw.get("equityRange")),
        "min_experience": text(raw.get("minExperience")),
        "min_school_year": text(raw.get("minSchoolYear")),
        "visa": text(raw.get("visa")),
        "skills": str_list(raw.get("skills")),
        "hiring_manager": hiring_manager(raw.get("hiringManager")),
        "posted_ago": text(raw.get("createdAt")),
        "last_active_ago": text(raw.get("lastActive")),
        "can_ask_questions": flag(raw.get("askUs")),
        "is_incomplete": flag(raw.get("isIncomplete")),
    }


def custom_question(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": to_int(raw.get("id")),
        "label": text(raw.get("label")),
        "type": text(raw.get("question_type")),
        "is_required": flag(raw.get("required")),
        "options": str_list(raw.get("options")),
    }


def job_from_page(props):
    """The /companies/<slug>/jobs/<hash> Inertia props -> full job."""
    props = props if isinstance(props, dict) else {}
    company_raw = props.get("company") if isinstance(props.get("company"), dict) else {}
    raw = props.get("job") if isinstance(props.get("job"), dict) else {}
    company_ref = {"id": to_int(company_raw.get("id")), "name": text(company_raw.get("name"))}
    out = job_card(raw, company_ref)
    out.update({
        "description": markdown_block(raw.get("description")),
        "interview_process": markdown_block(raw.get("interview_process")),
        "custom_questions": [custom_question(q) for q in props.get("customQuestions") or [] if isinstance(q, dict)],
        "related_jobs": [job_card(j) for j in props.get("relatedJobs") or [] if isinstance(j, dict)],
    })
    if company_raw:
        profile = company_from_list_row(company_raw)
        profile.pop("logo_large", None)
        hiring = plain(company_raw.get("hiring_description"))
        profile["hiring_description"] = {"html": None, "text": hiring} if hiring else None
        profile["founders"] = [founder_from_company(f, {"id": profile["id"], "slug": profile["slug"],
                                                        "name": profile["name"], "link": profile["link"]})
                               for f in company_raw.get("founders") or [] if isinstance(f, dict)]
        profile["shows_founder_contact"] = flag(company_raw.get("show_founder_contact"))
        out["company"] = {**profile, **{k: v for k, v in out["company"].items()
                                        if v is not None and v != {"code": None, "name": None} and k != "id"}}
    return out


def job_from_waas(props):
    """The workatastartup.com/jobs/<id> props -> job (what the YC page
    lacks: HTML description + interview process; what it lacks: role,
    hiring manager, posted-ago)."""
    props = props if isinstance(props, dict) else {}
    raw = props.get("job") if isinstance(props.get("job"), dict) else {}
    company = company_from_waas(props.get("company"))
    job_id = to_int(raw.get("id"))
    return {
        "id": job_id,
        "title": text(raw.get("title")),
        "link": refs.waas_job_link(job_id),
        "apply_link": link(props.get("applyUrl")),
        "company": company,
        "location": text(raw.get("location")),
        "job_type": text(raw.get("jobType")),
        "salary": money_range(raw.get("salaryRange")),
        "equity": percent_range(raw.get("equityRange")),
        "min_experience": text(raw.get("minExperience")),
        "visa": text(raw.get("sponsorsVisa")),
        "skills": str_list(raw.get("skills")),
        "description": html_block(raw.get("descriptionHtml")),
        "interview_process": html_block(raw.get("interviewProcessHtml")),
        "custom_questions": [custom_question(q) for q in props.get("customQuestions") or [] if isinstance(q, dict)],
        "other_jobs": [{
            "id": to_int(j.get("id")),
            "title": text(j.get("title")),
            "link": refs.waas_job_link(to_int(j.get("id"))),
            "location": text(j.get("location")),
            "job_type": text(j.get("jobType")),
            "salary": money_range(j.get("salaryRange")),
            "equity": percent_range(j.get("equityRange")),
            "min_experience": text(j.get("minExperience")),
        } for j in props.get("otherJobs") or [] if isinstance(j, dict)],
        "similar_jobs": [{
            "id": to_int(j.get("id")),
            "title": text(j.get("title")),
            "link": refs.waas_job_link(to_int(j.get("id"))),
            "location": text(j.get("location")),
            "job_type": text(j.get("jobType")),
            "role": {"specialty": text(j.get("roleType"))},
            "salary": money_range(j.get("salary")),
            "company": {
                "slug": text(j.get("companySlug")),
                "name": text(j.get("companyName")),
                "link": refs.company_link(text(j.get("companySlug"))),
                "batch": refs.batch_block(j.get("companyBatch")),
                "one_liner": text(j.get("companyOneLiner")),
                "logo": link(j.get("companyLogo") or j.get("companyLogoUrl")),
            },
        } for j in props.get("similarJobs") or [] if isinstance(j, dict)],
    }


def job_role_option(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {"value": text(raw.get("value")), "name": text(raw.get("label"))}


def slug_name(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {"slug": text(raw.get("slug")), "name": text(raw.get("name"))}


# ---- launches -----------------------------------------------------------------------

def _launch_company(raw):
    raw = raw if isinstance(raw, dict) else {}
    slug = text(raw.get("slug"))
    return {
        "id": to_int(raw.get("id") or raw.get("model_id")),
        "slug": slug,
        "name": text(raw.get("name")),
        "link": refs.company_link(slug),
        "website": website(raw.get("url")),
        "logo": link(raw.get("logo")),
        "one_liner": text(raw.get("description")),
        "batch": refs.batch_block(raw.get("batch")),
        "primary_industry": text(raw.get("industry")),
        "tags": str_list(raw.get("tags")),
    }


def launch_card(raw):
    """A launches feed hit (or a company page's launches row) -> launch."""
    raw = raw if isinstance(raw, dict) else {}
    slug = text(raw.get("slug"))
    out = {
        "id": to_int(raw.get("id")),
        "slug": slug,
        "title": text(raw.get("title") or raw.get("sanitized_title")),
        "tagline": text(raw.get("tagline")),
        "link": refs.launch_link(slug) or link(raw.get("url")),
        "created_at": iso_utc(raw.get("created_at")),
        "vote_count": to_int(raw.get("total_vote_count")),
        "company": _launch_company(raw.get("company")),
    }
    if raw.get("body"):
        out["body"] = markdown_block(raw.get("body"))
    return out


def launch_from_json(doc, page_post=None):
    """/launches/<slug>.json (+ the launch page's `post` props for the
    author and approval facts) -> full launch."""
    doc = doc if isinstance(doc, dict) else {}
    post = page_post if isinstance(page_post, dict) else {}
    out = launch_card(doc)
    user = post.get("user") if isinstance(post.get("user"), dict) else {}
    approver = post.get("approved_by") if isinstance(post.get("approved_by"), dict) else {}
    out.update({
        "body": markdown_block(doc.get("body") or post.get("body")),
        "updated_at": iso_utc(doc.get("updated_at")),
        "published_at": iso_utc(post.get("requested_publish_at")) or out["created_at"],
        "approved_at": iso_utc(post.get("approved_at")),
        "state": text(post.get("state")),
        "author": {"name": text(user.get("name")), "avatar": link(user.get("avatar"))} if user else None,
        "approved_by": {"name": text(approver.get("name")), "hacker_news_username": text(approver.get("hnid"))}
        if approver else None,
        "share_image": link(doc.get("share_image_url") or post.get("share_image")),
        "twitter_share_link": link(post.get("twitter_share_url")),
        "upvote_embed_link": link(post.get("launch_embed_url")),
    })
    if not out["company"].get("one_liner") and isinstance(post.get("company"), dict):
        out["company"]["one_liner"] = text(post["company"].get("description"))
    return out


# ---- partners (YC people) ---------------------------------------------------------------

def partner_card(raw, group=None):
    raw = raw if isinstance(raw, dict) else {}
    page = link(raw.get("url"))
    return {
        "slug": page.rstrip("/").rsplit("/", 1)[-1] if page else None,
        "name": text(raw.get("name")),
        "link": page,
        "title": text(raw.get("title")),
        "group": group,
        "bio": plain(raw.get("bio")),
        "photo": link(raw.get("photo")),
    }


def _handle_link(base, handle):
    handle = text(handle)
    return f"{base}{handle.lstrip('@')}" if handle else None


def partner_from_page(props):
    props = props if isinstance(props, dict) else {}
    raw = props.get("partner") if isinstance(props.get("partner"), dict) else {}
    slug = text(raw.get("slug"))
    return {
        "id": to_int(raw.get("id")),
        "slug": slug,
        "name": text(raw.get("name")),
        "link": refs.partner_link(slug),
        "avatar": link(raw.get("avatar_thumb")),
        "bio": plain(raw.get("bio")),
        "hacker_news_username": text(raw.get("hnid")),
        "blog_link": link(raw.get("blog")),
        "social": {
            "twitter": _handle_link("https://twitter.com/", raw.get("twitter_handle")),
            "linkedin": _handle_link("https://www.linkedin.com/in/", raw.get("linkedin_handle")),
            "instagram": _handle_link("https://www.instagram.com/", raw.get("instagram_handle")),
            "threads": _handle_link("https://www.threads.net/@", raw.get("threads_handle")),
        },
        "stats": [{"label": text(s.get("label") or s.get("name") or s.get("title")),
                   "value": s.get("value") if not isinstance(s.get("value"), str) else text(s.get("value"))}
                  if isinstance(s, dict) else {"label": None, "value": s}
                  for s in raw.get("stats") or []],
        "companies": [{
            "id": to_int(c.get("id")),
            "name": text(c.get("name")),
            "logo": link(c.get("image")),
            "website": website(c.get("url")),
        } for c in raw.get("companies") or [] if isinstance(c, dict)],
        "blog_posts": [{"title": text(p.get("title")), "link": link(p.get("url"))}
                       for p in raw.get("posts") or [] if isinstance(p, dict)],
        "press": [{"title": text(a.get("title")), "link": link(a.get("url")), "publisher": text(a.get("publisher"))}
                  for a in raw.get("articles") or [] if isinstance(a, dict)],
        "tweets": [{"text": plain(t.get("text")), "link": link(t.get("url")), "date": iso_date(t.get("date"))}
                   for t in raw.get("tweets") or [] if isinstance(t, dict)],
        "videos": [{"title": text(v.get("title")), "link": link(v.get("link") or v.get("url")),
                    "embed_link": link(v.get("url"))}
                   for v in raw.get("videos") or [] if isinstance(v, dict)],
        "library_articles": [article_card(a) for a in raw.get("library_articles") or [] if isinstance(a, dict)],
    }


# ---- blog -----------------------------------------------------------------------------

def _blog_image(value):
    value = text(value)
    if not value:
        return None
    if value.startswith("/"):
        return "https://www.ycombinator.com" + value
    return link(value)


def blog_author(raw):
    raw = raw if isinstance(raw, dict) else {}
    slug = text(raw.get("slug"))
    return {
        "name": text(raw.get("name")),
        "slug": slug,
        "link": f"https://www.ycombinator.com/blog/author/{slug}" if slug else None,
        "bio": plain(raw.get("bio")),
        "avatar": _blog_image(raw.get("profile_image")),
        "twitter": _handle_link("https://twitter.com/", raw.get("twitter")),
        "website": website(raw.get("website")),
        "location": text(raw.get("location")),
    }


def blog_tag(raw):
    raw = raw if isinstance(raw, dict) else {}
    slug = text(raw.get("slug"))
    return {
        "name": text(raw.get("name")),
        "slug": slug,
        "link": f"https://www.ycombinator.com/blog/tag/{slug}" if slug else None,
        "description": text(raw.get("description")),
    }


def post_card(raw):
    raw = raw if isinstance(raw, dict) else {}
    slug = text(raw.get("slug"))
    return {
        "id": text(raw.get("id")),
        "slug": slug,
        "title": text(raw.get("title")),
        "link": refs.post_link(slug),
        "excerpt": plain(raw.get("custom_excerpt") or raw.get("excerpt")),
        "feature_image": _blog_image(raw.get("feature_image")),
        "feature_image_caption": clean_html(raw.get("feature_image_caption")),
        "is_featured": flag(raw.get("featured")),
        "published_at": iso_utc(raw.get("published_at")),
        "updated_at": iso_utc(raw.get("updated_at")),
        "reading_time_minutes": to_int(raw.get("reading_time")),
        "authors": [blog_author(a) for a in raw.get("authors") or [] if isinstance(a, dict)],
        "tags": [blog_tag(t) for t in raw.get("tags") or [] if isinstance(t, dict)],
    }


def post_from_page(props):
    props = props if isinstance(props, dict) else {}
    raw = props.get("post") if isinstance(props.get("post"), dict) else {}
    out = post_card(raw)
    out["content"] = html_block(raw.get("html"))
    out["mentions"] = [m for m in props.get("mentions") or []] if isinstance(props.get("mentions"), list) else []
    out["related_posts"] = [post_card(p) for p in props.get("related_posts") or [] if isinstance(p, dict)]
    return out


# ---- library -------------------------------------------------------------------------

def _media_link(value):
    value = text(value)
    if not value:
        return None
    return "https://www.ycombinator.com" + value if value.startswith("/") else link(value)


def article_card(raw):
    raw = raw if isinstance(raw, dict) else {}
    slug = text(raw.get("slug"))
    youtube_id = text(raw.get("youtube_id"))
    return {
        "id": to_int(raw.get("id")),
        "slug": slug,
        "title": text(raw.get("title")),
        "link": refs.article_link(slug),
        "description": plain(raw.get("description")),
        "author": text(raw.get("author")),
        "authors": [{"name": text(a.get("name")), "link": link(a.get("url"))}
                    for a in raw.get("authors") or [] if isinstance(a, dict)],
        "categories": str_list(raw.get("categories_for_display") or raw.get("categories")),
        "series": text(raw.get("series_name")),
        "video": {
            "youtube_id": youtube_id,
            "link": link(raw.get("link")) or (f"https://www.youtube.com/watch?v={youtube_id}" if youtube_id else None),
            "duration_seconds": to_int(raw.get("video_duration")),
            "view_count": to_int(raw.get("youtube_view_count")),
            "chapters": raw.get("video_chapters") if isinstance(raw.get("video_chapters"), list) else None,
        } if youtube_id or raw.get("link") else None,
        "spotify_id": text(raw.get("spotify_id")),
        "slides_link": link(raw.get("slides")),
        "cover_photo": _media_link(raw.get("cover_photo")),
        "published_at": iso_utc(raw.get("created_at")),
        "view_access": text(raw.get("view_access")),
    }


def article_from_page(props, include_transcript=True):
    props = props if isinstance(props, dict) else {}
    raw = props.get("article") if isinstance(props.get("article"), dict) else {}
    out = article_card(raw)
    out["content"] = html_block(raw.get("content")) or markdown_block(raw.get("content"))
    out["transcript"] = plain(raw.get("transcript")) if include_transcript else None
    out["has_transcript"] = bool(text(raw.get("transcript")))
    out["carousel"] = text(props.get("carouselName"))
    out["related_articles"] = [article_card(a) for a in props.get("relatedArticles") or [] if isinstance(a, dict)]
    nxt = props.get("nextArticle")
    out["next_article"] = article_card(nxt) if isinstance(nxt, dict) else None
    return out


def library_carousel(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": to_int(raw.get("id")),
        "name": text(raw.get("name")),
        "description": plain(raw.get("description")),
        "articles": [article_card(a) for a in raw.get("articles") or [] if isinstance(a, dict)],
    }
