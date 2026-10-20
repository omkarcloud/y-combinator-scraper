"""/y-combinator/filters, /batches, /stats — the vocabulary every filter
param accepts (with counts), the batch list and directory-wide totals.
"""
from ycombinator import directory
from ycombinator import jobs as J
from ycombinator import parsers as P
from ycombinator import refs
from ycombinator.fetch import page_payload, page_props, run_parallel, soft


def filters():
    vocab, jobs_props = run_parallel([
        directory.vocabulary,
        soft(lambda: page_props("/jobs", label="jobs")[1], default={}),
    ])
    jobs_props = jobs_props or {}
    vocab["jobs"] = {
        "roles": [{"value": public, "category": code, "page_slug": J.ROLE_PAGES.get(code)}
                  for code, public in sorted({v: k for k, v in {
                      "engineering": "eng", "design": "design", "product": "product", "science": "science",
                      "sales": "sales", "marketing": "marketing", "support": "support", "operations": "operations",
                      "recruiting": "recruiting", "finance": "finance", "legal": "legal"}.items()}.items(),
                                             key=lambda kv: kv[1])],
        "role_categories": [P.job_role_option(r) for r in jobs_props.get("roleOptions") or [] if isinstance(r, dict)],
        "locations": [P.slug_name(l) for l in jobs_props.get("jobLocations") or [] if isinstance(l, dict)],
        "job_types": ["full-time", "contract", "internship", "part-time", "fellowship"],
        "sorts": ["relevance", "newest", "salary"],
    }
    vocab["companies"]["sorts"] = ["relevance", "newest"]
    vocab["companies"]["highlight_groups"] = ["women-founders", "black-founders", "hispanic-latino-founders"]
    vocab["batch_formats"] = ["W24", "S23", "F26", "X25 / P25", "Winter 2024"]
    return vocab


def batches():
    vocab = directory.vocabulary()
    rows = vocab["companies"]["batches"]
    founder_counts = {b["code"]: b["founder_count"] for b in vocab["founders"]["batches"]}
    for row in rows:
        row["founder_count"] = founder_counts.get(row["code"])
        row["link"] = f"https://www.ycombinator.com/companies?batch={row['code']}"
    payload = soft(lambda: page_payload("/companies", label="companies"), default={})() or {}
    props = payload.get("props") if isinstance(payload.get("props"), dict) else {}
    rails = payload.get("rails_context") if isinstance(payload.get("rails_context"), dict) else {}
    return {
        "current_batch": refs.batch_block(props.get("currentBatch")) if props.get("currentBatch") else None,
        "applications_open_for": refs.batch_block(rails.get("applyBatchLong")) if rails.get("applyBatchLong") else None,
        "application_deadline": P.text(rails.get("applyDeadlineShort")),
        "batches_count": len(rows),
        "batches": rows,
    }


def stats():
    companies = directory.facets("companies")
    founders = directory.facets("founders")
    status_counts = {k.lower(): v for k, v in (companies.get("status") or {}).items()}
    return {
        "companies": {
            "total_count": companies.get("_total"),
            "by_status": status_counts,
            "hiring_count": (companies.get("isHiring") or {}).get("true"),
            "top_company_count": (companies.get("top_company") or {}).get("true"),
            "nonprofit_count": (companies.get("nonprofit") or {}).get("true"),
            "by_primary_industry": dict(sorted((companies.get("industry") or {}).items(), key=lambda kv: -kv[1])),
            "top_tags": dict(sorted((companies.get("tags") or {}).items(), key=lambda kv: -kv[1])[:25]),
            "top_regions": dict(sorted((companies.get("regions") or {}).items(), key=lambda kv: -kv[1])[:25]),
            "batches_count": len([b for b in (companies.get("batch") or {}) if refs.batch_code(b)]),
        },
        "founders": {
            "total_count": founders.get("_total"),
            "top_company_count": (founders.get("top_company") or {}).get("true"),
            "top_titles": dict(sorted((founders.get("yc_titles") or {}).items(), key=lambda kv: -kv[1])[:15]),
            "top_regions": dict(sorted((founders.get("current_region") or {}).items(), key=lambda kv: -kv[1])[:15]),
        },
    }
