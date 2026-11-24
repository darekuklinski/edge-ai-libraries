# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import json
import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .account_store import _ensure_tables, _get_engine

_BASE_INSTRUCTIONS = """You have no access to the internet. Ask clarifying questions when a question is unclear. If you do not know the answer, say so.

Use the retrieved context when relevant and combine it with your general knowledge. If the context does not contain the answer, say so and answer from general knowledge when possible. Do not invent facts or attribute unsupported statements to the context.

Prioritize clarity and scannability. For longer answers, use Markdown headings, lists, emphasis, tables, and fenced code blocks as appropriate. Short answers may use plain text."""

_SEED_PROMPTS = [
    {"id": "general", "name": "General", "content": _BASE_INSTRUCTIONS, "is_default": True},
    {"id": "gpt", "name": "GPT family", "content": _BASE_INSTRUCTIONS + "\n\nGive a direct answer and do not expose private reasoning.", "is_default": False},
    {"id": "qwen", "name": "Qwen family", "content": _BASE_INSTRUCTIONS + "\n\nFollow the user's requested language and format.", "is_default": False},
    {"id": "llama", "name": "Llama family", "content": _BASE_INSTRUCTIONS + "\n\nAnswer clearly and distinguish retrieved evidence from inference.", "is_default": False},
    {"id": "mistral", "name": "Mistral family", "content": _BASE_INSTRUCTIONS + "\n\nBe concise and follow the user's requested format.", "is_default": False},
]
_SEED_ASSIGNMENTS = [
    {"scope": "family", "target": name, "prompt_id": name}
    for name in ("gpt", "qwen", "llama", "mistral")
]


async def initialize_system_prompts(connection) -> None:
    await connection.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_system_prompts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await connection.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS chat_system_prompts_name_idx
        ON chat_system_prompts (lower(name))
    """))
    await connection.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS chat_system_prompts_default_idx
        ON chat_system_prompts (is_default) WHERE is_default
    """))
    await connection.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_system_prompt_assignments (
            scope TEXT NOT NULL CHECK (scope IN ('model', 'family')),
            target TEXT NOT NULL CHECK (target <> ''),
            prompt_id TEXT NOT NULL REFERENCES chat_system_prompts(id) ON DELETE CASCADE,
            PRIMARY KEY (scope, target)
        )
    """))
    await connection.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_system_prompt_setup (
            id SMALLINT PRIMARY KEY CHECK (id = 1)
        )
    """))
    await connection.execute(text("""
        WITH setup AS (
            INSERT INTO chat_system_prompt_setup (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING RETURNING id
        ), prompts AS (
            INSERT INTO chat_system_prompts (id, name, content, is_default)
            SELECT entry.id, entry.name, entry.content, entry.is_default
            FROM setup CROSS JOIN jsonb_to_recordset(CAST(:prompts AS JSONB))
                AS entry(id TEXT, name TEXT, content TEXT, is_default BOOLEAN)
            RETURNING id
        )
        INSERT INTO chat_system_prompt_assignments (scope, target, prompt_id)
        SELECT entry.scope, entry.target, entry.prompt_id
        FROM jsonb_to_recordset(CAST(:assignments AS JSONB))
            AS entry(scope TEXT, target TEXT, prompt_id TEXT)
        JOIN prompts ON prompts.id = entry.prompt_id
    """), {"prompts": json.dumps(_SEED_PROMPTS), "assignments": json.dumps(_SEED_ASSIGNMENTS)})


async def list_system_prompts() -> tuple[list[dict], list[dict]]:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        prompts = await connection.execute(text("""
            SELECT id, name, content, is_default FROM chat_system_prompts
            ORDER BY is_default DESC, lower(name)
        """))
        assignments = await connection.execute(text("""
            SELECT scope, target, prompt_id FROM chat_system_prompt_assignments
            ORDER BY scope, target
        """))
        return [dict(row) for row in prompts.mappings()], [
            dict(row) for row in assignments.mappings()
        ]


