# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

SESSION_COOKIE_NAME = "chatqna_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
PASSWORD_HASH_ITERATIONS = 600_000
ADMIN_DEFAULT_PASSWORD = "admin"

_tables_ready = False
_tables_lock = asyncio.Lock()


class ServiceSetupIncomplete(RuntimeError):
    pass


class HFTokenEncryptionUnavailable(RuntimeError):
    pass


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
                        role TEXT NOT NULL DEFAULT 'standard'
                            CHECK (role IN ('admin', 'standard')),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = current_schema()
                              AND table_name = 'chat_users'
                              AND column_name = 'role'
                        ) THEN
                            ALTER TABLE chat_users
                            ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'standard'
                                CHECK (role IN ('admin', 'standard'));
                            UPDATE chat_users
                            SET role = 'admin'
                            WHERE username = 'admin';
                        END IF;
                    END;
                    $$
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_service_setup (
                        id SMALLINT PRIMARY KEY CHECK (id = 1),
                        initialized BOOLEAN NOT NULL DEFAULT FALSE
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO chat_service_setup (id, initialized)
                    VALUES (1, FALSE)
                    ON CONFLICT (id) DO NOTHING
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_models (
                        id TEXT PRIMARY KEY,
                        model_name TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        task TEXT NOT NULL
                            CHECK (task IN ('llm', 'embedding', 'reranker')),
                        source TEXT,
                        backend TEXT,
                        artifact_location TEXT,
                        status TEXT NOT NULL DEFAULT 'ready'
                            CHECK (status IN ('queued', 'downloading', 'ready', 'failed', 'deleting')),
                        is_default BOOLEAN NOT NULL DEFAULT FALSE,
                        metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            await connection.execute(
                text("ALTER TABLE chat_models DROP CONSTRAINT IF EXISTS chat_models_model_name_key")
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
                    CREATE TABLE IF NOT EXISTS chat_user_huggingface_tokens (
                        user_id BIGINT PRIMARY KEY
                            REFERENCES chat_users(id) ON DELETE CASCADE,
                        token_hash CHAR(64) NOT NULL,
                        encrypted_token TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS chat_user_conversations (
                        user_id BIGINT NOT NULL
                            REFERENCES chat_users(id) ON DELETE CASCADE,
                        conversation_id TEXT NOT NULL,
                        title TEXT,
                        model_id TEXT
                            REFERENCES chat_models(id) ON DELETE SET NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (user_id, conversation_id)
                    )
                    """
                )
            )

            configured_models = (
                (
                    os.getenv("LLM_MODEL"),
                    "llm",
                    _configured_backend(),
                    True,
                ),
                (
                    os.getenv("EMBEDDING_MODEL_NAME"),
                    "embedding",
                    _backend_for_endpoint(os.getenv("EMBEDDING_ENDPOINT_URL")),
                    False,
                ),
                (os.getenv("RERANKER_MODEL"), "reranker", "tei", False),
            )
            for configured_model, task, backend, is_default in configured_models:
                if not configured_model:
                    continue
                await connection.execute(
                    text(
                        """
                        INSERT INTO chat_models
                            (id, model_name, display_name, task, backend, status, is_default)
                        VALUES
                            (:model_id, :model_name, :display_name, :task, :backend,
                             'ready', :is_default)
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "model_id": configured_model,
                        "model_name": configured_model,
                        "display_name": configured_model.rsplit("/", 1)[-1],
                        "task": task,
                        "backend": backend,
                        "is_default": is_default,
                    },
                )

            await connection.execute(
                text(
                    """
                    INSERT INTO chat_user_conversations
                        (user_id, conversation_id, title, model_id)
                    SELECT
                        history.user_id,
                        conversation->>'conversationId',
                        conversation->>'title',
                        model.id
                    FROM chat_user_conversation_history AS history
                    CROSS JOIN LATERAL jsonb_array_elements(history.conversations)
                        AS entries(conversation)
                    LEFT JOIN chat_models AS model
                        ON model.id = conversation->>'modelId'
                    WHERE NULLIF(conversation->>'conversationId', '') IS NOT NULL
                    ON CONFLICT (user_id, conversation_id) DO NOTHING
                    """
                )
            )
            await _merge_duplicate_installed_models(connection)
            await _merge_installed_model_placeholders(connection)
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


def _is_well_formed_password_hash(stored_hash: str) -> bool:
    try:
        iterations_text, salt_hex, hash_hex = stored_hash.split("$", 2)
        iterations = int(iterations_text)
        return (
            100_000 <= iterations <= 2_000_000
            and len(bytes.fromhex(salt_hex)) == 16
            and len(bytes.fromhex(hash_hex)) == hashlib.sha256().digest_size
        )
    except (ValueError, TypeError):
        return False


async def ensure_service_setup() -> None:
    """Provision the admin from deployment configuration, or fail closed."""
    await _ensure_tables()
    initial_admin_password = os.getenv("CHATQNA_ADMIN_PASSWORD", "")
    configured_password = (
        initial_admin_password
        if 8 <= len(initial_admin_password) <= 128
        else None
    )

    async with _get_engine().begin() as connection:
        await connection.execute(
            text("SELECT id FROM chat_service_setup WHERE id = 1 FOR UPDATE")
        )
        setup_result = await connection.execute(
            text("SELECT initialized FROM chat_service_setup WHERE id = 1")
        )
        if setup_result.scalar_one():
            return

        admin_result = await connection.execute(
            text(
                """
                SELECT id, password_hash
                FROM chat_users
                WHERE username = 'admin'
                FOR UPDATE
                """
            )
        )
        admin = admin_result.mappings().one_or_none()

        if admin and _is_well_formed_password_hash(admin["password_hash"]):
            is_default_password = await asyncio.to_thread(
                _verify_password, ADMIN_DEFAULT_PASSWORD, admin["password_hash"]
            )
            if not is_default_password:
                await connection.execute(
                    text(
                        """
                        UPDATE chat_service_setup
                        SET initialized = TRUE
                        WHERE id = 1
                        """
                    )
                )
                return

        if configured_password is None:
            raise ServiceSetupIncomplete

        password_hash = await asyncio.to_thread(
            _hash_password, configured_password
        )
        if admin:
            await connection.execute(
                text(
                    """
                    UPDATE chat_users
                    SET password_hash = :password_hash
                    WHERE id = :user_id
                    """
                ),
                {"password_hash": password_hash, "user_id": admin["id"]},
            )
        else:
            await connection.execute(
                text(
                    """
                    INSERT INTO chat_users (username, password_hash, role)
                    VALUES ('admin', :password_hash, 'admin')
                    """
                ),
                {"password_hash": password_hash},
            )
        await connection.execute(
            text("UPDATE chat_service_setup SET initialized = TRUE WHERE id = 1")
        )


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return _hash_password("not-a-real-account-password")


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hf_token_cipher() -> Fernet:
    key = os.getenv("HF_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise HFTokenEncryptionUnavailable(
            "HF_TOKEN_ENCRYPTION_KEY must be configured to store Hugging Face tokens."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise HFTokenEncryptionUnavailable(
            "HF_TOKEN_ENCRYPTION_KEY is invalid."
        ) from error


def encrypt_model_download_token(token: str) -> str:
    key = os.getenv("MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY")
    if not key:
        raise HFTokenEncryptionUnavailable(
            "MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY must be configured."
        )
    try:
        cipher = Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise HFTokenEncryptionUnavailable(
            "MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY is invalid."
        ) from error
    return cipher.encrypt(token.encode("utf-8")).decode("ascii")


def _hash_huggingface_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def has_user_huggingface_token(user_id: int) -> bool:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM chat_user_huggingface_tokens
                    WHERE user_id = :user_id
                )
                """
            ),
            {"user_id": user_id},
        )
        return bool(result.scalar_one())


async def save_user_huggingface_token(user_id: int, token: str) -> None:
    await _ensure_tables()
    cipher = _hf_token_cipher()
    token_hash = _hash_huggingface_token(token)
    encrypted_token = cipher.encrypt(token.encode("utf-8")).decode("ascii")

    async with _get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO chat_user_huggingface_tokens
                    (user_id, token_hash, encrypted_token, updated_at)
                VALUES (:user_id, :token_hash, :encrypted_token, NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET token_hash = EXCLUDED.token_hash,
                    encrypted_token = EXCLUDED.encrypted_token,
                    updated_at = NOW()
                """
            ),
            {
                "user_id": user_id,
                "token_hash": token_hash,
                "encrypted_token": encrypted_token,
            },
        )


