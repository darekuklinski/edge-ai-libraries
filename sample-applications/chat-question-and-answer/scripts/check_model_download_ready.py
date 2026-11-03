#!/usr/bin/env python3
"""Healthcheck for completed ChatQnA OpenVINO model conversions."""

import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen


def main() -> int:
    model_names = {
        os.environ["LLM_MODEL"],
        os.environ["EMBEDDING_MODEL_NAME"],
    }
    repository = Path(os.environ["MODEL_REPOSITORY_PATH"])

    try:
        with urlopen("http://localhost:8000/jobs", timeout=10) as response:
            jobs = json.load(response).get("jobs", [])
    except Exception:
        return 1

    for model_name in model_names:
        conversions = [
            job
            for job in jobs
            if job.get("model_name") == model_name
            and job.get("operation_type") == "convert"
        ]
        if not conversions or any(job.get("status") != "completed" for job in conversions):
            return 1

    model_slug = os.environ["LLM_MODEL"].split("/")[-1]
    templates = [
        path
        for path in repository.rglob("chat_template.jinja")
        if model_slug in str(path)
    ]
    if not templates:
        return 1

    original = '{{- "<|start|>assistant" }}'
    final_channel = '{{- "<|start|>assistant<|channel|>final<|message|>" }}'
    for template in templates:
        content = template.read_text(encoding="utf-8")
        if original in content:
            template.write_text(content.replace(original, final_channel), encoding="utf-8")
        elif final_channel not in content:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())