import asyncio
from contextlib import asynccontextmanager

import app.account_store as account_store
from app.account_store import (
    HFTokenEncryptionUnavailable,
    ServiceSetupIncomplete,
    _hash_huggingface_token,
    _hash_password,
    _is_well_formed_password_hash,
    _merge_duplicate_installed_models,
    _merge_installed_model_placeholders,
    _hf_token_cipher,
    encrypt_model_download_token,
    _hash_session_token,
    _verify_password,
    ensure_service_setup,
)
from cryptography.fernet import Fernet


def test_ensure_tables_reconciles_configured_model_placeholders(monkeypatch):
    calls = []

    class FakeConnection:
        async def execute(self, statement, params=None):
            calls.append((str(statement), params))

    class FakeConnectionContext:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class FakeEngine:
        def begin(self):
            return FakeConnectionContext()

    async def record_duplicate_merge(connection):
        calls.append(("merge duplicates", None))

    async def record_placeholder_merge(connection):
        calls.append(("merge placeholders", None))

    monkeypatch.setattr(account_store, "_tables_ready", False)
    monkeypatch.setattr(account_store, "_get_engine", lambda: FakeEngine())
    monkeypatch.setattr(
        account_store, "_merge_duplicate_installed_models", record_duplicate_merge
    )
    monkeypatch.setattr(
        account_store, "_merge_installed_model_placeholders", record_placeholder_merge
    )
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "")
    monkeypatch.setenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-2-v2")

    asyncio.run(account_store._ensure_tables())

    configured_model_inserts = [
        params
        for statement, params in calls
        if "INSERT INTO chat_models" in statement
    ]
    assert configured_model_inserts == [
        {
            "model_id": "cross-encoder/ms-marco-MiniLM-L-2-v2",
            "model_name": "cross-encoder/ms-marco-MiniLM-L-2-v2",
            "display_name": "ms-marco-MiniLM-L-2-v2",
            "task": "reranker",
            "backend": "tei",
            "is_default": False,
        }
    ]
    assert any("ADD COLUMN IF NOT EXISTS role TEXT" in statement for statement, _ in calls)
    assert any(
        "SET role = 'admin'" in statement and "WHERE username = 'admin'" in statement
        for statement, _ in calls
    )
    assert calls[-2:] == [("merge duplicates", None), ("merge placeholders", None)]


def test_last_administrator_cannot_be_downgraded(monkeypatch):
    class Result:
        def mappings(self):
            return self

        def one_or_none(self):
            return {"id": 2, "username": "admin", "role": "admin"}

        def scalar_one(self):
            return 1

    class FakeConnection:
        async def execute(self, statement, params=None):
            return Result()

    class ConnectionContext:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class FakeEngine:
        def begin(self):
            return ConnectionContext()

    async def ensure_tables():
        return None

    monkeypatch.setattr(account_store, "_ensure_tables", ensure_tables)
    monkeypatch.setattr(account_store, "_get_engine", lambda: FakeEngine())

    try:
        asyncio.run(account_store.set_account_role(2, "standard", actor_user_id=1))
    except ValueError as error:
        assert "At least one administrator" in str(error)
    else:
        raise AssertionError("Expected the last administrator to be protected")


def test_duplicate_installed_artifacts_keep_precision_and_default_metadata():
    models = [
        {
            "id": "tiny|llm|CPU|int4",
            "model_name": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            "task": "llm",
            "artifact_location": "openvino_models/cpu/int4/TinyLlama/model",
            "is_default": False,
            "metadata": {"precision": "int4"},
        },
        {
            "id": "tiny|llm|CPU|",
            "model_name": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            "task": "llm",
            "artifact_location": "openvino_models/cpu/int4/TinyLlama/model",
            "is_default": True,
            "metadata": {"precision": None},
        },
    ]

    class Result:
        def mappings(self):
            return self

        def all(self):
            return models

    class FakeConnection:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.calls.append((sql, params))
            return Result()

    connection = FakeConnection()
    asyncio.run(_merge_duplicate_installed_models(connection))

    assert any(
        "SET is_default = TRUE" in sql
        and params == {"installed_id": "tiny|llm|CPU|int4"}
        for sql, params in connection.calls
    )
    assert any(
        "SET model_id = :installed_id" in sql
        and params == {
            "installed_id": "tiny|llm|CPU|int4",
            "duplicate_id": "tiny|llm|CPU|",
        }
        for sql, params in connection.calls
    )
    assert any(
        "DELETE FROM chat_models" in sql
        and params == {"duplicate_id": "tiny|llm|CPU|"}
        for sql, params in connection.calls
    )


