import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.account_store as account_store
from app import web_policy


RULES = [
    {"kind": "url", "effect": "allow", "value": "https://example.com/article"},
    {"kind": "phrase", "effect": "allow", "value": "Apollo 11"},
]


def test_policy_is_default_deny_and_deny_rules_win():
    with pytest.raises(ValueError, match="allowed URL"):
        web_policy.select_web_query("Apollo 11", [])
    assert web_policy.select_web_query("Tell me about APOLLO 11 today", RULES) == "Apollo 11"
    assert web_policy.select_web_query("Summarize https://example.com/article", RULES) == "https://example.com/article"
    with pytest.raises(ValueError, match="not allowed"):
        web_policy.select_web_query("Read https://example.com/other", RULES)
    denied = RULES + [{"kind": "phrase", "effect": "deny", "value": "secret"}]
    with pytest.raises(ValueError, match="denied phrase"):
        web_policy.select_web_query("Apollo 11 secret", denied)
    denied_url = RULES + [{"kind": "url", "effect": "deny", "value": "https://example.com/article"}]
    assert not web_policy.allowed_page("https://example.com/article", denied_url)
    assert not web_policy.allowed_page("https://example.com/article?submit=true", RULES)


def test_allowed_url_with_parentheses_and_sentence_punctuation():
    url = "https://example.com/Article_(topic)"
    rules = web_policy.normalize_rules([{"kind": "url", "effect": "allow", "value": url}])
    assert web_policy.select_web_query(f"Summarize {url}", rules) == rules[0]["value"]
    assert web_policy.select_web_query(f"Summarize {url}.", rules) == rules[0]["value"]
    with pytest.raises(ValueError, match="not allowed"):
        web_policy.select_web_query(
            "Read https://example.com/article)",
            web_policy.normalize_rules(
                RULES + [{"kind": "url", "effect": "deny", "value": "https://example.com/article)"}]
            ),
        )


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured")
def test_rules_persist_separately_for_each_user(monkeypatch):
    async def exercise():
        database_url = os.environ["TEST_DATABASE_URL"]
        schema = "test_web_rules_" + uuid.uuid4().hex
        admin_engine = create_async_engine(database_url)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(database_url, connect_args={"server_settings": {"search_path": schema}})
        try:
            monkeypatch.setattr(account_store, "_get_engine", lambda: engine)
            monkeypatch.setattr(web_policy, "_get_engine", lambda: engine)
            monkeypatch.setattr(account_store, "_tables_ready", False)
            await account_store._ensure_tables()
            async with engine.begin() as connection:
                await connection.execute(text("""
                    INSERT INTO chat_users (id, username, password_hash)
                    VALUES (1, 'user_one', 'hash'), (2, 'user_two', 'hash')
                """))
            assert await web_policy.get_web_rules(1) == []
            assert await web_policy.save_web_rules(1, RULES) == RULES
            assert await web_policy.get_web_rules(1) == RULES
            assert await web_policy.get_web_rules(2) == []
            await web_policy.save_web_rules(2, [{"kind": "phrase", "effect": "deny", "value": "secret"}])
            assert await web_policy.get_web_rules(1) == RULES
            with pytest.raises(ValueError, match="Duplicate"):
                await web_policy.save_web_rules(1, RULES + [RULES[0]])
            assert await web_policy.get_web_rules(1) == RULES
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(exercise())
