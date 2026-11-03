#!/usr/bin/env python3
"""Ensure config_all.json lists the downloaded ChatQnA models."""

import json
import os
from pathlib import Path


def main() -> None:
    repository = Path(os.environ["MODEL_REPOSITORY_PATH"]).resolve()
    model_names = [os.environ["LLM_MODEL"], os.environ["EMBEDDING_MODEL_NAME"]]
    entries = []

    for name in model_names:
        model_path = (repository / name).resolve()
        if not model_path.is_relative_to(repository) or not model_path.is_dir():
            raise FileNotFoundError(
                f"Downloaded model directory for {name!r} not found under {repository}"
            )
        entries.append(
            {"config": {"name": name, "base_path": model_path.relative_to(repository).as_posix()}}
        )

    config_path = repository / "config_all.json"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
        model_config_list = config.get("model_config_list")
        if not isinstance(model_config_list, list):
            raise ValueError(f"{config_path} must contain a model_config_list array")
    else:
        config = {"model_config_list": []}
        model_config_list = config["model_config_list"]

    requested_names = {entry["config"]["name"] for entry in entries}
    model_config_list[:] = [
        entry
        for entry in model_config_list
        if entry.get("config", {}).get("name") not in requested_names
    ]
    model_config_list.extend(entries)

    temporary_path = config_path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=4)
        config_file.write("\n")
    temporary_path.replace(config_path)
    print(f"Generated OVMS configuration at {config_path}")


if __name__ == "__main__":
    main()
