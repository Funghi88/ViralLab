---
name: multi-source-crawling-seo
description: Implements professional multi-source crawling and SEO discovery workflows across news, podcasts, and videos. Use when expanding source coverage, adding hard-to-crawl platforms, building hot-tag references, or improving bilingual EN/ZH discovery quality.
---
# Multi-Source Crawling + SEO

## Goal
Keep discovery quality high across:
- News
- Podcasts
- Videos

while staying practical on platform constraints.

## Scope Rules
1. Prefer official APIs/RSS where available.
2. For restricted platforms, use official search links and optional low-frequency crawlers.
3. Separate EN and ZH ecosystems (do not merge blindly).
4. Always produce hot-tag references for both EN and ZH.

## Workflow
Task Progress:
- [ ] Inventory current sources by format (news/podcast/video)
- [ ] Identify coverage gaps (platform + language)
- [ ] Add source connectors (API, RSS, or official search links)
- [ ] Update frontend tag references (EN/ZH)
- [ ] Verify dedupe, latency, and failure fallback

## Platform Handling
- **Easy**: RSS/API sources -> direct ingest
- **Medium**: Open web pages -> parser + fallback
- **Hard**: TikTok/Douyin/XHS/Shipinhao-like targets -> official search + optional crawler outputs

## SEO Discovery Rules
- Build tag references from:
  - platform hot topics
  - internal search demand
  - source-title frequency
- Keep EN/ZH tag sets separate
- Expose tags in UI as clickable chips

## Output Contract
When reporting changes, include:
- Added/updated sources
- What is crawlable now vs link-only
- EN/ZH hot tags now shown in UI
- Remaining blockers and legal/ToS cautions
