"""Run the LangGraph multi-agent research pipeline from task.json."""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from multi_agents.agents import ChiefEditorAgent

# On Chinese Windows the console defaults to the GBK codec, which crashes the
# whole LLM retry loop as soon as a response contains characters like é/œ/–.
# Force UTF-8 (with replacement) for stdout/stderr before anything prints.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

load_dotenv()

if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "")

if os.environ.get("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"


def open_task() -> dict:
    task_path = Path(__file__).with_name("task.json")
    if not task_path.exists():
        raise FileNotFoundError(f"task.json not found at {task_path}")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    if not task:
        raise ValueError("task.json is empty. Please provide a valid research task.")
    return task


async def run_research_task(query: str | None = None) -> dict:
    task = open_task()
    if query:
        task["query"] = query
    chief_editor = ChiefEditorAgent(task)
    return await chief_editor.run_research_task(task_id=uuid.uuid4())


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else None
    result = asyncio.run(run_research_task(query))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
