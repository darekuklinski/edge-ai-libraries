# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import Mock

from app import model_lifecycle


def test_model_lease_acquires_and_releases(monkeypatch):
    monkeypatch.setenv("OVMS_MODEL_LIFECYCLE_ENABLED", "true")
    monkeypatch.setenv("MODEL_LIFECYCLE_URL", "http://chatqna:8080")
    monkeypatch.setenv("MODEL_DOWNLOAD_SERVICE_TOKEN", "a" * 40)
    calls = []

    def request(method, url, payload=None):
        calls.append((method, url, payload))

    monkeypatch.setattr(model_lifecycle, "_request", request)

    with model_lifecycle.model_lease("org/embedding"):
        assert len(calls) == 1
        assert calls[0][0:2] == (
            "POST",
            "http://chatqna:8080/internal/model-runtime/leases",
        )
        assert calls[0][2]["model_name"] == "org/embedding"
        lease_id = calls[0][2]["lease_id"]

    assert calls[1] == (
        "DELETE",
        f"http://chatqna:8080/internal/model-runtime/leases/{lease_id}",
        None,
    )


def test_model_lease_is_noop_when_lifecycle_is_disabled(monkeypatch):
    monkeypatch.setenv("OVMS_MODEL_LIFECYCLE_ENABLED", "false")
    request = Mock()
    monkeypatch.setattr(model_lifecycle, "_request", request)

    with model_lifecycle.model_lease("org/embedding"):
        pass
    request.assert_not_called()