async def get_user_huggingface_token(user_id: int) -> str | None:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT encrypted_token
                FROM chat_user_huggingface_tokens
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        encrypted_token = result.scalar_one_or_none()

    if encrypted_token is None:
        return None

    try:
        return _hf_token_cipher().decrypt(encrypted_token.encode("ascii")).decode(
            "utf-8"
        )
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as error:
        raise HFTokenEncryptionUnavailable(
            "The stored Hugging Face token could not be decrypted."
        ) from error


async def delete_user_huggingface_token(user_id: int) -> None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                DELETE FROM chat_user_huggingface_tokens
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )


async def create_account(
    username: str,
    password: str,
    role: Literal["admin", "standard"] = "standard",
) -> dict[str, Any]:
    if role not in {"admin", "standard"}:
        raise ValueError("Invalid account group.")
    await _ensure_tables()
    password_hash = await asyncio.to_thread(_hash_password, password)

    try:
        async with _get_engine().begin() as connection:
            result = await connection.execute(
                text(
                    """
                    INSERT INTO chat_users (username, password_hash, role)
                    VALUES (:username, :password_hash, :role)
                    RETURNING id, username, role
                    """
                ),
                {
                    "username": username.lower(),
                    "password_hash": password_hash,
                    "role": role,
                },
            )
            user = result.mappings().one()
    except IntegrityError as error:
        raise ValueError("An account with this username already exists.") from error

    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    }