async def save_system_prompt(name: str, content: str, prompt_id: str | None = None) -> str:
    name, content = name.strip(), content.strip()
    if not name or not content:
        raise ValueError("A name and system prompt are required.")
    await _ensure_tables()
    try:
        async with _get_engine().begin() as connection:
            if prompt_id is None:
                prompt_id = str(uuid.uuid4())
                await connection.execute(text("""
                    INSERT INTO chat_system_prompts (id, name, content)
                    VALUES (:id, :name, :content)
                """), {"id": prompt_id, "name": name, "content": content})
            else:
                result = await connection.execute(text("""
                    UPDATE chat_system_prompts SET name = :name, content = :content,
                        updated_at = NOW() WHERE id = :id RETURNING id
                """), {"id": prompt_id, "name": name, "content": content})
                if result.scalar_one_or_none() is None:
                    raise ValueError("System prompt not found.")
    except IntegrityError as error:
        raise ValueError("A system prompt with this name already exists.") from error
    return prompt_id


async def set_default_system_prompt(prompt_id: str) -> None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        await connection.execute(text("LOCK TABLE chat_system_prompts IN EXCLUSIVE MODE"))
        result = await connection.execute(
            text("SELECT id FROM chat_system_prompts WHERE id = :id"), {"id": prompt_id}
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("System prompt not found.")
        await connection.execute(text("UPDATE chat_system_prompts SET is_default = FALSE WHERE is_default"))
        await connection.execute(
            text("UPDATE chat_system_prompts SET is_default = TRUE WHERE id = :id"), {"id": prompt_id}
        )


async def delete_system_prompt(prompt_id: str) -> None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        await connection.execute(text("LOCK TABLE chat_system_prompts IN EXCLUSIVE MODE"))
        result = await connection.execute(
            text("SELECT is_default FROM chat_system_prompts WHERE id = :id"), {"id": prompt_id}
        )
        is_default = result.scalar_one_or_none()
        if is_default is None:
            raise ValueError("System prompt not found.")
        if is_default:
            raise ValueError("Select another default before deleting this system prompt.")
        await connection.execute(
            text("DELETE FROM chat_system_prompts WHERE id = :id"), {"id": prompt_id}
        )


async def set_prompt_assignment(scope: str, target: str, prompt_id: str) -> None:
    target = target.strip().lower()
    if scope not in ("model", "family") or not target:
        raise ValueError("A model or family target is required.")
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        prompt = await connection.execute(
            text("SELECT id FROM chat_system_prompts WHERE id = :id"), {"id": prompt_id}
        )
        if prompt.scalar_one_or_none() is None:
            raise ValueError("System prompt not found.")
        if scope == "model":
            model = await connection.execute(text("""
                SELECT id FROM chat_models WHERE lower(model_name) = :target
                AND task = 'llm' LIMIT 1
            """), {"target": target})
            if model.scalar_one_or_none() is None:
                raise ValueError("Language model not found.")
        await connection.execute(text("""
            INSERT INTO chat_system_prompt_assignments (scope, target, prompt_id)
            VALUES (:scope, :target, :prompt_id)
            ON CONFLICT (scope, target) DO UPDATE SET prompt_id = EXCLUDED.prompt_id
        """), {"scope": scope, "target": target, "prompt_id": prompt_id})


async def delete_prompt_assignment(scope: str, target: str) -> None:
    target = target.strip().lower()
    if scope not in ("model", "family") or not target:
        raise ValueError("A model or family target is required.")
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        result = await connection.execute(text("""
            DELETE FROM chat_system_prompt_assignments
            WHERE scope = :scope AND target = :target RETURNING target
        """), {"scope": scope, "target": target})
        if result.scalar_one_or_none() is None:
            raise ValueError("System prompt assignment not found.")


async def get_system_prompt_for_model(model_name: str) -> str:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(text("""
            SELECT prompt.content
            FROM chat_system_prompts AS prompt
            LEFT JOIN chat_system_prompt_assignments AS assignment
                ON assignment.prompt_id = prompt.id
                AND ((assignment.scope = 'model' AND assignment.target = lower(:model_name))
                    OR (assignment.scope = 'family'
                        AND position(assignment.target in lower(:model_name)) > 0))
            WHERE assignment.prompt_id IS NOT NULL OR prompt.is_default
            ORDER BY CASE assignment.scope WHEN 'model' THEN 0 WHEN 'family' THEN 1 ELSE 2 END,
                length(assignment.target) DESC NULLS LAST, assignment.target
            LIMIT 1
        """), {"model_name": model_name})
        prompt = result.scalar_one_or_none()
        if prompt is None:
            raise RuntimeError("No default system prompt is configured.")
        return prompt
