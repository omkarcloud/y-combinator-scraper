# 🚀 Y Combinator Scraper

Y Combinator Scraper is a **free and open-source** scraper that gets you **unlimited** Y Combinator startup, founder and job data for free.

## ✨ What Can I Get?

- 🏢 **Full profiles of 6,300+ YC companies** — founders, batch, team size, socials, news, launches & open jobs
- 🔍 **Search the whole YC directory** — batch, industry, tag, region, status, hiring, team size & launch date
- 👩‍💼 **13,900+ YC founders** — bios, titles, LinkedIn, Twitter, past companies & co-founders
- 💼 **Jobs, launches & more** — Work at a Startup jobs with salary & equity, 3,300+ Launch YC posts, partners, blog & library

## 🎥 Example: A Full Y Combinator Company

```json
{
  "id": 271,
  "slug": "airbnb",
  "name": "Airbnb",
  "link": "https://www.ycombinator.com/companies/airbnb",
  "website": "http://airbnb.com",
  "one_liner": "Book accommodations around the world.",
  "batch": { "code": "W09", "name": "Winter 2009" },
  "status": "public",
  "team_size": 6132,
  "year_founded": 2008,
  "location": { "city": "San Francisco", "country": "US", "regions": ["United States of America", "America / Canada"] },
  "social": {
    "linkedin": "https://www.linkedin.com/company/airbnb/",
    "twitter": "https://twitter.com/Airbnb",
    "crunchbase": "https://www.crunchbase.com/organization/airbnb"
  },
  "group_partner": { "name": "Garry Tan", "link": "https://www.ycombinator.com/people/garry-tan" },
  "founders": [
    {
      "id": 21981,
      "name": "Brian Chesky",
      "title": "Founder/CEO",
      "bio": "Brian Chesky is the co-founder, Head of Community, and CEO of Airbnb, which he started with Joe Gebbia and Nathan Blecharczyk in 2008…",
      "social": { "linkedin": "https://www.linkedin.com/in/brianchesky/", "twitter": "https://twitter.com/bchesky" },
      "past_companies": "Industrial Designer at 3DID, Principal at Brian Chesky"
    }
  ],
  "news": [
    { "title": "Airbnb launches Airbnb Rooms listing category for budget travel", "link": "https://www.usatoday.com/story/travel/news/2023/05/03/airbnb-rooms-listing-category-budget-travel/70178696007/", "date": "2023-05-03" }
  ],
  "industries": ["Consumer", "Travel, Leisure and Tourism"],
  "stage": "Growth",
  "is_top_company": true
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Y Combinator Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/y-combinator-scraper
cd y-combinator-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/companies/details?company=airbnb"
```

```json
{
  "company": {
    "id": 271,
    "slug": "airbnb",
    "name": "Airbnb",
    "link": "https://www.ycombinator.com/companies/airbnb",
    "website": "http://airbnb.com",
    "one_liner": "Book accommodations around the world.",
    "batch": { "code": "W09", "name": "Winter 2009" },
    "status": "public",
    "team_size": 6132,
    "year_founded": 2008,
    "founders": [
      { "name": "Brian Chesky", "title": "Founder/CEO", "social": { "linkedin": "https://www.linkedin.com/in/brianchesky/" } },
      { "name": "Nathan Blecharczyk", "title": "Founder/CTO", "social": { "linkedin": "https://www.linkedin.com/in/blecharczyk/" } }
    ],
    "is_top_company": true
  }
}
```

All 25 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

25 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Company Details | `/companies/details` | One company in full: founders, socials, news, launches, jobs |
| Search Companies | `/companies/search` | 6,300+ startups by batch, industry, region, hiring and more |
| Top Companies | `/companies/top` | Every company with YC's Top Company badge |
| New Companies | `/companies/new` | The newest YC startups, latest launch first |
| Browse Companies | `/companies/browse` | YC's curated industry and location lists, 50 per page |
| Highlighted Companies | `/companies/highlights` | Companies founded by women, Black or Hispanic & Latino founders |
| Company Directory | `/companies/directory` | The whole directory page by page, for bulk downloads |
| Company Founders | `/companies/founders` | Every founder with bio, LinkedIn, Twitter and past companies |
| Company Jobs | `/companies/jobs` | Every open role with salary, equity and apply link |
| Company Launches | `/companies/launches` | A company's Launch YC posts with the full story |
| Search Founders | `/founders/search` | 13,900+ founders by name, batch, title and region |
| Founder Details | `/founders/details` | A founder's bio, socials, batches, co-founders and company |
| Search Jobs | `/jobs/search` | Startup jobs by role, location, salary, equity and visa |
| Job Details | `/jobs/details` | A full posting: description, interview process, hiring manager |
| Search Launches | `/launches/search` | 3,300+ Launch YC posts, newest first, by keyword and batch |
| Launch Details | `/launches/details` | One launch: the founder's story, votes and author |
| YC Partners | `/partners/list` | The people who run YC, grouped by team |
| Partner Details | `/partners/details` | A partner's bio, companies, press, tweets and videos |
| Blog Posts | `/blog/posts` | YC blog posts, newest first, by author or tag |
| Blog Post Details | `/blog/details` | A full blog post as HTML and text |
| Search Library | `/library/search` | YC Startup Library videos and essays, sortable by views |
| Library Article | `/library/details` | One video or essay with chapters and full transcript |
| Filters | `/filters` | Every filter value with counts |
| Batches | `/batches` | Every batch with counts, plus the application deadline |
| Directory Stats | `/stats` | Directory totals by status, industry, tag and region |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-y-combinator-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-y-combinator-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-y-combinator-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/companies/search",
    params={"query": "ai", "batch": "W24", "is_hiring": "true"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Y Combinator Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/y-combinator-scraper-github-whatsapp)

[![Ask Us by Email about Y Combinator Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Y%20Combinator%20Scraper%20API&body=I%20need%20help%20using%20the%20Y%20Combinator%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/y-combinator-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/y-combinator-scraper)
