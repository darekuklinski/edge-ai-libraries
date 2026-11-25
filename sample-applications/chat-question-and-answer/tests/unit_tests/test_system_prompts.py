import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.account_store as account_store
from app import system_prompts


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured")
def test_prompt_storage_resolution_and_seed_lifecycle(monkeypatch):
    async def exercise():
        database_url = os.environ["TEST_DATABASE_URL"]
        schema = "test_prompts_" + uuid.uuid4().hex
        admin_engine = create_async_engine(database_url)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            database_url, connect_args={"server_settings": {"search_path": schema}}
        )
        try:
            monkeypatch.setattr(account_store, "_get_engine", lambda: engine)
            monkeypatch.setattr(system_prompts, "_get_engine", lambda: engine)
            monkeypatch.setattr(account_store, "_tables_ready", False)
            monkeypatch.setenv("LLM_MODEL", "")
            monkeypatch.setenv("EMBEDDING_MODEL_NAME", "")
            monkeypatch.setenv("RERANKER_MODEL", "")

            prompts, assignments = await system_prompts.list_system_prompts()
            assert {item["id"] for item in prompts} == {"general", "gpt", "qwen", "llama", "mistral"}
            assert len(assignments) == 4
            assert await system_prompts.get_system_prompt_for_model("Qwen/Qwen3") == next(
                item["content"] for item in prompts if item["id"] == "qwen"
            )
            general = next(item["content"] for item in prompts if item["id"] == "general")
            assert await system_prompts.get_system_prompt_for_model("unknown/model") == general

            async with engine.begin() as connection:
                await connection.execute(text("""
                    UPDATE chat_system_prompts SET content = :content WHERE id = 'llama'
                """), {"content": next(
                    item["content"] for item in prompts if item["id"] == "llama"
                ).replace(system_prompts._WEB_OPENING, system_prompts._LEGACY_OPENING, 1)})
                await connection.execute(text("""
                    UPDATE chat_system_prompts SET content = 'Custom instructions' WHERE id = 'gpt'
                """))
                await system_prompts.initialize_system_prompts(connection)
            prompts, assignments = await system_prompts.list_system_prompts()
            assert next(item["content"] for item in prompts if item["id"] == "llama").startswith(
                system_prompts._WEB_OPENING
            )
            assert next(item["content"] for item in prompts if item["id"] == "gpt") == "Custom instructions"

            async with engine.begin() as connection:
                await connection.execute(text("""
                    INSERT INTO chat_models (id, model_name, display_name, task)
                    VALUES ('model-1', 'Qwen/Qwen3', 'Qwen3', 'llm')
                """))
            custom = await system_prompts.save_system_prompt("Custom", "Instructions {literal}")
            await system_prompts.save_system_prompt("Custom", "Updated {literal}", custom)
            await system_prompts.set_prompt_assignment("family", "qwen3", custom)
            assert await system_prompts.get_system_prompt_for_model("qwen/QWEN3") == "Updated {literal}"
            await system_prompts.set_prompt_assignment("model", "Qwen/Qwen3", "gpt")
            assert await system_prompts.get_system_prompt_for_model("Qwen/Qwen3") == next(
                item["content"] for item in prompts if item["id"] == "gpt"
            )
            await system_prompts.delete_prompt_assignment("model", "Qwen/Qwen3")
            assert await system_prompts.get_system_prompt_for_model("Qwen/Qwen3") == "Updated {literal}"
            await system_prompts.set_default_system_prompt(custom)
            assert await system_prompts.get_system_prompt_for_model("unknown/model") == "Updated {literal}"
            with pytest.raises(ValueError, match="another default"):
                await system_prompts.delete_system_prompt(custom)
            with pytest.raises(ValueError, match="already exists"):
                await system_prompts.save_system_prompt("custom", "Other")
            with pytest.raises(ValueError, match="Language model not found"):
                await system_prompts.set_prompt_assignment("model", "unknown/model", custom)
            await system_prompts.set_default_system_prompt("general")
            await system_prompts.delete_system_prompt(custom)
            await system_prompts.delete_system_prompt("qwen")
            monkeypatch.setattr(account_store, "_tables_ready", False)
            prompts, assignments = await system_prompts.list_system_prompts()
            assert all(item["id"] not in ("qwen", custom) for item in prompts)
            assert all(item["prompt_id"] not in ("qwen", custom) for item in assignments)
            assert await system_prompts.get_system_prompt_for_model("Qwen/Qwen3") == general
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(exercise())
