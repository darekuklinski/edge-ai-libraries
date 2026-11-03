# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

SESSION_COOKIE_NAME = "chatqna_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
PASSWORD_HASH_ITERATIONS = 600_000

_tables_ready = False
_tables_lock = asyncio.Lock()


def _get_engine() -> AsyncEngine:
    from .chain import engine

    return engine


async def _ensure_tables() -> None:
    global _tables_ready

    if _tables_ready:
        return

    async with _tables_lock:
        if _tables_ready:
            return

        async with _get_engine().begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_users (
                        id BIGSERIAL PRIMARY KEY,
                        username VARCHAR(32) NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_user_sessions (
                        token_hash CHAR(64) PRIMARY KEY,
                        user_id BIGINT NOT NULL
                            REFERENCES chat_users(id) ON DELETE CASCADE,
                        expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_user_conversation_history (
                        user_id BIGINT PRIMARY KEY
                            REFERENCES chat_users(id) ON DELETE CASCADE,
                        conversations JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
        _tables_ready = True


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return f"{PASSWORD_HASH_ITERATIONS}${salt.hex()}${password_hash.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        iterations_text, salt_hex, expected_hash = stored_hash.split("$", 2)
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations
        ).hex()
        return secrets.compare_digest(actual_hash, expected_hash)
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return _hash_password("not-a-real-account-password")


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_account(username: str, password: str) -> dict[str, Any]:
    await _ensure_tables()
    password_hash = await asyncio.to_thread(_hash_password, password)

    try:
        async with _get_engine().begin() as connection:
            result = await connection.execute(
                text(
                    """
                    INSERT INTO chat_users (username, password_hash)
                    VALUES (:username, :password_hash)
                    RETURNING id, username
                    """
                ),
                {"username": username.lower(), "password_hash": password_hash},
            )
            user = result.mappings().one()
    except IntegrityError as error:
        raise ValueError("An account with this username already exists.") from error

    return {"id": user["id"], "username": user["username"]}


async def authenticate_account(username: str, password: str) -> dict[str, Any] | None:
    await _ensure_tables()

    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT id, username, password_hash
                FROM chat_users
                WHERE username = :username
                """
            ),
            {"username": username.lower()},
        )
        user = result.mappings().one_or_none()

    valid = await asyncio.to_thread(
        _verify_password,
        password,
        user["password_hash"] if user else _dummy_password_hash(),
    )
    if not user or not valid:
        return None
    return {"id": user["id"], "username": user["username"]}


async def create_session(user_id: int) -> str:
    await _ensure_tables()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_session_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=SESSION_MAX_AGE_SECONDS
    )

    async with _get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO chat_user_sessions (token_hash, user_id, expires_at)
                VALUES (:token_hash, :user_id, :expires_at)
                """
            ),
            {"token_hash": token_hash, "user_id": user_id, "expires_at": expires_at},
        )
    return token


async def get_session_user(token: str) -> dict[str, Any] | None:
    await _ensure_tables()

    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT users.id, users.username
                FROM chat_user_sessions AS sessions
                JOIN chat_users AS users ON users.id = sessions.user_id
                WHERE sessions.token_hash = :token_hash
                  AND sessions.expires_at > NOW()
                """
            ),
            {"token_hash": _hash_session_token(token)},
        )
        user = result.mappings().one_or_none()
    return dict(user) if user else None


async def delete_session(token: str) -> None:
    await _ensure_tables()

    async with _get_engine().begin() as connection:
        await connection.execute(
            text("DELETE FROM chat_user_sessions WHERE token_hash = :token_hash"),
            {"token_hash": _hash_session_token(token)},
        )


async def get_user_conversation_history(
    user_id: int,
) -> tuple[bool, list[dict[str, Any]]]:
    await _ensure_tables()

    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT conversations
                FROM chat_user_conversation_history
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        conversations = result.scalar_one_or_none()

    if conversations is None:
        return False, []
    return True, conversations


async def save_user_conversation_history(
    user_id: int, conversations: list[dict[str, Any]]
) -> None:
    await _ensure_tables()

    async with _get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO chat_user_conversation_history
                    (user_id, conversations, updated_at)
                VALUES
                    (:user_id, CAST(:conversations AS JSONB), NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET conversations = EXCLUDED.conversations,
                    updated_at = NOW()
                """
            ),
            {"user_id": user_id, "conversations": json.dumps(conversations)},
        )
