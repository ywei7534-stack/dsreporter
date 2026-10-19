# GPT Researcher — LangGraph Multi-Agent Core

A trimmed-down version of GPT Researcher that keeps only the LangGraph
multi-agent research pipeline and the minimum of the `gpt_researcher`
single-agent engine it depends on.

## Structure

- `multi_agents/` — the LangGraph graph and the eight research agents.
- `gpt_researcher/` — trimmed single-agent research engine used by the Researcher node.
- `main.py` — CLI entry point (reads `task.json`).
- `task.json` — research task configuration.
- `langgraph.json` — LangGraph Studio / CLI graph definition.

## Agents

Human, Chief Editor, Editor, Researcher, Reviewer, Reviser, Writer, Publisher.

## Configure

Copy `.env.example` to `.env` and set `OPENAI_API_KEY` plus your search keys
(`TAVILY_API_KEY` and/or `XQUIK_API_KEY`). DuckDuckGo and arXiv need no key.

## Run

```bash
pip install -r requirements.txt
python main.py "Your research query"
```

The final report is written to `outputs/run_<id>/` in Markdown, PDF, and DOCX.

## Run the graph

```bash
langgraph up
```
