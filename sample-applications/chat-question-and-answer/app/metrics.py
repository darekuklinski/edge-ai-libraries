import asyncio
import inspect
import json
import logging
import os
import time
import psutil
import subprocess

from urllib.request import urlopen
from urllib.error import URLError
from functools import wraps
from datetime import datetime
from collections import deque
from typing import Dict, List, AsyncGenerator, Any


class SystemMonitor:
    def __init__(self):
        self.timestamp = deque(maxlen=100)
        self.cpu_usage_history = deque(maxlen=100)
        self.ram_usage_history = deque(maxlen=100)
        self.gpu_usage_history = deque(maxlen=100)
        self.npu_usage_history = deque(maxlen=100)
        self.endpoint = os.getenv("METRICS_ENDPOINT") or "http://metrics-manager:9090/metrics/stream"

    def _download_metrics(self) -> None:
        self.result = []

        try:
            with urlopen(self.endpoint, timeout=5) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()

                    # Ignore SSE comments and empty lines
                    if not line or line.startswith(":"):
                        continue

                    if line.startswith("data:"):
                        payload = json.loads(line.removeprefix("data:").strip())
                        self.result = payload.get("metrics", [])
                        return  # One snapshot is enough

        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logging.warning("Failed to download metrics: %s", exc)


    def _get_metric(
    self,
    search_query: str,
    source_metric: str | None = None,
    search_string: bool = False,
    ) -> str | None:
        for metric in self.result:
            if search_query not in metric.get("name", ""):
                continue
            if source_metric is not None:
                labels = metric.get("labels", {})
                if source_metric not in labels.values():
                    continue
            if search_string:
                return metric["name"]
            try:
                return f"{float(metric['value']):.2f}"
            except (ValueError, TypeError, KeyError):
                continue
        return None

    def _check_for_gpu_generation(self) -> str:
        generation = self._get_metric("intel", search_string=True)
        return "old" if generation is not None else "new"


    def get_cpu_usage(self) -> float | str:
        idle = self._get_metric("cpu_usage_idle")

        return 100 - float(idle) if idle is not None else "N/A"


    def get_ram_usage_in_percent(self) -> str:
        mem_percent = self._get_metric("mem_used_percent")
        return mem_percent if mem_percent is not None else "N/A"


    def get_ram_usage_in_gb(self) -> str:
        total = self._get_metric("mem_total")
        used = self._get_metric("mem_used")

        return f"{float(used) / (1024 ** 3):.2f}/{float(total) / (1024 ** 3):.2f}" if total is not None and used is not None else "N/A"


    def get_gpu_usage(self) -> dict[str, str]:
        old_search_query = "intel_gpu_engine_busy_percent"
        new_search_query = "gpu_engine_usage_usage{engine"
        old_metrics = ["Blitter", "Compute", "Render/3D", "Video", "VideoEnhance"]
        new_metrics = ["bcs", "ccs", "rcs", "vcs", "vecs"]
        metrics = {}

        generation = self._check_for_gpu_generation()

        match generation:
            case "old":
                search_query = old_search_query
                source_metrics = old_metrics

            case "new":
                search_query = new_search_query
                source_metrics = new_metrics

        for source_metric, target_metric in zip(source_metrics, new_metrics):
            gpu_stats = self._get_metric(search_query, source_metric)
            metrics[target_metric] = float(gpu_stats) if gpu_stats is not None else "N/A"

        return {"bcs": f"{metrics['bcs']}", "ccs": f"{metrics['ccs']}", "rcs": f"{metrics['rcs']}", "vcs": f"{metrics['vcs']}", "vecs": f"{metrics['vecs']}"}
        
    def get_npu_usage(self) -> str:
            npu_stats = self._get_metric("npu_usage_percent")
            return npu_stats if npu_stats is not None else "N/A"

    async def return_all(self, ram_type: str = "percent"):
        while True:
            try:
                self._download_metrics()
                data = {
                "timestamp": datetime.now().isoformat(),
                "cpu": self.get_cpu_usage(),
                "gpu": self.get_gpu_usage(),
                "npu": self.get_npu_usage(),
                "ram": (
                    self.get_ram_usage_in_gb()
                    if ram_type == "gb"
                    else self.get_ram_usage_in_percent()
                ),
            }
                yield f"data: {json.dumps(data)}\n\n"
            finally:
                await asyncio.sleep(1)

