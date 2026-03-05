# ViralLab Setup — API Keys & News Sources

ViralLab uses creator-focused news sources. Some work out of the box; others need API keys.

## Out of the Box (No Setup)

| Source | What it does |
|--------|--------------|
| **Hacker News** | Top stories from HN front page |
| **TechCrunch** | Latest tech news via RSS |
| **The Verge** | Tech & culture via RSS |
| **Tubefilter** | YouTube/creator industry news |
| **Ars Technica** | Tech news |
| **Wired** | Tech & culture |
| **Indie Hackers** | Creator/startup stories via RSS |
| **Buffer** | Social media blog via RSS |
| **Social Media Examiner** | Marketing/creators via RSS |
| **Later** | Social media blog via RSS |
| **Fast Company** | Business/innovation via RSS |
| **VentureBeat** | Tech news via RSS |
| **Engadget** | Tech/gadgets via RSS |
| **Mashable** | Tech & culture via RSS |
| **Digital Trends** | Tech news via RSS |
| **MIT Technology Review** | Tech & AI via RSS |
| **CNET** | Tech news via RSS |
| **Gizmodo** | Tech/gadgets via RSS |
| **Adweek** | Advertising/media/creators via RSS |
| **Variety** | Entertainment industry via RSS |
| **GeekWire** | Tech & startups via RSS |
| **TechRadar** | Tech news & reviews via RSS |
| **ZDNet** | Business technology via RSS |
| **TechRepublic** | Enterprise tech via RSS |
| **Hootsuite** | Social media marketing via RSS |
| **Digiday** | Media & marketing industry via RSS |
| **Axios** | Tech & business news via RSS |
| **DuckDuckGo News** | Trending news (supplements other sources) |
| **Google News RSS** | Topic search via RSS (no key) |

**中文區 RSS:** TechNode, 36氪, 爱范儿, PingWest, 虎嗅, 36氪文章, 钛媒体, 少数派, 雷锋网, 知乎日报, InfoQ, 极客公园, 机核, 机器之心, 量子位, 快科技

## News by Topic (按主題新聞) — Sources

When users search a topic, we query multiple sources:

| Source | API Key | Notes |
|--------|--------|-------|
| Google News RSS | None | Topic search, EN/zh auto |
| DuckDuckGo News | None | Topic search |
| Serper (Google News) | `SERPER_API_KEY` | Optional, 2,500 free/month |
| Hacker News | None | English topics only |
| NewsAPI | `NEWSAPI_KEY` | Topic search |

Add `SERPER_API_KEY` for richer results. Add `NEWSAPI_KEY` for more publisher coverage.

---

## Adding More Sources (For Maintainers)

To diversify news and better serve content creators, edit `src/news_sources.py`:

### 1. Add RSS feeds (no API key)

Append to `RSS_FEEDS_EN` (English) or `RSS_FEEDS_ZH` (Chinese):

```python
RSS_FEEDS_EN = [
    ("https://techcrunch.com/feed/", "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml", "The Verge"),
    ("https://tubefilter.com/feed/", "Tubefilter"),
    ("https://your-new-feed.com/feed.xml", "Your Source Name"),  # Add here
]
```

Then add the source name to the `sources_used` loop in `fetch_all_sources()` (around line 270).

### 2. Add API-based sources

Create a new `fetch_xyz()` function following the pattern of `fetch_newsapi()` or `fetch_youtube_trending()`. Each fetcher returns `list[dict]` with keys: `title`, `snippet`, `url`, `date`, `source`. Call it from `fetch_all_sources()` and append to `all_items` and `sources_used`.

### 3. Creator-focused sources to consider

| Source | Type | Notes |
|--------|------|-------|
| Tubefilter | RSS | YouTube/creator industry |
| Social Media Examiner | RSS | Marketing/creators |
| Later blog | RSS | Social media |
| Buffer blog | RSS | Social media |
| Indie Hackers | RSS | Creators/startups |
| NewsAPI | API | Add `NEWSAPI_KEY` to `.env` |
| YouTube Trending | API | Add `YOUTUBE_API_KEY` to `.env` |
| Product Hunt | API | Add `PRODUCT_HUNT_TOKEN` to `.env` |

---

## Optional: Add API Keys for More Sources

Create a `.env` file in the project root. Add the keys you want:

```bash
# YouTube Trending (creator-focused)
YOUTUBE_API_KEY=your_key_here

# Product Hunt (new products & launches)
PRODUCT_HUNT_TOKEN=your_token_here

# NewsAPI (headlines from many publishers)
NEWSAPI_KEY=your_key_here

# Serper (Google News search, 2,500 free/month) — richer topic search
SERPER_API_KEY=your_key_here
```

---

## Step-by-Step: YouTube API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select one)
3. Enable **YouTube Data API v3**:
   - APIs & Services → Library → search "YouTube Data API v3" → Enable
4. Create credentials:
   - APIs & Services → Credentials → Create Credentials → API Key
5. Copy the key and add to `.env`:
   ```
   YOUTUBE_API_KEY=AIza...
   ```
6. (Optional) Restrict the key to YouTube Data API v3 for security

**Free quota:** 10,000 units/day. Trending fetch uses ~1 unit per run.

---

## Step-by-Step: Product Hunt Token

1. Go to [Product Hunt API](https://api.producthunt.com/v2/docs)
2. Sign in with your Product Hunt account
3. Create an app:
   - Click "Create new application"
   - Name it (e.g. "ViralLab")
   - Copy the **Developer Token**
4. Add to `.env`:
   ```
   PRODUCT_HUNT_TOKEN=your_token_here
   ```

**Free tier:** 6,250 complexity points per 15 minutes. Read-only, public scope.

---

## Step-by-Step: NewsAPI Key

1. Go to [NewsAPI.org](https://newsapi.org/)
2. Click "Get API Key" and sign up
3. Copy your API key from the dashboard
4. Add to `.env`:
   ```
   NEWSAPI_KEY=your_key_here
   ```

**Free tier:** 100 requests/day. Enough for daily news refresh.

---

## Load Environment Variables

ViralLab uses `python-dotenv`. If you create `.env` in the project root, it will load automatically when you run:

```bash
python main.py --daily-news
```

Or when the Flask server runs (ensure `load_dotenv()` is called at startup).

---

## What Creators See

On the Daily News page, a small label shows which sources contributed:

> **Sources:** Hacker News, TechCrunch, The Verge, Tubefilter — curated for content creators.
