"""Minimal OpenAI-only LLM provider for DS Reporter."""

import aiofiles
import asyncio
import importlib
import json
import os
import subprocess
import sys
import traceback
from enum import Enum
from typing import Any

from colorama import Fore, Style, init

_SUPPORTED_PROVIDERS = {"openai"}

NO_SUPPORT_TEMPERATURE_MODELS = [
    "o1-mini",
    "o1-mini-2024-09-12",
    "o1",
    "o1-2024-12-17",
    "o3-mini",
    "o3-mini-2025-01-31",
    "o1-preview",
    "o3",
    "o3-2025-04-16",
    "o4-mini",
    "o4-mini-2025-04-16",
    # GPT-5 family: OpenAI enforces default temperature only.
    "gpt-5",
    "gpt-5-mini",
]

SUPPORT_REASONING_EFFORT_MODELS = [
    "o3-mini",
    "o3-mini-2025-01-31",
    "o3",
    "o3-2025-04-16",
    "o4-mini",
    "o4-mini-2025-04-16",
]


class ReasoningEfforts(Enum):
    High = "high"
    Medium = "medium"
    Low = "low"


class ChatLogger:
    """Helper utility to log chat requests and responses."""

    def __init__(self, fname: str):
        self.fname = fname
        self._lock = asyncio.Lock()

    async def log_request(self, messages, response):
        async with self._lock:
            async with aiofiles.open(self.fname, mode="a", encoding="utf-8") as handle:
                await handle.write(
                    json.dumps(
                        {
                            "messages": messages,
                            "response": response,
                            "stacktrace": traceback.format_exc(),
                        }
                    )
                    + "\n"
                )


class GenericLLMProvider:
    def __init__(self, llm, chat_log: str | None = None, verbose: bool = True):
        self.llm = llm
        self.chat_logger = ChatLogger(chat_log) if chat_log else None
        self.verbose = verbose
        self.last_usage_metadata: dict[str, Any] | None = None
        self.last_response_metadata: dict[str, Any] = {}

    def _reset_last_response_metadata(self) -> None:
        self.last_usage_metadata = None
        self.last_response_metadata = {}

    def _capture_response_metadata(self, message: Any) -> None:
        usage_metadata = getattr(message, "usage_metadata", None)
        if usage_metadata:
            if hasattr(usage_metadata, "model_dump"):
                usage_metadata = usage_metadata.model_dump()
            self.last_usage_metadata = dict(usage_metadata)

        response_metadata = getattr(message, "response_metadata", None)
        if response_metadata:
            if hasattr(response_metadata, "model_dump"):
                response_metadata = response_metadata.model_dump()
            self.last_response_metadata = {
                **self.last_response_metadata,
                **dict(response_metadata),
            }

    @classmethod
    def from_provider(
        cls,
        provider: str,
        chat_log: str | None = None,
        verbose: bool = True,
        **kwargs: Any,
    ):
        if provider != "openai":
            supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
            raise ValueError(
                f"Unsupported {provider}.\n\nSupported model providers are: {supported}"
            )

        _check_pkg("langchain_openai")
        from langchain_openai import ChatOpenAI

        # Support custom OpenAI-compatible APIs via OPENAI_BASE_URL.
        if "openai_api_base" not in kwargs and os.environ.get("OPENAI_BASE_URL"):
            kwargs["openai_api_base"] = os.environ["OPENAI_BASE_URL"]

        llm = ChatOpenAI(**kwargs)
        return cls(llm, chat_log, verbose=verbose)

    async def get_chat_response(self, messages, stream, websocket=None, **kwargs):
        self._reset_last_response_metadata()
        if not stream:
            output = await self.llm.ainvoke(messages, **kwargs)
            self._capture_response_metadata(output)
            res = output.content
        else:
            res = await self.stream_response(messages, websocket, **kwargs)

        if self.chat_logger:
            await self.chat_logger.log_request(messages, res)

        return res

    async def stream_response(self, messages, websocket=None, **kwargs):
        self._reset_last_response_metadata()
        paragraph = ""
        response = ""

        async for chunk in self.llm.astream(messages, **kwargs):
            self._capture_response_metadata(chunk)
            content = chunk.content
            if not content:
                continue
            response += content
            paragraph += content
            if "\n" in paragraph:
                await self._send_output(paragraph, websocket)
                paragraph = ""

        if paragraph:
            await self._send_output(paragraph, websocket)

        return response

    async def _send_output(self, content, websocket=None):
        if websocket is not None:
            await websocket.send_json({"type": "report", "output": content})
        elif self.verbose:
            print(f"{Fore.GREEN}{content}{Style.RESET_ALL}", flush=True)


def _check_pkg(pkg: str) -> None:
    if importlib.util.find_spec(pkg):
        return

    pkg_kebab = pkg.replace("_", "-")
    init(autoreset=True)
    print(f"{Fore.YELLOW}Installing {pkg_kebab}...{Style.RESET_ALL}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", pkg_kebab])
        importlib.invalidate_caches()
        print(f"{Fore.GREEN}Successfully installed {pkg_kebab}{Style.RESET_ALL}")
    except subprocess.CalledProcessError:
        raise ImportError(
            Fore.RED
            + f"Failed to install {pkg_kebab}. Please install manually with "
            f"`pip install -U {pkg_kebab}`"
        )
