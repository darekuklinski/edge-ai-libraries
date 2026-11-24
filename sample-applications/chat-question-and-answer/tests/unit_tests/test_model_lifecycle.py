# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json

import pytest

from app.model_lifecycle import ModelLifecycleError, OVMSModelLifecycle


def _write_config(path, model_names):
    path.write_text(
        json.dumps(
            {
                "model_config_list": [
                    {"config": {"name": name, "base_path": name}}
                    for name in model_names
                ]
            }
        ),
        encoding="utf-8",
    )


def _manager(tmp_path, monkeypatch, idle_seconds=0.01):
    source = tmp_path / "config_all.json"
    active = tmp_path / "config_active.json"
    _write_config(source, ["llm", "embedding", "reranker"])
    _write_config(active, ["llm"])
    monkeypatch.setenv("LLM_MODEL", "llm")
    manager = OVMSModelLifecycle(
        str(source),
        str(active),
        "http://ovms:8080",
        idle_seconds=idle_seconds,
        enabled=True,
    )

    async def set_active(model_names):
        _write_config(active, sorted(model_names))

    async def wait_until_ready(_model_name):
        return None

    manager._set_active_models = set_active
    manager._wait_until_ready = wait_until_ready
    return manager, active


def _active_model_names(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    return {entry["config"]["name"] for entry in config["model_config_list"]}


def test_model_lease_loads_then_evicts_after_idle(tmp_path, monkeypatch):
    manager, active = _manager(tmp_path, monkeypatch)

    async def run():
        await manager.acquire("embedding", "lease-1")
        assert _active_model_names(active) == {"llm", "embedding"}
        await manager.release("lease-1")
        await asyncio.sleep(0.03)

    asyncio.run(run())
    assert _active_model_names(active) == {"llm"}


def test_model_remains_loaded_while_another_lease_is_active(
    tmp_path, monkeypatch
):
    manager, active = _manager(tmp_path, monkeypatch)

    async def run():
        await manager.acquire("embedding", "lease-1")
        await manager.acquire("embedding", "lease-2")
        await manager.release("lease-1")
        await asyncio.sleep(0.03)
        assert _active_model_names(active) == {"llm", "embedding"}
        await manager.release("lease-2")
        await asyncio.sleep(0.03)

    asyncio.run(run())
    assert _active_model_names(active) == {"llm"}


def test_persistent_model_is_not_evicted(tmp_path, monkeypatch):
    manager, active = _manager(tmp_path, monkeypatch)

    async def run():
        await manager.acquire("llm", "lease-1")
        await manager.release("lease-1")
        await asyncio.sleep(0.03)

    asyncio.run(run())
    assert _active_model_names(active) == {"llm"}


def test_acquire_rejects_models_missing_from_downloaded_config(
    tmp_path, monkeypatch
):
    source = tmp_path / "config_all.json"
    active = tmp_path / "config_active.json"
    _write_config(source, ["llm", "embedding"])
    _write_config(active, ["llm"])
    monkeypatch.setenv("LLM_MODEL", "llm")
    manager = OVMSModelLifecycle(
        str(source),
        str(active),
        "http://ovms:8080",
        enabled=True,
    )

    with pytest.raises(ModelLifecycleError, match="missing"):
        asyncio.run(manager.acquire("unknown-model", "lease-1"))


def test_model_config_status_detects_available_ovms_version():
    response = {
        "org/embedding": {
            "model_version_status": [{"version": "1", "state": "AVAILABLE"}]
        }
    }

    assert OVMSModelLifecycle._response_is_ready(response, "org/embedding")
    assert not OVMSModelLifecycle._response_is_ready(
        {"org/embedding": {"model_version_status": [{"state": "LOADING"}]}},
        "org/embedding",
    )


def test_runtime_config_uses_ovms_model_mount_paths(
    tmp_path, monkeypatch
):
    source = tmp_path / "config_all.json"
    active = tmp_path / "config_active.json"
    _write_config(source, ["llm", "embedding"])
    _write_config(active, ["llm"])
    manager = OVMSModelLifecycle(
        str(source),
        str(active),
        "http://ovms:8080",
        enabled=True,
    )
    reload_requests = []

    class Response:
        def raise_for_status(self):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url):
            reload_requests.append(url)
            return Response()

    monkeypatch.setattr(
        "app.model_lifecycle.httpx.AsyncClient",
        lambda **_kwargs: Client(),
    )

    asyncio.run(manager._set_active_models({"llm", "embedding"}))
    config = json.loads(active.read_text(encoding="utf-8"))
    assert {
        entry["config"]["base_path"]
        for entry in config["model_config_list"]
    } == {"/workspace/models/llm", "/workspace/models/embedding"}
    assert reload_requests == ["http://ovms:8080/v1/config/reload"]