async def list_user_accounts() -> list[dict[str, Any]]:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT id, username, role, created_at
                FROM chat_users
                ORDER BY username
                """
            )
        )
        return [dict(user) for user in result.mappings()]


async def set_account_role(
    user_id: int,
    role: Literal["admin", "standard"],
    actor_user_id: int | None = None,
) -> dict[str, Any] | None:
    if role not in {"admin", "standard"}:
        raise ValueError("Invalid account group.")
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        await connection.execute(
            text("SELECT id FROM chat_service_setup WHERE id = 1 FOR UPDATE")
        )
        user_result = await connection.execute(
            text("SELECT id, username, role FROM chat_users WHERE id = :user_id FOR UPDATE"),
            {"user_id": user_id},
        )
        user = user_result.mappings().one_or_none()
        if user is None:
            return None

        if user["role"] == "admin" and role == "standard":
            if user_id == actor_user_id:
                raise ValueError("You cannot remove your own administrator privileges.")
            admin_result = await connection.execute(
                text("SELECT COUNT(*) FROM chat_users WHERE role = 'admin'")
            )
            if admin_result.scalar_one() <= 1:
                raise ValueError("At least one administrator must remain.")

        await connection.execute(
            text("UPDATE chat_users SET role = :role WHERE id = :user_id"),
            {"user_id": user_id, "role": role},
        )
        return {"id": user["id"], "username": user["username"], "role": role}


async def get_managed_model_for_removal(model_id: str) -> dict[str, Any] | None:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT id, model_name, task, backend, artifact_location, status,
                       is_default, metadata
                FROM chat_models
                WHERE id = :model_id
                """
            ),
            {"model_id": model_id},
        )
        model = result.mappings().one_or_none()
    return dict(model) if model else None


