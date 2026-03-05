"""CrewAI news crew for ViralLab - crawls hot/trending news and produces structured output."""
import os
import urllib.request

from crewai import Agent, Crew, LLM, Process, Task
from crewai_tools import ScrapeWebsiteTool
from news_tools import NewsSearchTool

news_search = NewsSearchTool()
scrape_tool = ScrapeWebsiteTool()


def _ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


def get_llm() -> LLM:
    """Select LLM: API keys (Gemini, OpenAI, Anthropic) or local Ollama."""
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return LLM(model="gemini/gemini-2.0-flash", temperature=0.7)
    if os.getenv("OPENAI_API_KEY"):
        return LLM(model="openai/gpt-4o", temperature=0.7)
    if os.getenv("ANTHROPIC_API_KEY"):
        return LLM(model="anthropic/claude-3-5-sonnet-20241022", temperature=0.7)
    if _ollama_running():
        return LLM(model="ollama/llama3", base_url="http://127.0.0.1:11434", temperature=0.7)
    raise RuntimeError(
        "No LLM configured. Set one of: GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY in .env\n"
        "Or run Ollama locally: ollama pull llama3 && ollama serve"
    )


def create_news_crew(topic: str) -> Crew:
    """Create a crew that researches and summarizes trending news on a topic."""
    llm = get_llm()
    researcher = Agent(
        role=f"Senior News Researcher for {topic}",
        goal=f"Find the hottest and most relevant news about {topic}",
        backstory="You're a seasoned researcher who excels at finding trending news and filtering signal from noise.",
        tools=[news_search],
        llm=llm,
        verbose=True,
    )

    analyst = Agent(
        role=f"News Analyst for {topic}",
        goal="Synthesize news into a clear, structured digest",
        backstory="You turn raw news into actionable summaries with clear sections and key takeaways.",
        tools=[scrape_tool],
        llm=llm,
        verbose=True,
    )

    research_task = Task(
        description=f"""Search for the latest and hottest news about {topic}.
        Find at least 5-8 relevant articles. Include both breaking news and trending discussions.
        Return a structured list with: title, summary, URL, and why it matters.""",
        expected_output="A list of 5-8 news items with title, 2-sentence summary, URL, and relevance note.",
        agent=researcher,
    )

    report_task = Task(
        description="""Take the research findings and create a polished news digest.
        Structure: 1) Executive summary, 2) Key headlines (with brief context), 3) Trends to watch.
        Format as clean markdown.""",
        expected_output="A markdown report with executive summary, key headlines, and trends section.",
        agent=analyst,
        context=[research_task],
    )

    return Crew(
        agents=[researcher, analyst],
        tasks=[research_task, report_task],
        process=Process.sequential,
        verbose=True,
    )
