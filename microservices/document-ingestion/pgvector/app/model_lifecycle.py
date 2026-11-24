# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import json
import os
from contextlib import contextmanager
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4


class ModelLifecycleRequestError(RuntimeError):
    pass


def _request(method: str, url: str, payload: dict | None = None) -> None:
    service_token = os.getenv("MODEL_DOWNLOAD_SERVICE_TOKEN", "")
    if len(service_token) < 32 or not service_token.isascii():
        raise ModelLifecycleRequestError(
            "Model lifecycle service authentication is not configured"
        )

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {service_token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=300):
            return
    except HTTPError as error:
        raise ModelLifecycleRequestError(
            f"Model lifecycle service returned HTTP {error.code}"
        ) from error
    except (TimeoutError, URLError) as error:
        raise ModelLifecycleRequestError(
            "Model lifecycle service is unavailable"
        ) from error


@contextmanager
def model_lease(model_name: str) -> Iterator[None]:
    if os.getenv("OVMS_MODEL_LIFECYCLE_ENABLED", "false").lower() != "true":
        yield
        return

    lifecycle_url = os.getenv("MODEL_LIFECYCLE_URL", "").rstrip("/")
    if not lifecycle_url:
        raise ModelLifecycleRequestError(
            "Model lifecycle service URL is not configured"
        )

    lease_id = str(uuid4())
    _request(
        "POST",
        f"{lifecycle_url}/internal/model-runtime/leases",
        {"model_name": model_name, "lease_id": lease_id},
    )
    try:
        yield
    finally:
        _request(
            "DELETE",
            f"{lifecycle_url}/internal/model-runtime/leases/{quote(lease_id, safe='')}",
        )
