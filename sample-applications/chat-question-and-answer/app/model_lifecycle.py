# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import copy
import json
import logging
import os
import posixpath
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, AsyncIterator
from uuid import uuid4

import httpx


class ModelLifecycleError(RuntimeError):
    pass


class OVMSModelLifecycle:
    def __init__(
        self,
        config_source_path: str | None = None,
        active_config_path: str | None = None,
        ovms_rest_url: str | None = None,
        idle_seconds: float | None = None,
        enabled: bool | None = None,
    ):
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("OVMS_MODEL_LIFECYCLE_ENABLED", "false").lower()
            == "true"
        )
        self.config_source_path = Path(
            config_source_path or os.getenv("OVMS_CONFIG_SOURCE_PATH", "")
        )
        self.active_config_path = Path(
            active_config_path
            or os.getenv(
                "OVMS_ACTIVE_CONFIG_PATH",
                "/opt/models/config_active.json",
            )
        )
        self.ovms_rest_url = (
            ovms_rest_url or os.getenv("OVMS_REST_URL", "")
        ).rstrip("/")
        self.ovms_model_base_path = PurePosixPath(
            os.getenv("OVMS_MODEL_BASE_PATH", "/workspace/models")
        )
        self.idle_seconds = (
            idle_seconds
            if idle_seconds is not None
            else float(os.getenv("OVMS_MODEL_IDLE_SECONDS", "300"))
        )
        self.persistent_model_names = {
            model_name
            for model_name in [os.getenv("LLM_MODEL")]
            if model_name
        }
        self._lock = asyncio.Lock()
        self._leases: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._eviction_tasks: dict[str, asyncio.Task[None]] = {}

    @asynccontextmanager
    async def lease(self, model_name: str) -> AsyncIterator[None]:
        if not self.enabled:
            yield
            return

        lease_id = str(uuid4())
        await self.acquire(model_name, lease_id)
        try:
            yield
        finally:
            await self.release(lease_id)

    async def acquire(self, model_name: str, lease_id: str) -> None:
        if not self.enabled:
            return
        if not model_name or not lease_id:
            raise ValueError("A model name and lease ID are required")

        async with self._lock:
            leased_model = self._leases.get(lease_id)
            if leased_model:
                if leased_model != model_name:
                    raise ValueError("Lease ID is already assigned to another model")
                return

            eviction_task = self._eviction_tasks.pop(model_name, None)
            if eviction_task:
                eviction_task.cancel()

            active_names = self._read_active_model_names()
            if model_name not in active_names:
                self._validate_model_names(active_names | {model_name})
                try:
                    await self._set_active_models(active_names | {model_name})
                    await self._wait_until_ready(model_name)
                except ModelLifecycleError as load_error:
                    try:
                        await self._set_active_models(active_names)
                    except ModelLifecycleError as rollback_error:
                        logging.exception(
                            "Failed to restore OVMS config after model load failure"
                        )
                        raise ModelLifecycleError(
                            "OVMS model load failed and config rollback failed"
                        ) from rollback_error
                    raise load_error
            else:
                await self._wait_until_ready(model_name)

            self._leases[lease_id] = model_name
            self._counts[model_name] = self._counts.get(model_name, 0) + 1

    async def release(self, lease_id: str) -> None:
        if not self.enabled:
            return
        async with self._lock:
            model_name = self._leases.pop(lease_id, None)
            if model_name is None:
                raise ValueError("Unknown model lease")

            remaining = self._counts[model_name] - 1
            if remaining:
                self._counts[model_name] = remaining
                return

            del self._counts[model_name]
            if model_name in self.persistent_model_names:
                return

            self._eviction_tasks[model_name] = asyncio.create_task(
                self._evict_after_idle(model_name)
            )

    async def deactivate_model(self, model_name: str) -> bool:
        if not self.enabled:
            return True
        async with self._lock:
            if model_name in self.persistent_model_names or self._counts.get(
                model_name, 0
            ):
                return False
            eviction_task = self._eviction_tasks.pop(model_name, None)
            if eviction_task:
                eviction_task.cancel()
            active_names = self._read_active_model_names()
            if model_name not in active_names:
                return True
            await self._set_active_models(active_names - {model_name})
            return True

    async def _evict_after_idle(self, model_name: str) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
            async with self._lock:
                if self._counts.get(model_name, 0):
                    return
                active_names = self._read_active_model_names()
                if model_name in active_names:
                    await self._set_active_models(active_names - {model_name})
                self._eviction_tasks.pop(model_name, None)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, httpx.HTTPError, ModelLifecycleError):
            logging.exception("Failed to evict idle OVMS model %s", model_name)
            self._eviction_tasks.pop(model_name, None)

    def _read_json_config(self, path: Path) -> dict[str, Any]:
        try:
            with path.open(encoding="utf-8") as config_file:
                config = json.load(config_file)
        except (OSError, json.JSONDecodeError) as error:
            raise ModelLifecycleError(f"Cannot read OVMS config at {path}") from error
        if not isinstance(config, dict) or not isinstance(
            config.get("model_config_list"), list
        ):
            raise ModelLifecycleError(
                f"OVMS config at {path} must contain a model_config_list array"
            )
        return config

    def _read_active_model_names(self) -> set[str]:
        config = self._read_json_config(self.active_config_path)
        return {
            entry["config"]["name"]
            for entry in config["model_config_list"]
            if isinstance(entry, dict)
            and isinstance(entry.get("config"), dict)
            and isinstance(entry["config"].get("name"), str)
        }

    def _validate_model_names(self, model_names: set[str]) -> None:
        source = self._read_json_config(self.config_source_path)
        configured_names = {
            entry["config"]["name"]
            for entry in source["model_config_list"]
            if isinstance(entry, dict)
            and isinstance(entry.get("config"), dict)
            and isinstance(entry["config"].get("name"), str)
        }
        missing_names = model_names - configured_names
        if missing_names:
            raise ModelLifecycleError(
                "OVMS model configuration is missing: "
                + ", ".join(sorted(missing_names))
            )

    async def _set_active_models(self, model_names: set[str]) -> None:
        source = self._read_json_config(self.config_source_path)
        entries_by_name = {
            entry["config"]["name"]: entry
            for entry in source["model_config_list"]
            if isinstance(entry, dict)
            and isinstance(entry.get("config"), dict)
            and isinstance(entry["config"].get("name"), str)
        }
        missing_names = model_names - entries_by_name.keys()
        if missing_names:
            raise ModelLifecycleError(
                "OVMS model configuration is missing: "
                + ", ".join(sorted(missing_names))
            )

        active_config = dict(source)
        active_entries = []
        for name in sorted(model_names):
            entry = copy.deepcopy(entries_by_name[name])
            model_config = entry["config"]
            base_path = model_config.get("base_path")
            if not isinstance(base_path, str) or not base_path:
                raise ModelLifecycleError(
                    f"OVMS model {name!r} has no configured base_path"
                )
            relative_path = PurePosixPath(base_path)
            if relative_path.is_absolute():
                model_config["base_path"] = str(relative_path)
            else:
                if ".." in relative_path.parts:
                    raise ModelLifecycleError(
                        f"OVMS model {name!r} has an unsafe base_path"
                    )
                model_config["base_path"] = posixpath.join(
                    str(self.ovms_model_base_path), str(relative_path)
                )
            active_entries.append(entry)
        active_config["model_config_list"] = active_entries
        try:
            self.active_config_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.active_config_path.parent,
                prefix=f".{self.active_config_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as config_file:
                json.dump(active_config, config_file, indent=2)
                config_file.write("\n")
                temporary_path = Path(config_file.name)
            temporary_path.chmod(0o644)
            temporary_path.replace(self.active_config_path)
        except OSError as error:
            raise ModelLifecycleError(
                f"Cannot write active OVMS config at {self.active_config_path}"
            ) from error

        try:
            async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
                response = await client.post(f"{self.ovms_rest_url}/v1/config/reload")
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise ModelLifecycleError("OVMS configuration reload failed") from error

    async def _wait_until_ready(self, model_name: str) -> None:
        deadline = time.monotonic() + 120
        status_url = f"{self.ovms_rest_url}/v1/config"
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = await client.get(status_url)
                    if response.status_code == 200 and self._response_is_ready(
                        response.json(), model_name
                    ):
                        return
                except (httpx.HTTPError, ValueError):
                    logging.debug("Waiting for OVMS model %s to become ready", model_name)
                await asyncio.sleep(1)
        raise ModelLifecycleError(
            f"OVMS model {model_name!r} did not become ready within 120 seconds"
        )

    @staticmethod
    def _response_is_ready(response: Any, model_name: str) -> bool:
        if not isinstance(response, dict) or not isinstance(
            response.get(model_name), dict
        ):
            return False
        model_status = response[model_name]
        version_statuses = model_status.get("model_version_status", [])
        if isinstance(version_statuses, list):
            states = [
                status.get("state")
                for status in version_statuses
                if isinstance(status, dict)
            ]
            return any(
                isinstance(state, str) and state.upper() == "AVAILABLE"
                for state in states
            )
        return False


model_lifecycle = OVMSModelLifecycle()
