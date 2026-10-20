"""OpenAI embedding provider management for DS Reporter."""

import os
from typing import Any

OPENAI_EMBEDDING_MODEL = os.environ.get(
    "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
)

_SUPPORTED_PROVIDERS = {"openai", "custom"}


class Memory:
    """Manages OpenAI embedding generation for document similarity and retrieval."""

    def __init__(self, embedding_provider: str, model: str, **embedding_kwargs: Any):
        _embeddings = None
        match embedding_provider:
            case "custom":
                from langchain_openai import OpenAIEmbeddings

                _embeddings = OpenAIEmbeddings(
                    model=model,
                    openai_api_key=os.getenv("OPENAI_API_KEY", "custom"),
                    openai_api_base=(
                        os.getenv("EMBEDDING_BASE_URL")
                        or os.getenv("OLLAMA_BASE_URL")
                        or os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
                    ),
                    check_embedding_ctx_length=False,
                    **embedding_kwargs,
                )
            case "openai":
                from langchain_openai import OpenAIEmbeddings

                if "openai_api_base" not in embedding_kwargs and os.environ.get(
                    "OPENAI_BASE_URL"
                ):
                    embedding_kwargs["openai_api_base"] = os.environ["OPENAI_BASE_URL"]

                _embeddings = OpenAIEmbeddings(model=model, **embedding_kwargs)
            case _:
                raise Exception("Embedding not found.")

        self._embeddings = _embeddings

    def get_embeddings(self):
        return self._embeddings
