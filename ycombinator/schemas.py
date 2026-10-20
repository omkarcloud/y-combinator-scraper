"""Marshmallow request schemas for every /y-combinator/* route. Generic
fields come from the shared schema_fields.py; this module adds the YC
resolvers. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    company   a directory slug (airbnb), the numeric id (271) OR any
              ycombinator.com / workatastartup.com company link
    founder   a founder slug (brian-chesky), the numeric user id OR a
              /founders/<slug> link
    job       a posting id (116108), a workatastartup.com/jobs/<id> link, a
              ycombinator.com/companies/<c>/jobs/<hash>-… link OR <company>/<hash>
    launch    a launch slug OR its /launches/<slug> link
    partner   a people slug (garry-tan) OR its /people/<slug> link
    post      a blog slug OR its /blog/<slug> link
    article   a library slug OR its /library/<slug> link
    batch     W24 | S23 | F26 | X25 / P25 | "Winter 2024" (comma lists where noted)

Every schema accepts `refresh=true` (skip and overwrite the cached row).
"""
import re
from datetime import datetime, timedelta, timezone

from marshmallow import ValidationError, validate

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, PageField, PageSizeField,
                           PositiveInt, QueryField, RefField, StrippedString, TrueOnlyFlag)
from ycombinator import refs

STATUSES = ["active", "inactive", "acquired", "public"]
COMPANY_SORTS = ["relevance", "newest"]
JOB_ROLES = {
    "engineering": "eng", "eng": "eng", "software-engineer": "eng",
    "design": "design", "designer": "design",
    "product": "product", "product-manager": "product",
    "science": "science",
    "sales": "sales", "sales-manager": "sales",
    "marketing": "marketing",
    "support": "support",
    "operations": "operations",
    "recruiting": "recruiting", "recruiting-hr": "recruiting", "hr": "recruiting",
    "finance": "finance",
    "legal": "legal",
}
JOB_TYPES = ["full-time", "contract", "internship", "part-time", "fellowship"]
JOB_SORTS = ["relevance", "newest", "salary"]
HIGHLIGHT_GROUPS = ["women-founders", "black-founders", "hispanic-latino-founders"]
LIBRARY_SORTS = ["relevance", "newest", "views"]
_RELATIVE_RE = re.compile(r"^(\d{1,4})\s*(h|hours?|d|days?|w|weeks?|m|months?|y|years?)$", re.I)


# ---- fields -----------------------------------------------------------------------------

class CompanyField(RefField):
    resolver = staticmethod(refs.resolve_company)


class FounderField(RefField):
    resolver = staticmethod(refs.resolve_founder)


class JobField(RefField):
    resolver = staticmethod(refs.resolve_job)


class LaunchField(RefField):
    resolver = staticmethod(refs.resolve_launch)


class PartnerField(RefField):
    resolver = staticmethod(refs.resolve_partner)


class PostField(RefField):
    resolver = staticmethod(refs.resolve_post)


class ArticleField(RefField):
    resolver = staticmethod(refs.resolve_article)


