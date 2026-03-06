# Deployment Options

Where to host ViralLab when you're ready to go online.

---

## Go Live Checklist

1. **Create GitHub repo** — New repo at github.com, name it `ViralLab` (or your choice).
2. **Push code** — `git init && git add . && git commit -m "Initial commit" && git remote add origin https://github.com/Funghi88/ViralLab.git && git push -u origin main`
3. **Deploy on Render** — [render.com](https://render.com) → New → Web Service → Connect your repo. Render auto-detects `render.yaml`. Add env vars (`CRON_SECRET`, `OPENAI_API_KEY` or `GEMINI_API_KEY` if needed). Deploy.
4. **Set up cron** — [cron-job.org](https://cron-job.org) → Create jobs: `refresh-daily` (daily at 8:00), `refresh-videos` (every 6 hours). Both use `?key=YOUR_CRON_SECRET`.
5. **Share** — Your live URL (e.g. `https://virallab.onrender.com`) is the shareable link.

**Note:** `docs/` is in `.gitignore` — internal docs stay private. The rest is open source.

---

## Production viability: what happens on reconnect/restart

| Scenario | What happens |
|----------|--------------|
| **User refreshes the page** | Content loads from disk. If files exist, it works immediately. |
| **Server restarts** (deploy, dyno sleep/wake, crash) | The `output/` folder is **ephemeral** on Railway, Render, Heroku — it gets wiped. Content is empty until our **bootstrap** (runs on startup when empty) finishes fetching (~1–2 min). Users visiting during that window see empty news/videos. |
| **After bootstrap completes** | Content loads normally. Scheduler refreshes every 60 mins. |

**To make it production-ready for public use:**

1. **Keep the dyno always on** (paid tier) — avoids sleep/wake, so restarts only happen on deploy. Bootstrap still runs on deploy (~1–2 min empty window).
2. **Persistent storage** (future) — Store digests in a database (PostgreSQL) or object storage (S3) instead of local files. Survives restarts; no empty window.
3. **External cron** — Hit `/api/refresh-daily` and `/news/refresh` via cron-job.org or platform cron. Helps keep content fresh; does not fix the ephemeral-filesystem issue on restart.

---

## Recommended (Free Tier)

| Platform | Best for | Notes |
|----------|----------|-------|
| [Railway](https://railway.app) | Easiest | Connect GitHub, auto-deploy. Free $5/mo credit. |
| [Render](https://render.com) | Simple | Free tier for web services. Add `render.yaml` for one-click. |
| [Fly.io](https://fly.io) | Global edge | Free tier, good for low traffic. |
| [PythonAnywhere](https://pythonanywhere.com) | Python-only | Free tier, no Docker needed. |

---

## Render (Recommended — Free Tier)

**Why Render:** Zero config (`render.yaml` ready), truly free (no credit card), ~5–10 concurrent users, 750 instance hours/month. Sleeps after 15 min idle (~1 min cold start).

### Deploy Steps

1. Push ViralLab to a GitHub repo.
2. Go to [render.com](https://render.com) → New → Web Service.
3. Connect the repo; Render detects `render.yaml`.
4. Add env vars in Render Dashboard → Environment:
   - `PORT` — auto-set by Render
   - `CRON_SECRET` — optional; protects refresh endpoints (generate a random string)
   - `OPENAI_API_KEY` or `GEMINI_API_KEY` — if using AI features (video-to-text, content angles)
5. Deploy. URL: `https://virallab.onrender.com` (or your service name).
6. **Cron for fresh content**: [cron-job.org](https://cron-job.org) → Create jobs:
   - `refresh-daily`: `https://your-app.onrender.com/api/refresh-daily?key=YOUR_CRON_SECRET` — daily at 8:00
   - `refresh-videos`: `https://your-app.onrender.com/api/refresh-videos?key=YOUR_CRON_SECRET` — every 6 hours (optional; scheduler also refreshes every 60 mins when server is running)

### Optional: Reduce Cold Start

[UptimeRobot](https://uptimerobot.com) (free) can ping `https://your-app.onrender.com/api/health` every 10–14 min to keep the service awake. Uses more of your 750 instance hours.

---

## Setup (Railway / Render)

1. Add `Procfile`:
   ```
   web: python server.py
   ```

2. Set env: `PORT` is provided by platform.

3. **Keep daily news fresh**: Hit `GET /api/refresh-daily` daily (e.g. 8am). Use cron-job.org, GitHub Actions, or platform cron. Optional: set `CRON_SECRET` env and add `?key=your-secret` to the URL.

---

## Static Output Option

If you only need to share output files (no live search):

- Push `output/*.md` to GitHub
- Use [GitHub Pages](https://pages.github.com) + a simple index.html that links to the files
- Or [Netlify](https://netlify.com) / [Vercel](https://vercel.com) for static hosting

---

## China Access

| Source | VPN required? |
|--------|----------------|
| DuckDuckGo, YouTube | **Yes** — blocked in mainland China |
| Bilibili, Douyin, Xiaohongshu, Shipinhao | **No** — China-native sources |

- **In China:** Use China sources in the app. VPN required only for global content (DuckDuckGo, YouTube).
- **Hosting:** Railway, Render, Fly.io run outside China. For China hosting, consider Alibaba Cloud, Tencent Cloud. See [CHINA_ACCESS.md](CHINA_ACCESS.md).
