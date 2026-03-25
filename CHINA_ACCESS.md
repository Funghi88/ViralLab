# China Access Guide

ViralLab supports both **global** and **China-native** sources.

---

## VPN Required (Global Sources)

If you are in mainland China, you need a **VPN** to use:

- **DuckDuckGo** — news and video search
- **YouTube** — video search, transcripts, video-to-text

Without VPN, these will fail with connection errors.

---

## China Sources (No VPN Needed)

When in China, use our China-native sources:


| Platform            | Use                        | Notes                      |
| ------------------- | -------------------------- | -------------------------- |
| **抖音 Douyin**       | Short-form video           | China's TikTok             |
| **小红书 Xiaohongshu** | Lifestyle, beauty, fashion | Search by keyword          |
| **视频号 Shipinhao**   | WeChat Channels            | Short video in WeChat      |
| **哔哩哔哩 Bilibili**   | Long-form video            | Search via API in ViralLab |


### In the app

- **Daily News / Videos**: Use the **Source** selector to switch between **Global** (DuckDuckGo, YouTube) and **China** (Bilibili).
- **Bilibili** search works directly in ViralLab. For Douyin, Xiaohongshu, and Shipinhao, use the quick links to search on each platform.

### 免费且合规 (Free & compliant)

若希望**不付费、不爬取、不登录**，仅用免费且合法合规的方式：使用 B站 公开 API（在「热门视频」选中国来源）+ 各平台官方搜索链接（在中国内容页「免费且合规」区域点击，在浏览器中搜索）。详见 **[docs/CHINA_FREE_COMPLIANT.md](docs/CHINA_FREE_COMPLIANT.md)**。

---

## Summary


| Your location | DuckDuckGo / YouTube | Bilibili / China sources |
| ------------- | -------------------- | ------------------------ |
| Outside China | ✅ Works              | ✅ Works                  |
| In China      | ❌ VPN required       | ✅ Works (no VPN)         |

---

## Building our own China flow

We’re **building our own** China content pipeline — simple setup, clear UX, no dependency on third‑party crawler projects. Today: **Bilibili** (API) + **hot lists** (微博, 知乎, 抖音, etc. via existing APIs). Next: our own, user‑first sources. See [docs/CHINA_SOURCES_ROADMAP.md](docs/CHINA_SOURCES_ROADMAP.md).