class BatchField(RefField):
    """One batch -> {"code", "name"}."""
    resolver = staticmethod(refs.normalize_batch)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class BatchListField(RefField):
    """Comma-separated batches -> [{"code", "name"}, …]."""
    resolver = staticmethod(refs.resolve_batches)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class SinceField(StrippedString):
    """A moment: relative ('24h', '7d', '2w', '3m', '1y') or absolute
    (YYYY-MM-DD or an ISO datetime) -> an ISO UTC timestamp, rounded down
    to the hour so the same '7d' shares a cache row for an hour."""

    def __init__(self, default=None, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", (lambda: since_default(default)) if default else None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        match = _RELATIVE_RE.match(value)
        if match:
            amount, unit = int(match.group(1)), match.group(2).lower()[0]
            delta = {"h": timedelta(hours=amount), "d": timedelta(days=amount), "w": timedelta(weeks=amount),
                     "m": timedelta(days=30 * amount), "y": timedelta(days=365 * amount)}[unit]
            if delta > timedelta(days=366 * 25):
                raise ValidationError("At most 25 years back.")
            return (_hour_now() - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError("Must be relative (24h, 7d, 2w, 3m, 1y) or a date (YYYY-MM-DD or ISO datetime).")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed > datetime.now(timezone.utc) + timedelta(days=1):
            raise ValidationError("Must not be in the future.")
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour_now():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def since_default(relative):
    return SinceField()._deserialize(relative, None, None)


def _max_length(n):
    """Length(max=n) that tolerates the None an optional StrippedString
    yields for an empty value."""
    return lambda value: value is None or bool(validate.Length(max=n)(value))


def _text(max_length=100):
    return StrippedString(required=False, load_default=None, validate=_max_length(max_length))


def _names(max_items=10):
    """Comma-separated facet values, case kept (canonicalized downstream)."""
    return CommaListField(upper=False, max_items=max_items)


class RefreshSchema(BaseSchema):
    CACHE_REFRESH = True
    refresh = TrueOnlyFlag(load_default=False)


# ---- companies ----------------------------------------------------------------------------

class CompanySearchSchema(RefreshSchema):
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    batch = BatchListField()
    industry = _names()
    subindustry = _names()
    tag = _names()
    region = _names()
    status = ChoiceField(STATUSES)
    is_hiring = Flag()
    is_top_company = Flag()
    is_nonprofit = Flag()
    has_demo_day_video = Flag()
    has_app_video = Flag()
    team_size_min = PositiveInt(max_value=1_000_000)
    team_size_max = PositiveInt(max_value=1_000_000)
    launched_since = SinceField()
    sort = ChoiceField(COMPANY_SORTS, load_default="relevance")
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=20, max_size=100)


class CompaniesTopSchema(RefreshSchema):
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    batch = BatchListField()
    industry = _names()
    page = PageField(max_page=100)
    per_page = PageSizeField(default=20, max_size=100)


class CompaniesNewSchema(RefreshSchema):
    since = SinceField(default="30d")
    batch = BatchListField()
    industry = _names()
    tag = _names()
    region = _names()
    page = PageField(max_page=100)
    per_page = PageSizeField(default=20, max_size=100)


class CompanySchema(RefreshSchema):
    company = CompanyField()


class CompanyBrowseSchema(RefreshSchema):
    """The curated list pages: industry and/or location slug, 50 a page."""
    industry = _text()
    location = _text()
    hiring_only = Flag(load_default=False)
    page = PageField(max_page=500)


class CompanyDirectorySchema(RefreshSchema):
    """YC's own open API: the whole directory, 25 (unfiltered) / 20
    (filtered) rows a page."""
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    batch = BatchField()
    status = ChoiceField(STATUSES)
    industry = _text()
    tag = _text()
    region = _text()
    is_hiring = Flag()
    is_nonprofit = Flag()
    is_top_company = Flag()
    page = PageField(max_page=1000)


class HighlightGroupField(StrippedString):
    """Required choice (ChoiceField is optional by construction)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = (super()._deserialize(value, attr, data, **kwargs) or "").lower().replace(" ", "-")
        if value not in HIGHLIGHT_GROUPS:
            raise ValidationError(f"Must be one of: {', '.join(HIGHLIGHT_GROUPS)}.")
        return value


class CompanyHighlightsSchema(RefreshSchema):
    group = HighlightGroupField()
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    batch = BatchListField()
    page = PageField(max_page=500)
    per_page = PageSizeField(default=20, max_size=100)


# ---- founders ------------------------------------------------------------------------------

class FounderSearchSchema(RefreshSchema):
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    batch = BatchListField()
    title = _names()
    industry = _names()
    subindustry = _names()
    region = _names()
    is_top_company = Flag()
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=20, max_size=100)


class FounderSchema(RefreshSchema):
    founder = FounderField()


# ---- jobs ------------------------------------------------------------------------------------

class JobRoleField(ChoiceField):
    def __init__(self, **kwargs):
        super().__init__(JOB_ROLES, **kwargs)


class JobsSearchSchema(RefreshSchema):
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    role = JobRoleField()
    location = _text()
    job_type = ChoiceField(JOB_TYPES)
    is_remote = Flag()
    batch = BatchListField()
    skill = _names()
    min_salary = PositiveInt(max_value=100_000_000)
    has_salary = Flag()
    has_equity = Flag()
    visa = _text()
    min_experience = _text(30)
    sort = ChoiceField(JOB_SORTS, load_default="relevance")
    page = PageField(max_page=100)
    per_page = PageSizeField(default=20, max_size=100)


class JobSchema(RefreshSchema):
    job = JobField()


# ---- launches ---------------------------------------------------------------------------------

class LaunchesSearchSchema(RefreshSchema):
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    batch = BatchField()
    page = PageField(max_page=500)
    per_page = PageSizeField(default=20, max_size=100)


class LaunchSchema(RefreshSchema):
    launch = LaunchField()


# ---- partners / blog / library -----------------------------------------------------------------

class PartnersSchema(RefreshSchema):
    query = QueryField(required=False, load_default=None, validate=_max_length(100))
    group = _text()


class PartnerSchema(RefreshSchema):
    partner = PartnerField()


class BlogPostsSchema(RefreshSchema):
    author = _text(80)
    tag = _text(80)
    page = PageField(max_page=1000)


class PostSchema(RefreshSchema):
    post = PostField()


class LibrarySearchSchema(RefreshSchema):
    query = QueryField(required=False, load_default=None, validate=_max_length(200))
    category = _text()
    series = _text()
    author = _text()
    sort = ChoiceField(LIBRARY_SORTS, load_default="relevance")
    page = PageField(max_page=100)
    per_page = PageSizeField(default=20, max_size=100)


class ArticleSchema(RefreshSchema):
    article = ArticleField()
    include_transcript = Flag(load_default=True)


# ---- meta -----------------------------------------------------------------------------------

class FiltersSchema(RefreshSchema):
    pass


class BatchesSchema(RefreshSchema):
    pass


class StatsSchema(RefreshSchema):
    pass