async def begin_managed_model_removal(model_id: str) -> bool:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        result = await connection.execute(
            text(
                """
                UPDATE chat_models
                SET status = 'deleting', updated_at = NOW()
                WHERE id = :model_id
                  AND is_default = FALSE
                  AND status = 'ready'
                  AND artifact_location IS NOT NULL
                """
            ),
            {"model_id": model_id},
        )
        return result.rowcount == 1


async def cancel_managed_model_removal(model_id: str) -> None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE chat_models
                SET status = 'ready', updated_at = NOW()
                WHERE id = :model_id AND status = 'deleting'
                """
            ),
            {"model_id": model_id},
        )


async def delete_managed_model_record(model_id: str) -> bool:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        result = await connection.execute(
            text(
                """
                DELETE FROM chat_models
                WHERE id = :model_id
                  AND is_default = FALSE
                  AND status = 'deleting'
                  AND artifact_location IS NOT NULL
                """
            ),
            {"model_id": model_id},
        )
        return result.rowcount == 1


async def authenticate_account(username: str, password: str) -> dict[str, Any] | None:
    await _ensure_tables()

    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT id, username, password_hash, role
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
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


async def change_account_password(
    user_id: int, current_password: str, new_password: str
) -> bool:
    await _ensure_tables()

    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text("SELECT password_hash FROM chat_users WHERE id = :user_id"),
            {"user_id": user_id},
        )
        stored_hash = result.scalar_one_or_none()

    if stored_hash is None or not await asyncio.to_thread(
        _verify_password, current_password, stored_hash
    ):
        return False

    new_hash = await asyncio.to_thread(_hash_password, new_password)
    async with _get_engine().begin() as connection:
        result = await connection.execute(
            text(
                """
                UPDATE chat_users
                SET password_hash = :password_hash
                WHERE id = :user_id AND password_hash = :current_hash
                """
            ),
            {
                "user_id": user_id,
                "password_hash": new_hash,
                "current_hash": stored_hash,
            },
        )
        return result.rowcount == 1


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
                SELECT users.id, users.username, users.role
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
        model_result = await connection.execute(
            text(
                """
                SELECT conversation_id, model_id
                FROM chat_user_conversations
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        model_ids = {
            row["conversation_id"]: row["model_id"]
            for row in model_result.mappings()
        }

    if conversations is None:
        return False, []
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        conversation_id = conversation.get("conversationId")
        if conversation_id in model_ids:
            model_id = model_ids[conversation_id]
            if model_id is None:
                conversation.pop("modelId", None)
                continue
            conversation["modelId"] = model_id
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
        for conversation in conversations:
            conversation_id = conversation.get("conversationId")
            if not isinstance(conversation_id, str) or not conversation_id:
                continue
            model_id = conversation.get("modelId") or None
            if model_id is not None and not isinstance(model_id, str):
                raise ValueError("A conversation model ID must be a string.")
            if model_id is not None:
                model_result = await connection.execute(
                    text(
                        """
                        SELECT id
                        FROM chat_models
                        WHERE id = :model_id AND task = 'llm' AND status = 'ready'
                        """
                    ),
                    {"model_id": model_id},
                )
                if model_result.scalar_one_or_none() is None:
                    raise ValueError("A conversation references an unavailable model.")
            await connection.execute(
                text(
                    """
                    INSERT INTO chat_user_conversations
                        (user_id, conversation_id, title, model_id)
                    VALUES (:user_id, :conversation_id, :title, :model_id)
                    ON CONFLICT (user_id, conversation_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        model_id = COALESCE(
                            EXCLUDED.model_id, chat_user_conversations.model_id
                        ),
                        updated_at = NOW()
                    """
                ),
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "title": conversation.get("title"),
                    "model_id": model_id,
                },
            )
        await connection.execute(
            text(
                """
                DELETE FROM chat_user_conversations AS saved
                WHERE saved.user_id = :user_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(CAST(:conversations AS JSONB))
                          AS entries(incoming)
                      WHERE incoming->>'conversationId' = saved.conversation_id
                  )
                """
            ),
            {"user_id": user_id, "conversations": json.dumps(conversations)},
        )