def test_installed_models_replace_configured_placeholders_and_preserve_defaults():
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    placeholders = [
        {
            "id": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            "model_name": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            "task": "llm",
            "is_default": True,
        },
        {
            "id": "BAAI/bge-base-en-v1.5",
            "model_name": "BAAI/bge-base-en-v1.5",
            "task": "embedding",
            "is_default": False,
        },
    ]
    installed = {
        ("TinyLlama/TinyLlama-1.1B-Chat-v1.0", "llm"): [
            {"id": "tiny|llm|CPU|int4", "is_default": False}
        ],
        ("BAAI/bge-base-en-v1.5", "embedding"): [
            {"id": "bge|embedding|CPU|int8", "is_default": False}
        ],
    }

    class FakeConnection:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.calls.append((sql, params))
            if "SELECT id, model_name, task, is_default" in sql:
                return Result(placeholders)
            if "SELECT id, is_default" in sql:
                key = (params["model_name"], params["task"])
                return Result(installed[key])
            return Result([])

    connection = FakeConnection()
    asyncio.run(_merge_installed_model_placeholders(connection))

    updates = [(sql, params) for sql, params in connection.calls if "UPDATE " in sql]
    deletes = [(sql, params) for sql, params in connection.calls if "DELETE " in sql]
    assert any(
        "SET is_default = TRUE" in sql and params == {"installed_id": "tiny|llm|CPU|int4"}
        for sql, params in updates
    )
    assert any(
        "SET model_id = :installed_id" in sql
        and params == {
            "installed_id": "tiny|llm|CPU|int4",
            "placeholder_id": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        }
        for sql, params in updates
    )
    assert {params["placeholder_id"] for _, params in deletes} == {
        "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        "BAAI/bge-base-en-v1.5",
    }


def test_password_hash_is_salted_and_verifiable():
    first_hash = _hash_password("test-password")
    second_hash = _hash_password("test-password")

    assert first_hash != second_hash
    assert _verify_password("test-password", first_hash)
    assert not _verify_password("wrong-password", first_hash)
    assert _is_well_formed_password_hash(first_hash)
    assert not _is_well_formed_password_hash("invalid")


def test_session_token_is_stored_as_a_one_way_hash():
    token = "random-session-token"

    assert _hash_session_token(token) != token
    assert _hash_session_token(token) == _hash_session_token(token)


def test_huggingface_token_is_hashed_and_encrypted(monkeypatch):
    token = "hf_high-entropy-example"
    monkeypatch.setenv(
        "HF_TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )

    encrypted = _hf_token_cipher().encrypt(token.encode("utf-8"))

    assert _hash_huggingface_token(token) != token
    assert encrypted.decode("ascii") != token
    assert _hf_token_cipher().decrypt(encrypted).decode("utf-8") == token


def test_huggingface_token_cipher_requires_a_configured_key(monkeypatch):
    monkeypatch.delenv("HF_TOKEN_ENCRYPTION_KEY", raising=False)

    try:
        _hf_token_cipher()
    except HFTokenEncryptionUnavailable as error:
        assert "must be configured" in str(error)
    else:
        raise AssertionError("Expected encryption configuration to be required")


def test_model_download_token_exchange_uses_separate_encryption_key(monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv("MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY", key.decode("ascii"))

    encrypted = encrypt_model_download_token("hf_exchange-token")

    assert Fernet(key).decrypt(encrypted.encode("ascii")).decode() == "hf_exchange-token"
    assert encrypted != "hf_exchange-token"


def test_model_download_token_exchange_requires_a_configured_key(monkeypatch):
    monkeypatch.delenv("MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY", raising=False)

    try:
        encrypt_model_download_token("hf_exchange-token")
    except HFTokenEncryptionUnavailable as error:
        assert "must be configured" in str(error)
    else:
        raise AssertionError("Expected exchange encryption configuration to be required")


def test_service_setup_blocks_default_admin_until_configured_password(
    monkeypatch, mocker
):
    class Result:
        def __init__(self, value=None):
            self.value = value

        def scalar_one(self):
            return self.value

        def mappings(self):
            return self

        def one_or_none(self):
            return self.value

    class FakeConnection:
        def __init__(self):
            self.initialized = False
            self.admin = {"id": 1, "password_hash": _hash_password("admin")}

        async def execute(self, statement, params=None):
            sql = str(statement)
            if "SELECT initialized" in sql:
                return Result(self.initialized)
            if "SELECT id, password_hash" in sql:
                return Result(self.admin)
            if "UPDATE chat_users" in sql:
                self.admin["password_hash"] = params["password_hash"]
            elif "INSERT INTO chat_users" in sql:
                self.admin = {"id": 1, "password_hash": params["password_hash"]}
            elif "UPDATE chat_service_setup" in sql:
                self.initialized = True
            return Result()

    connection = FakeConnection()

    class FakeEngine:
        @asynccontextmanager
        async def begin(self):
            yield connection

    mocker.patch("app.account_store._ensure_tables", new_callable=mocker.AsyncMock)
    mocker.patch("app.account_store._get_engine", return_value=FakeEngine())
    monkeypatch.delenv("CHATQNA_ADMIN_PASSWORD", raising=False)

    try:
        asyncio.run(ensure_service_setup())
    except ServiceSetupIncomplete:
        pass
    else:
        raise AssertionError("Expected default admin credentials to require setup")
    assert not connection.initialized

    monkeypatch.setenv("CHATQNA_ADMIN_PASSWORD", "configured-admin-password")
    asyncio.run(ensure_service_setup())

    assert connection.initialized
    assert not _verify_password("admin", connection.admin["password_hash"])
    assert _verify_password(
        "configured-admin-password", connection.admin["password_hash"]
    )
