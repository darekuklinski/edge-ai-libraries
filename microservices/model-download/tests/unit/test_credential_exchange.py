# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet

from src.core.credential_exchange import (
    CredentialExchangeError,
    fetch_user_huggingface_token,
)


@pytest.mark.asyncio
async def test_fetch_user_token_authenticates_and_decrypts_response(monkeypatch):
    key = Fernet.generate_key()
    encrypted_token = Fernet(key).encrypt(b"hf_private-token").decode("ascii")
    request_mock = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"encrypted_token": encrypted_token},
            request=httpx.Request("GET", "http://chatqna/internal/token"),
        )
    )

    class MockClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        get = request_mock

    monkeypatch.setattr("src.core.credential_exchange.httpx.AsyncClient", MockClient)
    monkeypatch.setenv("CHATQNA_TOKEN_EXCHANGE_URL", "http://chatqna:8080/")
    service_token = "s" * 48
    monkeypatch.setenv("MODEL_DOWNLOAD_SERVICE_TOKEN", service_token)
    monkeypatch.setenv("MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY", key.decode("ascii"))

    assert await fetch_user_huggingface_token(42) == "hf_private-token"
    request_mock.assert_awaited_once_with(
        "http://chatqna:8080/internal/model-download/users/42/huggingface-token",
        headers={"Authorization": f"Bearer {service_token}"},
    )


@pytest.mark.asyncio
async def test_fetch_user_token_rejects_tampered_ciphertext(monkeypatch):
    class MockClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return httpx.Response(
                200,
                json={"encrypted_token": "tampered"},
                request=httpx.Request("GET", "http://chatqna/internal/token"),
            )

    monkeypatch.setattr("src.core.credential_exchange.httpx.AsyncClient", MockClient)
    monkeypatch.setenv("CHATQNA_TOKEN_EXCHANGE_URL", "http://chatqna:8080")
    monkeypatch.setenv("MODEL_DOWNLOAD_SERVICE_TOKEN", "s" * 48)
    monkeypatch.setenv(
        "MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY",
        Fernet.generate_key().decode("ascii"),
    )

    with pytest.raises(CredentialExchangeError, match="invalid encrypted credential"):
        await fetch_user_huggingface_token(42)