def _configured_backend() -> str:
    return _backend_for_endpoint(os.getenv("ENDPOINT_URL"))


def _backend_for_endpoint(endpoint: str | None) -> str:
    endpoint = (endpoint or "").lower()
    if "ovms" in endpoint:
        return "ovms"
    if "vllm" in endpoint:
        return "vllm"
    if "text-generation" in endpoint:
        return "text-generation"
    return "unknown"


async def get_available_models() -> list[dict[str, Any]]:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT id, model_name, display_name, task, is_default
                FROM chat_models
                WHERE task = 'llm' AND status = 'ready'
                ORDER BY is_default DESC, display_name
                """
            )
        )
        return [dict(row) for row in result.mappings()]


def _managed_model_id(
    model_name: str, task: str, device: str | None, precision: str | None
) -> str:
    return "|".join((model_name, task, device or "", precision or ""))


async def _merge_duplicate_installed_models(connection: Any) -> None:
    result = await connection.execute(
        text(
            """
            SELECT id, model_name, task, artifact_location, is_default, metadata
            FROM chat_models
            WHERE artifact_location IS NOT NULL
              AND metadata->>'source' = 'ovms'
            ORDER BY model_name, task, artifact_location,
                     (NULLIF(metadata->>'precision', '') IS NULL), id
            """
        )
    )
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for model in result.mappings().all():
        key = (model["model_name"], model["task"], model["artifact_location"])
        groups.setdefault(key, []).append(model)

    for models in groups.values():
        if len(models) < 2:
            continue

        winner = models[0]
        has_default = any(model["is_default"] for model in models)
        if has_default and not winner["is_default"]:
            await connection.execute(
                text(
                    """
                    UPDATE chat_models
                    SET is_default = FALSE
                    WHERE task = :task AND is_default = TRUE
                    """
                ),
                {"task": winner["task"]},
            )
            await connection.execute(
                text(
                    """
                    UPDATE chat_models
                    SET is_default = TRUE
                    WHERE id = :installed_id
                    """
                ),
                {"installed_id": winner["id"]},
            )

        for duplicate in models[1:]:
            await connection.execute(
                text(
                    """
                    UPDATE chat_user_conversations
                    SET model_id = :installed_id
                    WHERE model_id = :duplicate_id
                    """
                ),
                {
                    "installed_id": winner["id"],
                    "duplicate_id": duplicate["id"],
                },
            )
            await connection.execute(
                text("DELETE FROM chat_models WHERE id = :duplicate_id"),
                {"duplicate_id": duplicate["id"]},
            )


async def _merge_installed_model_placeholders(connection: Any) -> None:
    placeholders = await connection.execute(
        text(
            """
            SELECT id, model_name, task, is_default
            FROM chat_models
            WHERE id = model_name AND artifact_location IS NULL
            """
        )
    )
    for placeholder in placeholders.mappings().all():
        installed_result = await connection.execute(
            text(
                """
                SELECT id, is_default
                FROM chat_models
                WHERE model_name = :model_name
                  AND task = :task
                  AND artifact_location IS NOT NULL
                  AND status = 'ready'
                ORDER BY is_default DESC, id
                """
            ),
            {
                "model_name": placeholder["model_name"],
                "task": placeholder["task"],
            },
        )
        installed_models = installed_result.mappings().all()
        if not installed_models:
            continue

        installed = installed_models[0]
        if placeholder["is_default"] and not installed["is_default"]:
            await connection.execute(
                text(
                    """
                    UPDATE chat_models
                    SET is_default = FALSE
                    WHERE task = :task AND is_default = TRUE
                    """
                ),
                {"task": placeholder["task"]},
            )
            await connection.execute(
                text(
                    """
                    UPDATE chat_models
                    SET is_default = TRUE
                    WHERE id = :installed_id
                    """
                ),
                {"installed_id": installed["id"]},
            )

        await connection.execute(
            text(
                """
                UPDATE chat_user_conversations
                SET model_id = :installed_id
                WHERE model_id = :placeholder_id
                """
            ),
            {
                "installed_id": installed["id"],
                "placeholder_id": placeholder["id"],
            },
        )
        await connection.execute(
            text("DELETE FROM chat_models WHERE id = :placeholder_id"),
            {"placeholder_id": placeholder["id"]},
        )


async def get_model_catalog() -> list[dict[str, Any]]:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT id, model_name, display_name, task, backend, artifact_location,
                       status, is_default, metadata, created_at, updated_at
                FROM chat_models
                ORDER BY CASE task
                    WHEN 'llm' THEN 0
                    WHEN 'reranker' THEN 1
                    ELSE 2
                END, display_name
                """
            )
        )
        return [dict(row) for row in result.mappings()]


