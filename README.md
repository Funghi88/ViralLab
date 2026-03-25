# ViralLab

<p align="center">
  <img src="assets/thumbnail.png" alt="ViralLab — Engineer your influence" width="800">
</p>

**Engineer your influence. Turn noise into viral.**

**[Try it live →](https://virallab.onrender.com)**

ViralLab scores content using Jonah Berger's STEPPS framework — behavioral science, not guesswork. Design content that spreads.

ViralLab now includes professional, project-level skill workflows for:
- strict Berger STEPPS contagious evaluation
- strict Minto Pyramid structuring (conclusion-first, grouped logic, evidence mapping)
- multi-source crawling + SEO discovery for bilingual tag coverage

**English and Chinese channels use different sources.** The English channel pulls from DuckDuckGo, YouTube, Hacker News, Reddit. The Chinese channel uses Weibo, Zhihu, Douyin, Baidu, Bilibili, 少数派, IT之家, 36氪, 今日头条, 掘金, and PTT (Taiwan). Bilingual users can switch between channels to digest content from each ecosystem based on their preference.

**英文与中文频道使用不同来源。** 英文频道来自 DuckDuckGo、YouTube、Hacker News、Reddit；中文频道来自微博、知乎、抖音、百度、B站、少数派、IT之家、36氪、今日头条、掘金、PTT（台湾）。双语用户可按偏好切换频道，获取不同生态的内容。

---

## Who is this for?

**Content creators** — YouTubers, course builders, newsletter writers, social media managers. Anyone who wants to:

- Catch what's trending in their niche
- Know *why* content goes viral (science, not guesswork)
- Turn video into text for scripts, blogs, or repurposing
- Build their channel around topics that actually spread

If you create content and want to be ahead of the curve, ViralLab is for you.

---

## What does it do?

1. **Gather trends** — Search news and videos by topic. No API keys. DuckDuckGo (global) + Bilibili (China).
2. **Score with Berger** — Every piece gets a 0–100 score based on Jonah Berger's STEPPS (Social Currency, Triggers, Emotion, Public, Practical, Stories) and magic words. Science-backed.
3. **Video/audio to text** — Paste YouTube/Bilibili/Douyin/Xiaohongshu/Shipinhao/Xiaoyuzhou/podcast links (or local media path). Export transcript markdown and score the script.
4. **One dashboard** — News, videos, transcripts. All in one place. Simple.

---

## Professional Skill Sets Built In

To keep outputs consistent and production-ready, ViralLab ships with reusable project skills under `.cursor/skills/`:

1. **Minto Pyramid Structuring** (`minto-pyramid-structuring`)
   - Enforces single governing thought, grouped key points, and mapped evidence.
   - Supports strict structure for transcript-to-article workflows.

2. **Contagious Berger STEPPS** (`contagious-berger-stepps`)
   - Applies auditable STEPPS scoring and diagnosis for article/video/news cards.
   - Helps answer: "Which content attracts attention?" and "What should we borrow?"

3. **Multi-Source Crawling + SEO** (`multi-source-crawling-seo`, `technical-seo-discovery`)
   - Expands discovery workflows for news, podcasts, and videos.
   - Keeps EN/ZH ecosystems separated and generates hot-tag references for both.

These skills are designed to make the project viable for repeated, professional use across teams—not one-off prompting.

---

## How to use it

### Quick start (3 steps)

```bash
git clone https://github.com/Funghi88/ViralLab.git
cd ViralLab
./scripts/install.sh
source .venv/bin/activate
python server.py
```

Open **http://127.0.0.1:5001** in your browser.

### Commands

| What you want | Command |
|---------------|---------|
| **Daily news** (top 3 today) | `.venv/bin/python main.py --daily-news` |
| News on a topic | `.venv/bin/python main.py --search-only "AI agents"` |
| Viral videos (ranked by spread rate) | `.venv/bin/python main.py --videos "trending viral"` |
| Videos + full transcript (markdown) | `.venv/bin/python main.py --videos "AI explainer" --transcript` |
| Single media link/file → text | `.venv/bin/python main.py --video-to-text <url_or_media_path>` |
| Web dashboard | `.venv/bin/python server.py` |

### In the app

- **Daily News** — Top 3 most talked about or key focus topics. Each section has its own page.
- **Your field** — Choose your field (fashion, tech, food, beauty, content) for curated trends, color forecasting, and reliable resources.
- **Viral Videos** — Search by topic (YouTube or Bilibili). Berger score, content angles, trend lifecycle.
- **Long-form & Podcasts** — Dedicated page for deep articles + podcast signals, with EN/ZH hot-tag references.
- **STEPPS & Magic Words** — Learn how we score. Jonah Berger's framework, explained.
- **Video to Text** — Paste platform URL/audio link (or local media path) → markdown transcript + Berger score + Minto structure tab.

---

## Why Berger?

We use Jonah Berger's research from *Contagious* and *Magic Words*. Not random. Not algorithmic engagement hacks. **Behavioral science** — what actually makes people share.

High score = content that taps into social currency, emotion, practical value, stories. The stuff that spreads.

---

## Install

```bash
./scripts/install.sh
```

Python 3.12+. No API keys for news/videos.

**Transcript coverage (recommended):**

```bash
pip install videocaptioner
```

ViralLab uses YouTube captions first when available. For Bilibili, Douyin, Xiaohongshu, Shipinhao, Xiaoyuzhou, and broader podcast/audio links, VideoCaptioner enables ASR fallback transcript generation.

**China users:** DuckDuckGo and YouTube require VPN. Use our China sources (Bilibili, Douyin, Xiaohongshu, Shipinhao) for content without VPN. See [CHINA_ACCESS.md](CHINA_ACCESS.md).

**Platform note:** Some sources (e.g. TikTok/Douyin/Xiaohongshu/Shipinhao) are constrained by platform policies. ViralLab supports a hybrid approach: official search links + optional crawler outputs where feasible.

**China crawler (optional):** To add content from Xiaohongshu, Douyin, Zhihu, and Shipinhao to the China viral feed: use the **Fetch** card on the Viral page (source = China), or run the CLI:

```bash
pip install playwright
playwright install chromium
.venv/bin/python -m tools.china_crawler run --platform xhs --keywords "关键词"
# Or: bilibili, douyin, shipinhao, zhihu
```

Results are written to `output/china_crawler_<platform>.json`. The app merges them into the China list and shows content type (video, post, article, note). Many platforms may require login for full results. See [docs/CHINA_SOURCES_ROADMAP.md](docs/CHINA_SOURCES_ROADMAP.md).

---

## Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Funghi88/ViralLab)

1. Click the button above (or go to [render.com](https://render.com) → New → Web Service).
2. Connect your GitHub and select the ViralLab repo. Render detects `render.yaml`.
3. Add env vars if needed: `OPENAI_API_KEY` or `GEMINI_API_KEY` for AI features.
4. Deploy. Live at [virallab.onrender.com](https://virallab.onrender.com).

**Keep content fresh:** [cron-job.org](https://cron-job.org) → Create job → URL: `https://virallab.onrender.com/api/refresh-daily?key=YOUR_CRON_SECRET` → Daily at 8:00.

See [DEPLOY.md](DEPLOY.md) for full instructions.

---

## For developers

- **China Access** — VPN requirements, China sources (Bilibili, Douyin, Xiaohongshu, Shipinhao). See [CHINA_ACCESS.md](CHINA_ACCESS.md).
- **API** — `GET /api/digests` (list), `GET /api/digests/<filename>`, `GET /api/export/<filename>?format=markdown|notion|obsidian`, `GET /api/viral-videos?q=<query>&source=global|china`, `POST /api/video-to-text`.
- **China crawler** — `tools/china_crawler`: optional Playwright-based XHS search; output merges into China viral when present. [docs/CHINA_SOURCES_ROADMAP.md](docs/CHINA_SOURCES_ROADMAP.md).
- **Project skills** — Professional reusable workflows live in `.cursor/skills/`:
  - `minto-pyramid-structuring`
  - `contagious-berger-stepps`
  - `multi-source-crawling-seo`
  - `technical-seo-discovery`
