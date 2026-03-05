---
name: Daily News Digest
description: Crawl hot/trendy news on a topic and produce a structured markdown digest
schedule: "0 8 * * *"
trigger: manual
inputs:
  topic:
    type: string
    required: true
    default: "AI agents"
---

# Daily News Digest

ViralLab crawls trending news and produces a structured digest.

## Steps

1. **Research** - Search for latest and hottest news on `{topic}` using news search tools
2. **Analyze** - Synthesize findings into a digest with: executive summary, key headlines, trends
3. **Output** - Save to `output/digest_{topic}.md`

## Shareable Component

Import in other repos:

```yaml
imports:
  - repo: your-org/ViralLab
    path: .github/agents/daily-news-digest.md
```

## Reference Implementation

The Python implementation lives in `src/news_crew.py` and `main.py`.
Uses CrewAI for orchestration and duckduckgo-search for news (no API key required).

## Cursor-Native (No API Keys)

In Cursor, ask: "Create a news digest for {topic}". The `.cursor/rules/daily-news-digest.mdc` rule instructs Cursor to:

1. Run `python main.py --search-only "{topic}"` → outputs `output/raw_{topic}.md`
2. Read the raw results and use Cursor's built-in AI to summarize
3. Save digest to `output/digest_{topic}.md`
