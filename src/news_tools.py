"""News search for ViralLab. Uses duckduckgo-search (no API key)."""
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
from duckduckgo_search import DDGS


class NewsSearchInput(BaseModel):
    """Input for NewsSearchTool."""
    query: str = Field(..., description="Search query for news articles")
    max_results: int = Field(default=10, description="Max number of results to return")


class NewsSearchTool(BaseTool):
    name: str = "News Search"
    description: str = "Search for trending and latest news on any topic. Returns titles, snippets, and URLs."
    args_schema: Type[BaseModel] = NewsSearchInput

    def _run(self, query: str, max_results: int = 10) -> str:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=max_results))
            if not results:
                return f"No news found for: {query}"
            output = []
            for i, r in enumerate(results, 1):
                output.append(f"{i}. {r.get('title', 'N/A')}\n   {r.get('body', '')[:200]}...\n   URL: {r.get('url', '')}")
            return "\n\n".join(output)
        except Exception as e:
            return f"Search error: {str(e)}"
