import asyncio
import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from app.web_search import WebSearchResult


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
        AsyncMock(return_value=[Document(
            page_content="retrieved evidence", metadata={"url": "https://example.com/article"}
        )]),
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

    async def exercise(web_search=None):
        return [
            chunk async for chunk in chain.process_chunks(
                [SimpleNamespace(role="user", content="Question?")],
                100, model_name="Qwen/Qwen3", web_search=web_search, web_rules=[
                    {"kind": "phrase", "effect": "allow", "value": "Apollo"},
                    {"kind": "url", "effect": "allow", "value": "https://en.wikipedia.org/wiki/Apollo"},
                ],
            )
        ]

    assert asyncio.run(exercise()) == ["data: answer\n\n"]
    resolve.assert_awaited_once_with("Qwen/Qwen3")
    assert [message.type for message in captured[0]] == ["system", "human"]
    assert captured[0][0].content == "Follow {literal} instructions."
    assert "retrieved evidence" in captured[0][1].content
    assert "Source: https://example.com/article" in captured[0][1].content
    assert "Question?" in captured[0][1].content
    assert "No live web search was requested." in captured[0][1].content

    search = AsyncMock(return_value=WebSearchResult([Document(
        page_content="Wikipedia evidence", metadata={"source": "https://en.wikipedia.org/wiki/Apollo_11"}
    )]))
    monkeypatch.setattr(chain, "search_web", search)
    assert asyncio.run(exercise("Apollo 11")) == [
        "data: answer\n\n",
        "data: \\n\\nWeb sources: [1](https://en.wikipedia.org/wiki/Apollo_11)\n\n",
    ]
    assert search.await_args.args[0] == "Apollo 11"
    assert "Wikipedia evidence" in captured[1][1].content
    assert "https://en.wikipedia.org/wiki/Apollo_11" in captured[1][1].content

    def refining_model(value):
        if isinstance(value, list):
            return AIMessage(content="Apollo")
        captured.append(value.to_messages())
        return "answer"

    monkeypatch.setattr(chain, "EGAIModelServing", lambda **_kwargs: RunnableLambda(refining_model))
    search.reset_mock()
    search.side_effect = [WebSearchResult([]), WebSearchResult([Document(
        page_content="Refined evidence", metadata={"source": "https://en.wikipedia.org/wiki/Apollo"}
    )])]
    assert asyncio.run(exercise("Apollo missing")) == [
        "data: answer\n\n",
        "data: \\n\\nWeb sources: [1](https://en.wikipedia.org/wiki/Apollo)\n\n",
    ]
    assert [call.args[0] for call in search.await_args_list] == ["Apollo missing", "Apollo"]
    assert "Refined evidence" in captured[2][1].content
