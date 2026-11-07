# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import os

import httpx
from cryptography.fernet import Fernet, InvalidToken


class CredentialExchangeError(RuntimeError):
    """Raised when a user credential cannot be exchanged securely."""


async def fetch_user_huggingface_token(user_id: int) -> str:
    base_url = os.getenv("CHATQNA_TOKEN_EXCHANGE_URL", "").rstrip("/")
    service_token = os.getenv("MODEL_DOWNLOAD_SERVICE_TOKEN")
    encryption_key = os.getenv("MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY")
    if (
        not base_url
        or not service_token
        or len(service_token) < 32
        or not service_token.isascii()
        or not encryption_key
    ):
        raise CredentialExchangeError(
            "The ChatQnA credential exchange is not configured."
        )

    try:
        cipher = Fernet(encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise CredentialExchangeError(
            "The credential exchange encryption key is invalid."
        ) from error

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(
                (
                    f"{base_url}/internal/model-download/users/{user_id}"
                    "/huggingface-token"
                ),
                headers={"Authorization": f"Bearer {service_token}"},
            )
    except httpx.RequestError as error:
        raise CredentialExchangeError(
            "ChatQnA is unavailable for credential exchange."
        ) from error

    if response.status_code == 404:
        raise CredentialExchangeError(
            "The user has not configured a Hugging Face token."
        )
    if response.status_code != 200:
        raise CredentialExchangeError(
            f"ChatQnA credential exchange failed with status {response.status_code}."
        )

    try:
        encrypted_token = response.json()["encrypted_token"]
        if not isinstance(encrypted_token, str):
            raise TypeError("Encrypted token must be a string")
        return cipher.decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, InvalidToken) as error:
        raise CredentialExchangeError(
            "ChatQnA returned an invalid encrypted credential."
        ) from error
