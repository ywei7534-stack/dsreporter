"""Create a research task and print its report as SSE chunks arrive."""

import argparse
import json
import sys
from typing import Any

import requests


for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


DEFAULT_QUERY = "AI 生产力效应的多维证据与情境依赖性"
TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a research task from the command line and stream its report."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--language", default="简体中文")
    parser.add_argument("--max-sections", type=int, default=1)
    parser.add_argument("--request-timeout", type=int, default=30)
    parser.add_argument("--stream-timeout", type=int, default=1800)
    return parser.parse_args()


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def create_task(args: argparse.Namespace) -> str:
    payload = {
        "query": args.query,
        "model": args.model,
        "source": "web",
        "language": args.language,
        "max_sections": args.max_sections,
        "max_plan_revisions": 0,
        "publish_formats": {
            "markdown": True,
            "pdf": False,
            "docx": False,
        },
        "include_human_feedback": False,
        "follow_guidelines": False,
        "guidelines": [],
        "verbose": False,
    }

    response = requests.post(
        f"{args.base_url.rstrip('/')}/api/v1/research-tasks",
        json=payload,
        timeout=args.request_timeout,
    )
    response.raise_for_status()
    task = response.json()
    log(f"[client] task_id={task['id']}")
    log(f"[client] status={task['status']} stage={task['current_stage']}")
    return task["id"]


def print_event(event: dict[str, Any], state: dict[str, Any]) -> bool:
    event_type = event.get("type", "")
    data = event.get("data") or {}

    if event_type == "snapshot":
        status = data.get("status")
        log(f"[stream] snapshot status={status} stage={data.get('current_stage')}")
        if status in TERMINAL_STATUSES:
            state["terminal_status"] = status
            return True
    elif event_type == "report_start":
        state["report_started"] = True
        log(
            "\n[stream] report_start "
            f"format={data.get('format')} length={data.get('length')}"
        )
    elif event_type == "report_delta":
        text = data.get("text", "")
        state["report_text"] += text
        print(text, end="", flush=True)
    elif event_type == "report_end":
        state["report_finished"] = True
        log(
            "\n[stream] report_end "
            f"length={data.get('length')} received={len(state['report_text'])}"
        )
    elif event_type == "stage":
        log(f"[stream] stage={data.get('stage')}")
    elif event_type == "progress":
        log(
            "[stream] progress="
            f"{data.get('completed_sections', 0)}/{data.get('planned_sections', '?')}"
        )
    elif event_type == "plan_review_required":
        log("[stream] plan review is required")
    elif event_type == "status":
        status = data.get("status")
        log(f"[stream] status={status}")
        if status in TERMINAL_STATUSES:
            state["terminal_status"] = status
            error = data.get("error")
            if error:
                log(
                    f"[stream] error={error.get('code')}: "
                    f"{error.get('message')}"
                )
            return True
    return False


def stream_events(
    args: argparse.Namespace,
    task_id: str,
    state: dict[str, Any],
) -> None:
    url = (
        f"{args.base_url.rstrip('/')}/api/v1/research-tasks/"
        f"{task_id}/events"
    )
    with requests.get(
        url,
        stream=True,
        headers={"Accept": "text/event-stream"},
        timeout=(args.request_timeout, args.stream_timeout),
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            if raw_line.startswith(":"):
                continue
            if not raw_line.startswith("data:"):
                continue

            payload = raw_line[5:].strip()
            event = json.loads(payload)
            if print_event(event, state):
                return


def fetch_fallback_report(args: argparse.Namespace, task_id: str) -> str:
    url = (
        f"{args.base_url.rstrip('/')}/api/v1/research-tasks/"
        f"{task_id}/result"
    )
    response = requests.get(url, timeout=args.request_timeout)
    response.raise_for_status()
    result = response.json()
    return result["result"]["report_markdown"]


def main() -> int:
    args = parse_args()
    state: dict[str, Any] = {
        "report_started": False,
        "report_finished": False,
        "report_text": "",
        "terminal_status": None,
    }

    try:
        task_id = create_task(args)
        stream_events(args, task_id, state)
    except requests.RequestException as exc:
        log(f"[client] request failed: {exc}")
        return 1
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log(f"[client] invalid response: {exc}")
        return 1

    if state["terminal_status"] == "failed":
        return 2

    if not state["report_finished"]:
        log("[client] report stream ended unexpectedly; fetching final result")
        try:
            report = fetch_fallback_report(args, task_id)
        except requests.RequestException as exc:
            log(f"[client] fallback result fetch failed: {exc}")
            return 1
        print(report, end="", flush=True)
        state["report_text"] = report

    print()
    log(f"[client] complete status={state['terminal_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
