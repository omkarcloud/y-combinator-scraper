"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same validation as the API, so a batch
can be `W24` or `Winter 2024` and a company a slug, an id or a link.
"""
import json
import os

from ycombinator import companies, jobs, schemas

os.makedirs("output", exist_ok=True)


def params(schema_cls, **values):
    """Validate params exactly like the API does (defaults filled in)."""
    data = schema_cls().load({k: str(v) for k, v in values.items()})
    data.pop("refresh", None)
    return data


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a slug, a numeric id or any ycombinator.com company link
    save("company_airbnb.json", companies.details(**params(schemas.CompanySchema, company="airbnb")))

    # 6,300+ companies by keyword, batch, industry, hiring, team size and more
    save("search_ai_w24.json", companies.search(**params(schemas.CompanySearchSchema, query="ai", batch="W24")))

    # Work at a Startup jobs by role and location, with salary and equity
    save("jobs_engineering_sf.json", jobs.search(**params(schemas.JobsSearchSchema, role="engineering",
                                                          location="san-francisco")))