async def sync_installed_models(models: list[dict[str, Any]]) -> None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        for model in models:
            model_name = model["model_name"]
            task = model["task"]
            device = model.get("device")
            precision = model.get("precision")
            model_id = _managed_model_id(model_name, task, device, precision)
            metadata = {
                "device": device,
                "precision": precision,
                "source": "ovms",
            }
            await connection.execute(
                text(
                    """
                    INSERT INTO chat_models
                        (id, model_name, display_name, task, backend,
                         artifact_location, status, metadata)
                    VALUES
                        (:id, :model_name, :display_name, :task, 'ovms',
                         :artifact_location, 'ready', CAST(:metadata AS JSONB))
                    ON CONFLICT (id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        backend = EXCLUDED.backend,
                        artifact_location = EXCLUDED.artifact_location,
                    status = CASE
                        WHEN chat_models.status = 'deleting' THEN 'deleting'
                        ELSE 'ready'
                    END,
                        metadata = chat_models.metadata || EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                {
                    "id": model_id,
                    "model_name": model_name,
                    "display_name": model.get("display_name") or model_name,
                    "task": task,
                    "artifact_location": model.get("artifact_location"),
                    "metadata": json.dumps(metadata),
                },
            )
        await _merge_duplicate_installed_models(connection)
        await _merge_installed_model_placeholders(connection)


async def register_managed_model(
    model_name: str,
    task: str,
    device: str,
    precision: str,
    is_ovms: bool,
    user_id: int,
) -> str:
    await _ensure_tables()
    model_id = _managed_model_id(model_name, task, device, precision)
    metadata = {
        "device": device,
        "precision": precision,
        "is_ovms": is_ovms,
        "requested_by": user_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "job_ids": [],
        "logs": "",
    }
    async with _get_engine().begin() as connection:
        result = await connection.execute(
            text(
                """
                INSERT INTO chat_models
                    (id, model_name, display_name, task, backend, status, metadata)
                VALUES
                    (:id, :model_name, :display_name, :task, 'ovms',
                     'downloading', CAST(:metadata AS JSONB))
                ON CONFLICT (id) DO UPDATE
                SET status = 'downloading',
                    artifact_location = NULL,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                WHERE chat_models.status != 'ready'
                """
            ),
            {
                "id": model_id,
                "model_name": model_name,
                "display_name": model_name.rsplit("/", 1)[-1],
                "task": task,
                "metadata": json.dumps(metadata),
            },
        )
        if result.rowcount != 1:
            raise ValueError("This model and configuration are already available.")
    return model_id


async def update_managed_model(
    model_id: str,
    status: str,
    *,
    job_ids: list[str] | None = None,
    logs: str | None = None,
    artifact_location: str | None = None,
) -> None:
    if status not in {"downloading", "ready", "failed"}:
        raise ValueError("Invalid managed model status.")
    metadata_update: dict[str, Any] = {}
    if job_ids is not None:
        metadata_update["job_ids"] = job_ids
    if logs is not None:
        metadata_update["logs"] = logs[:50000]

    await _ensure_tables()
    async with _get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE chat_models
                SET status = :status,
                    artifact_location = COALESCE(:artifact_location, artifact_location),
                    metadata = metadata || CAST(:metadata AS JSONB),
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {
                "id": model_id,
                "status": status,
                "artifact_location": artifact_location,
                "metadata": json.dumps(metadata_update),
            },
        )


async def set_default_model(model_id: str) -> None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        model = await connection.execute(
            text(
                """
                SELECT task FROM chat_models
                WHERE id = :id AND status = 'ready'
                """
            ),
            {"id": model_id},
        )
        task = model.scalar_one_or_none()
        if task is None:
            raise ValueError("The selected model is not available.")
        await connection.execute(
            text("UPDATE chat_models SET is_default = FALSE WHERE task = :task"),
            {"task": task},
        )
        await connection.execute(
            text(
                """
                UPDATE chat_models
                SET is_default = TRUE, updated_at = NOW()
                WHERE id = :id AND task = :task AND status = 'ready'
                """
            ),
            {"id": model_id, "task": task},
        )


async def get_default_model_for_task(task: str) -> str | None:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT model_name FROM chat_models
                WHERE task = :task AND status = 'ready'
                ORDER BY is_default DESC, created_at
                LIMIT 1
                """
            ),
            {"task": task},
        )
        return result.scalar_one_or_none()


