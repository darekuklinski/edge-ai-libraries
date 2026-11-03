#!/usr/bin/env python3
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Stream Intel GPU engine busy percentages from intel_gpu_top to Telegraf."""

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from json import JSONDecodeError
from pathlib import Path
from typing import Any, TextIO

HOSTNAME = os.environ.get("METRICS_MANAGER_HOSTNAME") or os.uname()[1]
DRM_DEVICE_DIR = Path("/dev/dri")
SAMPLE_INTERVAL_MS = 1000
RETRY_DELAY_S = 10
DEVICE_SCAN_INTERVAL_S = 10
MISSING_TOOL_RETRY_S = 60
STOP = threading.Event()
PRINT_LOCK = threading.Lock()
logger = logging.getLogger("intel_gpu_top_reader")
logging.basicConfig(stream=sys.stderr, level=logging.INFO)


def iter_json_objects(stream: TextIO) -> Iterator[dict[str, Any]]:
    """Decode intel_gpu_top's streamed JSON array one sample at a time."""
    decoder = json.JSONDecoder()
    buffer = ""
    for line in stream:
        buffer += line
        while buffer:
            buffer = buffer.lstrip()
            if not buffer:
                break
            if buffer[0] in "[,":
                buffer = buffer[1:]
                continue
            if buffer[0] == "]":
                return
            try:
                value, end = decoder.raw_decode(buffer)
            except JSONDecodeError:
                break
            buffer = buffer[end:]
            if isinstance(value, dict):
                yield value


def extract_engine_busy(sample: dict[str, Any]) -> list[tuple[str, float]]:
    """Return valid engine name/busy-percent pairs from one JSON sample."""
    engines = sample.get("engines")
    if not isinstance(engines, dict):
        return []

    values = []
    for name, stats in engines.items():
        if not isinstance(name, str) or not isinstance(stats, dict):
            continue
        busy = stats.get("busy")
        if isinstance(busy, bool) or not isinstance(busy, (int, float)):
            continue
        busy_percent = float(busy)
        if not math.isfinite(busy_percent):
            continue
        values.append((name, min(100.0, max(0.0, busy_percent))))
    return values


def escape_tag(value: str) -> str:
    return re.sub(r"([\\ ,=])", r"\\\1", value)


def emit_engine_busy(
    engine_values: list[tuple[str, float]], gpu_id: int, timestamp_ns: int
) -> None:
    for engine, busy_percent in engine_values:
        line = (
            f"intel_gpu_engine,engine={escape_tag(engine)},"
            f"host={escape_tag(HOSTNAME)},gpu_id={gpu_id} "
            f"busy_percent={busy_percent:.2f} {timestamp_ns}"
        )
        with PRINT_LOCK:
            print(line, flush=True)


def discover_cards() -> list[tuple[int, Path]]:
    """Find DRM card devices without accidentally selecting render nodes."""
    cards = []
    for path in DRM_DEVICE_DIR.glob("card[0-9]*"):
        match = re.fullmatch(r"card(\d+)", path.name)
        if match and path.exists():
            cards.append((int(match.group(1)), path))
    return sorted(cards)


def monitor_card(gpu_id: int, card_path: Path) -> None:
    command = [
        "intel_gpu_top",
        "-J",
        "-s",
        str(SAMPLE_INTERVAL_MS),
        "-o",
        "-",
        "-d",
        f"drm:{card_path}",
    ]
    while not STOP.is_set():
        try:
            with subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            ) as process:
                if process.stdout is None:
                    raise RuntimeError("intel_gpu_top stdout pipe was not created")
                for sample in iter_json_objects(process.stdout):
                    emit_engine_busy(
                        extract_engine_busy(sample), gpu_id, time.time_ns()
                    )
                    if STOP.is_set():
                        break
                if process.poll() is None:
                    process.terminate()
                process.wait()
                if not STOP.is_set():
                    logger.warning(
                        "intel_gpu_top stopped for %s (exit code %s); retrying",
                        card_path,
                        process.returncode,
                    )
        except FileNotFoundError:
            logger.error("intel_gpu_top is not installed; GPU busy metrics unavailable")
            return
        except OSError:
            logger.exception("Could not run intel_gpu_top for %s", card_path)
        if not STOP.is_set():
            STOP.wait(RETRY_DELAY_S)


def main() -> None:
    """Start one intel_gpu_top reader for each visible DRM card."""
    threads: dict[Path, threading.Thread] = {}
    try:
        while not STOP.is_set():
            if shutil.which("intel_gpu_top") is None:
                logger.error("intel_gpu_top is not installed; GPU busy metrics unavailable")
                STOP.wait(MISSING_TOOL_RETRY_S)
                continue
            for gpu_id, card_path in discover_cards():
                thread = threads.get(card_path)
                if thread is None or not thread.is_alive():
                    thread = threading.Thread(
                        target=monitor_card,
                        args=(gpu_id, card_path),
                        daemon=True,
                    )
                    threads[card_path] = thread
                    thread.start()
            STOP.wait(DEVICE_SCAN_INTERVAL_S)
    except KeyboardInterrupt:
        STOP.set()
        for thread in threads.values():
            thread.join(timeout=RETRY_DELAY_S + 1)


if __name__ == "__main__":
    main()
