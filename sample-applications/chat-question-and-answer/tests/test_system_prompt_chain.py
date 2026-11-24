import asyncio
import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda


def test_selected_system_prompt_reaches_chat_model_with_reranked_context(monkeypatch):
    monkeypatch.setenv("PG_CONNECTION_STRING", "postgresql+asyncpg://test:test@localhost/test")
    spec = importlib.util.spec_from_file_location(
        "app.chain_system_prompt_test", Path(__file__).parents[1] / "app" / "chain.py"
    )
    assert spec is not None and spec.loader is not None
    chain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chain)

    resolve = AsyncMock(return_value="Follow {literal} instructions.")
    monkeypatch.setattr(chain, "get_system_prompt_for_model", resolve)
    monkeypatch.setattr(chain, "get_default_model_settings", AsyncMock(return_value=None))
    monkeypatch.setattr(
        chain, "context_retriever_fn",
        AsyncMock(return_value=[Document(page_content="retrieved evidence")]),
    )

    class Reranker:
        def __init__(self, **_kwargs):
            pass

        def rerank(self, inputs):
            return {key: inputs[key] for key in ("question", "context", "history")}

    captured = []
    monkeypatch.setattr(chain, "CustomReranker", Reranker)
    monkeypatch.setattr(
        chain, "EGAIModelServing",
        lambda **_kwargs: RunnableLambda(lambda value: captured.append(value.to_messages()) or "answer"),
    )

    @asynccontextmanager
    async def lease(_model):
        yield

    monkeypatch.setattr(chain.model_lifecycle, "lease", lease)

    async def exercise():
        return [
            chunk async for chunk in chain.process_chunks(
                [SimpleNamespace(role="user", content="Question?")],
                100, model_name="Qwen/Qwen3",
            )
        ]

    assert asyncio.run(exercise()) == ["data: answer\n\n"]
    resolve.assert_awaited_once_with("Qwen/Qwen3")
    assert [message.type for message in captured[0]] == ["system", "human"]
    assert captured[0][0].content == "Follow {literal} instructions."
    assert "retrieved evidence" in captured[0][1].content
    assert "Question?" in captured[0][1].content
