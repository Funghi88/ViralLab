# ViralLab

<p align="center">
  <img src="assets/thumbnail.png" alt="ViralLab — Engineer your influence" width="800">
</p>

**Engineer your influence. Turn noise into viral.**

ViralLab scores content using Jonah Berger's STEPPS framework — behavioral science, not guesswork. Design content that spreads.

**English and Chinese channels use different sources.** The English channel pulls from DuckDuckGo, YouTube, Hacker News, Reddit. The Chinese channel uses Bilibili, Douyin, Xiaohongshu, Weibo, Zhihu. Bilingual users can switch between channels to digest content from each ecosystem based on their preference.

**英文与中文频道使用不同来源。** 英文频道来自 DuckDuckGo、YouTube、Hacker News、Reddit；中文频道来自 B站、抖音、小红书、微博、知乎。双语用户可按偏好切换频道，获取不同生态的内容。

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
3. **Video to text** — Paste a YouTube URL. Get the transcript as markdown. See how viral the script is.
4. **One dashboard** — News, videos, transcripts. All in one place. Simple.

---

## How to use it

### Quick start (3 steps)

```bash
git clone https://github.com/Funghi88/ViralLab.git
cd ViralLab
./scripts/install.sh
python3 server.py
```

Open **http://127.0.0.1:5001** in your browser.

### Commands

| What you want | Command |
|---------------|---------|
| **Daily news** (top 3 today) | `python3 main.py --daily-news` |
| News on a topic | `python3 main.py --search-only "AI agents"` |
| Viral videos (ranked by spread rate) | `python3 main.py --videos "trending viral"` |
| Videos + full transcript (markdown) | `python3 main.py --videos "AI explainer" --transcript` |
| Single video → text | `python3 main.py --video-to-text <youtube_url>` |
| Web dashboard | `python3 server.py` |

### In the app

- **Daily News** — Top 3 most talked about or key focus topics. Each section has its own page.
- **Your field** — Choose your field (fashion, tech, food, beauty, content) for curated trends, color forecasting, and reliable resources.
- **Viral Videos** — Search by topic (YouTube or Bilibili). Berger score, content angles, trend lifecycle.
- **STEPPS & Magic Words** — Learn how we score. Jonah Berger's framework, explained.
- **Video to Text** — Paste URL → markdown transcript + Berger score.

---

## Why Berger?

We use Jonah Berger's research from *Contagious* and *Magic Words*. Not random. Not algorithmic engagement hacks. **Behavioral science** — what actually makes people share.

High score = content that taps into social currency, emotion, practical value, stories. The stuff that spreads.

---

## Install

```bash
./scripts/install.sh
```

Python 3.9+. No API keys for news/videos.

**China users:** DuckDuckGo and YouTube require VPN. Use our China sources (Bilibili, Douyin, Xiaohongshu, Shipinhao) for content without VPN. See [CHINA_ACCESS.md](CHINA_ACCESS.md).

---

## Deploy

See [DEPLOY.md](DEPLOY.md) for full instructions. **Recommended: Render** — free tier, one-click deploy via `render.yaml`.

Once live, your app URL (e.g. `https://virallab.onrender.com`) is the shareable link. No login required. Dates use each user's local timezone.

**Keep content fresh:** Set up a cron job (e.g. [cron-job.org](https://cron-job.org)) to hit `https://your-app.onrender.com/api/refresh-daily` daily. Optional: set `CRON_SECRET` in env and add `?key=your-secret` to the URL.

---

## For developers

- **China Access** — VPN requirements, China sources (Bilibili, Douyin, Xiaohongshu, Shipinhao). See [CHINA_ACCESS.md](CHINA_ACCESS.md).
- **API** — `GET /api/digests` (list), `GET /api/digests/<filename>`, `GET /api/export/<filename>?format=markdown|notion|obsidian`, `GET /api/viral-videos?q=<query>&source=global|china`, `POST /api/video-to-text`.
