# yt-dlp cookies for Douyin (and other gated sites)

**ViralLab 默认推荐：** 先把抖音视频**保存到本盘**，在「影片转文字」粘贴 **本地文件路径** 做逐字稿；**本节只需在坚持「用抖音网页链接在线拉」时再读。**

If you see **`Fresh cookies are needed`** or **`Failed to parse JSON`** (empty body) on Douyin, `yt-dlp` needs **`douyin.com` cookies** — usually supplied as **Netscape-formatted `cookies.txt`**. **`config`** is only a folder name. You only touch **one file**: **`config/ytdlp_cookies.txt`**. Other files under **`config/`** (JSON, keywords, etc.) must stay as-is.

Making a separate “new project” elsewhere does **not** fix Douyin; the bottleneck is Douyin/web session + yt-dlp, not ViralLab’s folder layout.

---

## 零基础（可选）：坚持用抖音链接时再配置 —— `config/ytdlp_cookies.txt`

Goal: Chrome is logged in on **douyin.com** → export **Netscape** cookies → paste into **`config/ytdlp_cookies.txt`** → restart the dev server.

1. **Open Chrome**（桌面版 Chrome，不是手机）。
2. **Install one export extension**（任选其一即可）：
   - In Chrome, open **[Chrome Web Store](https://chromewebstore.google.com)**.
   - Search for **`Get cookies.txt LOCALLY`**（常见作者名 **kairii**）。
   - Click **「添加至 Chrome」** / **Add to Chrome** → allow.
3. **Pin the extension**（方便点后一步）：
   - Click Chrome’s puzzle-piece **「扩展程序」** icon → find the extension → **「固定」** / **Pin**。
4. **Log in on Douyin in the browser tab**：
   - Open **`https://www.douyin.com`**.
   - **Complete web login**（能看到推荐流 / 点开视频都算；**仅字节系 App 登录不算**，网页未登录则无有效 Cookie）。
5. **Stay on douyin.com**（地址栏里是 `douyin.com`）。
6. **Export cookies from the extension**：
   - Click the extension icon → choose **export / export all** → pick **Netscape** / **cookies.txt** if the extension asks format.
   - Chrome usually downloads **`cookies.txt`** or **`douyin_com_cookies.txt`** to **`Downloads`**。
7. **Open the downloaded file with TextEdit**（文本编辑）or Cursor：
   - You should see many lines whose first column looks like **`.douyin.com`** or **`www.douyin.com`**（域名）.
   - Each cookie line should use **`Tab`** between columns (**not** spaces). Netscape cookie lines have **7 tab-separated columns** (+ optional comment lines starting with **`#`** at the top).

8. **Replace only `config/ytdlp_cookies.txt` in ViralLab**：
   - In Cursor’s left sidebar open **`config/ytdlp_cookies.txt`**。
   - **Select all** placeholder text (the lines starting with `#`) → delete.
   - **Paste** the **entire** contents of the file you exported from Chrome (**from the first `# Netscape`** line down through every cookie row**`).
   - **Save** (**Cmd + S**). The filename stays **`ytdlp_cookies.txt`**; do **not** rename **`config`**。

9. **Restart the ViralLab server**（必填，服务端启动时读了环境后才跑 yt-dlp）：
   - In the terminal running **`./scripts/dev-server.sh`**, stop with **Ctrl+C**。
   - Start again：**`./scripts/dev-server.sh`**。

10. **Retry** 「影片转文字」 with your Douyin URL.

Still failing after steps 8–10? Your file may still be JSON from the wrong exporter, wrong site (exported from `localhost`, etc.), or Douyin closed the API (**empty JSON**). Then use **download or screen-record to a local `.mp4` / `.m4a`** and paste the **filesystem path** into ViralLab for transcript.

Security: **Never commit real `cookies.txt` to Git** — this repo’s **`config/ytdlp_cookies.txt`** is intended to stay **gitignored** or personal-only.

---

## Quick path (English)

1. On desktop **Chrome**, open **https://www.douyin.com** and finish **web** login (not app-only).
2. Use **Get cookies.txt LOCALLY** (or similar) → export **Netscape** cookies for **`douyin.com`**.
3. Paste the **whole** exported file contents into **`config/ytdlp_cookies.txt`** in this repo, **replacing** the placeholder comments (**one file only** — not overwriting the **`config/`** folder).
   - Or save as **`.local/ytdlp_cookies.txt`** inside the repo.
4. Restart **`./scripts/dev-server.sh`** (or `.venv/bin/python server.py`).
5. Retry **影片转文字** with the Douyin URL.

Alternatively set **`YTDLP_COOKIES_FILE=/absolute/path/to/cookies.txt`** in `.env`.

---

## Verify you did not keep a placeholder

If ViralLab’s error still says **`未发现带有效 Cookie 行的配置文件`** or NDJSON **`n_cookie_files_with_netscape_rows: 0`**, your **`ytdlp_cookies.txt`** still has **zero** seven-column tab rows (often because only **`#`** comment lines remained, or JSON was pasted).

---

## URL shape (Douyin)

- Feed links like **`https://www.douyin.com/jingxuan?modal_id=7627…`** share the numeric id with **`https://www.douyin.com/video/7627…`**. ViralLab rewrites the former before calling `yt-dlp`.
- If you still see **Unsupported URL**, use a share link with **`/video/<digits>`**.

## macOS Keychain prompts (`--cookies-from-browser`)

Repeated **“security wants to use … Chrome Safe Storage”** happens when **`--cookies-from-browser`** runs repeatedly.

**Prefer `config/ytdlp_cookies.txt`:** when that file has **real Netscape cookie rows**, ViralLab **skips `--cookies-from-browser` for Douyin URLs** by default.

**If you have not exported a file yet:** for Douyin only, ViralLab uses **one** `--cookies-from-browser` attempt (**`YTDLP_COOKIES_BROWSER`** / **`YTDLP_COOKIES_PROFILE`**). To restore older multi-browser probes: **`VIRALLAB_YTDLP_DOUYIN_WIDE_BROWSER=1`**.

- **`VIRALLAB_YTDLP_USE_BROWSER_COOKIES=1`**: add browser fallbacks even for Douyin when a file exists.
- **`VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES=1`**: never use **`--cookies-from-browser`**.

## Notes

- **App-only login does not populate** the cookies yt-dlp needs; use browser **douyin.com** session.
- **`--cookies-from-browser` on macOS** may fail when the browser denies DB access — the file export avoids that.
- Keep **`pip install -U yt-dlp`** reasonably current; Douyin can still return **HTTP 200 with empty JSON** (**anti-bot**). Workaround: **local media file** transcript path.
