"""Cache TTL per /y-combinator/* endpoint (cache.py, keyed on the validated
params).

The directory changes when a batch is announced (3-4 times a year) and
when founders edit profiles (a trickle); hiring flags and job postings
move daily; launches land several a day; the blog a few times a week.
"""
from datetime import timedelta

# --- companies -----------------------------------------------------------------
COMPANY_SEARCH_CACHE = timedelta(hours=6)        # companies/search, /top, /new, /directory, /browse, /highlights
COMPANY_CACHE = timedelta(hours=12)              # companies/details, /founders, /launches
COMPANY_JOBS_CACHE = timedelta(hours=1)          # companies/jobs

# --- founders ------------------------------------------------------------------
FOUNDER_SEARCH_CACHE = timedelta(hours=6)
FOUNDER_CACHE = timedelta(hours=12)

# --- jobs ----------------------------------------------------------------------
JOB_SEARCH_CACHE = timedelta(minutes=30)
JOB_CACHE = timedelta(hours=6)

# --- launches ------------------------------------------------------------------
LAUNCH_SEARCH_CACHE = timedelta(minutes=30)
LAUNCH_CACHE = timedelta(hours=12)

# --- partners / blog / library -------------------------------------------------
PARTNERS_CACHE = timedelta(days=1)
BLOG_LIST_CACHE = timedelta(hours=2)
BLOG_POST_CACHE = timedelta(days=1)
LIBRARY_SEARCH_CACHE = timedelta(hours=6)
LIBRARY_ARTICLE_CACHE = timedelta(days=1)

# --- meta ----------------------------------------------------------------------
META_CACHE = timedelta(hours=6)                  # filters, batches, stats
