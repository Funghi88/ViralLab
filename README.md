# ViralLab

**Engineer your influence. Turn noise into viral.**

**[Try it live →](https://virallab.onrender.com)**

ViralLab is an end-to-end bilingual (EN / ZH) intelligence, rewriting, and publishing workbench for content creators. It gathers global news, deep long-form essays, podcasts, and viral videos, scores them with **Jonah Berger's STEPPS** behavioral science framework, structures arguments using the **Minto Pyramid Principle**, and publishes directly to your blog and social channels.

---

## Core Workflow: Spot → Rewrite → Publish

1. **Daily News & AI Authority (`/daily`)** — Global news digest (EN & ZH kept strictly separated) plus a founder-grade **AI Authority Brief** auto-tagged into 4 strategic layers (`Research`, `Industry`, `Investment`, `Strategy & Society`).
   * **Global EN sources (40+ verified feeds):** BBC World & Tech, NPR World & Tech, The Guardian, Al Jazeera, Deutsche Welle (DW), France 24, CNA Singapore, South China Morning Post, The Japan Times, ABC News Australia, Financial Times, Semafor, New York Times Tech, CNBC, TechCrunch, The Verge, Wired, Ars Technica, MIT Technology Review, Axios, Rest of World, OpenAI Blog, Google AI & DeepMind Blogs, Hugging Face, BAIR, Simon Willison, Hacker News, and Google News.
   * **Chinese ZH sources (17+ verified feeds):** 量子位, IT之家, 爱范儿, 少数派, Solidot, 开源中国, 人人都是产品经理, 创业邦, 德国之声中文, 法广中文 RFI, plus targeted signals from 机器之心, DeepTech, 甲子光年, 阿里研究院, and 新智元.
2. **News by Topic (`/news`)** — Search any topic in English or Chinese with live auto-refreshing background search, platform hot-topic discovery (HN, Lobste.rs, Dev.to, GitHub, Bilibili, Weibo/Zhihu/Douyin/Baidu/PTT), and field-heat breakdowns.
3. **Long-form & Podcasts (`/longform`)** — Curated essays and top podcasts (The Atlantic, The New Yorker, The Economist, Stratechery, Pragmatic Engineer, Hard Fork, Acquired, Lenny's Podcast, FT中文网, 纽约时报中文网, 報導者, 端傳媒, 阮一峰的网络日志, UX Coffee, etc.).
4. **Viral Videos & Social Discovery (`/viral`, `/china-content`)** — Instant cached trending videos for **Global (YouTube)** and **China (Bilibili + optional Playwright crawlers for Xiaohongshu, Douyin, Zhihu, Shipinhao, TikTok, X, Instagram)** with Berger STEPPS scores and 3 content angles per item.
5. **Video / Audio to Text + Image OCR (`/video-to-text`)** — Paste a YouTube/Bilibili/Douyin/XHS/podcast URL or local media path to extract transcripts (YouTube captions → `yt-dlp` → VideoCaptioner / optional WhisperX) with STEPPS + Minto analysis. Also supports YouTube video/audio downloads and offline Chinese/Latin **Image OCR** via RapidOCR + ONNX.
6. **1-Click Rewrite (`/article-lab`)** — Every card on `/daily`, `/news`, and `/longform` has **✍️ Rewrite** and **🚀 Publish** buttons. Rewrite transcripts or articles into conclusion-first **Minto Pyramid** drafts with full **STEPPS** diagnosis (works rule-based with no API keys, or enhanced via OpenAI / Anthropic / Gemini).
7. **5-Channel Publish Hub & Scheduler (`/publish`)** — Queue, schedule (auto-dispatched every minute by APScheduler), format, and publish directly to:
   * **Personal Blog (GitHub Pages / Jekyll)** — Native Jekyll frontmatter (`layout: post`, `title`, `date`, `category`, `excerpt`) committed directly to `_posts/` or `_drafts/` via GitHub API (preconfigured for `Funghi88/funghi88.github.io`), or 1-click Copy Jekyll `.md`.
   * **Telegram** — Direct Bot API HTML publishing with automatic chunking for long posts.
   * **WeChat 公众号** — Direct Draft Box API (`draft/add`) + 1-click **Copy WeChat Rich HTML** (inline-styled HTML that pastes cleanly into `mp.weixin.qq.com` with zero keys required).
   * **Xiaohongshu 小红书** — Native mobile formatter (≤20-char hook title, emoji paragraphs, `#tags`) + 1-click Copy & Open Creator Studio + optional webhook.
   * **X (Twitter)** — Direct X API v2 OAuth 1.0a publishing (with automatic numbered multi-tweet threads) + webhook fallback + 1-click Copy Thread & Open X Composer.

---

## Quick Start (macOS / Linux)

Requires **Python 3.12** (recommended) and `ffmpeg` (for audio/video processing).

```bash
git clone https://github.com/Funghi88/ViralLab.git
cd ViralLab
./scripts/install.sh
./scripts/dev-server.sh
```

Open **[http://127.0.0.1:5001](http://127.0.0.1:5001)** in your browser.

### Useful Commands

| Task | Command |
| :--- | :--- |
| Start local dashboard (auto-reload) | `./scripts/dev-server.sh` |
| Refresh all feeds (hot list, daily, longform, videos, topics) | `.venv/bin/python scripts/refresh_all_content.py` |
| Daily news + AI Authority only | `.venv/bin/python main.py --daily-news` |
| Search news on a topic | `.venv/bin/python main.py --search-only "AI agents"` |
| Viral videos (+ optional `--transcript`) | `.venv/bin/python main.py --videos "AI explainer" --transcript` |
| Single media URL or local file → transcript | `.venv/bin/python main.py --video-to-text <url_or_path>` |
| Upgrade `yt-dlp` in `.venv` | `./scripts/upgrade-ytdlp.sh` |
| Run full test suite | `.venv/bin/python -m unittest discover -s tests` |

---

## Network & macOS VPN Support

ViralLab's [src/proxy_env.py](src/proxy_env.py) handles macOS VPN environments automatically — no hardcoded proxy ports required:

* **TUN VPN mode (e.g., QuickQ TUN):** Detected cleanly as direct/TUN routing with zero dead-port stalls.
* **Floating SOCKS5 / HTTP proxies:** Dynamically inspects macOS `scutil --proxy` (with native `PySocks` / `socksio` support) and fast-probes ports before use, adapting automatically whenever your VPN reconnects and changes ports.
* **Domestic vs Overseas routing:** China-domestic endpoints (Douyin, XHS short links, WeChat API) bypass overseas proxies automatically.
* Check live proxy status anytime at `GET /api/health`.

---

## Configuration (`.env`)

Copy `.env.example` to `.env`. News, long-form, viral videos, OCR, and platform formatters work **without any API keys**. Add keys only for the optional features you want:

### AI-Enhanced Scoring & Rewrites (Optional)
Multi-provider client ([src/llm_client.py](src/llm_client.py)) tries configured keys in order with automatic fallback:
```bash
OPENAI_API_KEY=sk-...             # Default model: gpt-4.1-mini (override: VIRALLAB_OPENAI_MODEL)
ANTHROPIC_API_KEY=sk-ant-...      # Default model: claude-haiku-4-5 (override: VIRALLAB_ANTHROPIC_MODEL)
GEMINI_API_KEY=...                # Default model: gemini-2.5-flash (override: VIRALLAB_GEMINI_MODEL)
```

### 5-Channel Live Publishing (Optional)
```bash
# Personal Blog (GitHub Pages / Jekyll)
GITHUB_TOKEN=ghp_...
GITHUB_BLOG_REPO=Funghi88/funghi88.github.io
GITHUB_BLOG_BRANCH=main
GITHUB_BLOG_CATEGORY=Writing

# Telegram Channel / Chat
TELEGRAM_BOT_TOKEN=123456789:AA...
TELEGRAM_CHAT_ID=@your_channel

# WeChat Official Account Draft Box (or use 1-click Copy WeChat Rich HTML with no keys)
WECHAT_APP_ID=wx...
WECHAT_APP_SECRET=...
WECHAT_THUMB_MEDIA_ID=...

# X (Twitter) — Direct API v2 (OAuth 1.0a) OR Webhook (n8n / Make / Zapier)
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
# X_PUBLISH_WEBHOOK=https://...

# Xiaohongshu (or use 1-click Copy XHS Format with no keys)
# XHS_PUBLISH_WEBHOOK=https://...
```

### Optional Media & Crawlers
* **Douyin → Transcript:** Pasting a local downloaded video/audio path is most reliable. For URLs, see `config/README-ytdlp-cookies.md`.
* **Higher-Quality Local ASR (WhisperX):** `pip install -r requirements-asr.txt` (automatically uses CPU `int8` on Apple Silicon to avoid `ctranslate2` MPS issues).
* **Playwright Crawlers (XHS / Douyin / Zhihu / Shipinhao / X / Instagram):**
  ```bash
  .venv/bin/python -m playwright install chromium
  .venv/bin/python -m tools.china_crawler login --platform xhs
  .venv/bin/python -m tools.china_crawler run --platform xhs --keywords "AI"
  ```
* **Automatic Storage Cleanup:** `src/output_cleanup.py` automatically prunes stale `raw_*`, `videos_*`, `transcript_*`, `article_rewrite_*`, `youtube_*`, `viral_cache_*`, and `handoff_*` artifacts older than `OUTPUT_RETENTION_DAYS` (default: 3 days) and deletes intermediate `yt-dlp` fragments after merging.

---

## API Endpoints

* `GET /api/health` — Server health & active proxy mode (`direct`, `scutil_socks`, `scutil_http`, `env`)
* `GET /api/digests` · `GET /api/digests/<filename>` · `GET /api/export/<filename>?format=markdown|notion|obsidian`
* `GET /api/refresh-daily` · `GET /api/refresh-ai-authority` · `GET /api/refresh-videos` *(supports `?key=CRON_SECRET`)*
* `POST /api/search-news` · `GET /api/search-news-status?stem=<stem>`
* `GET /api/viral-videos?q=<query>&source=global|china` *(15-min cache; `&refresh=1` to bypass)*
* `POST /api/video-to-text` · `POST /api/youtube-formats` · `POST /api/youtube-download` · `POST /api/image-ocr`
* `POST /api/china-crawl` · `POST /api/china-content-evaluate` · `POST /api/china-content-rewrite`
* `POST /api/handoff` · `POST /api/publish/format`

---

## Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Funghi88/ViralLab)

1. Connect your GitHub repo on [render.com](https://render.com) — Render auto-detects `render.yaml`.
2. Add any optional API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `GITHUB_TOKEN`, `TELEGRAM_BOT_TOKEN`, `CRON_SECRET`).
3. Optional cron keep-fresh: schedule `GET https://<your-app>/api/refresh-daily?key=YOUR_CRON_SECRET`.

See [DEPLOY.md](DEPLOY.md) and [CHINA_ACCESS.md](CHINA_ACCESS.md) for details.