async def get_default_model_settings(task: str) -> dict[str, str] | None:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT model_name, backend FROM chat_models
                WHERE task = :task AND status = 'ready'
                ORDER BY is_default DESC, created_at
                LIMIT 1
                """
            ),
            {"task": task},
        )
        row = result.mappings().one_or_none()
        return dict(row) if row else None


async def get_default_model_name() -> str | None:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text(
                """
                SELECT model_name
                FROM chat_models
                WHERE task = 'llm' AND status = 'ready'
                ORDER BY is_default DESC, created_at
                LIMIT 1
                """
            )
        )
        return result.scalar_one_or_none()


async def set_user_conversation_model(
    user_id: int, conversation_id: str, model_id: str
) -> None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        model = await connection.execute(
            text(
                """
                SELECT id
                FROM chat_models
                WHERE id = :model_id AND task = 'llm' AND status = 'ready'
                """
            ),
            {"model_id": model_id},
        )
        if model.scalar_one_or_none() is None:
            raise ValueError("The selected language model is not available.")

        await connection.execute(
            text(
                """
                INSERT INTO chat_user_conversations
                    (user_id, conversation_id, model_id)
                VALUES (:user_id, :conversation_id, :model_id)
                ON CONFLICT (user_id, conversation_id) DO UPDATE
                SET model_id = EXCLUDED.model_id, updated_at = NOW()
                """
            ),
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model_id": model_id,
            },
        )


async def get_user_conversation_model(
    user_id: int, conversation_id: str
) -> str | None:
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        result = await connection.execute(
            text(
                """
                SELECT model.model_name
                FROM chat_user_conversations AS conversation
                JOIN chat_models AS model ON model.id = conversation.model_id
                WHERE conversation.user_id = :user_id
                  AND conversation.conversation_id = :conversation_id
                  AND model.task = 'llm'
                  AND model.status = 'ready'
                """
            ),
            {"user_id": user_id, "conversation_id": conversation_id},
        )
        model_name = result.scalar_one_or_none()
        if model_name is not None:
            return model_name

        default_result = await connection.execute(
            text(
                """
                SELECT id, model_name
                FROM chat_models
                WHERE task = 'llm' AND status = 'ready'
                ORDER BY is_default DESC, created_at
                LIMIT 1
                """
            )
        )
        default_model = default_result.mappings().one_or_none()
        if default_model is None:
            return None

        await connection.execute(
            text(
                """
                INSERT INTO chat_user_conversations
                    (user_id, conversation_id, model_id)
                VALUES (:user_id, :conversation_id, :model_id)
                ON CONFLICT (user_id, conversation_id) DO UPDATE
                SET model_id = EXCLUDED.model_id, updated_at = NOW()
                """
            ),
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model_id": default_model["id"],
            },
        )
        return default_model["model_name"]
