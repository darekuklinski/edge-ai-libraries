#!/usr/bin/env python3
"""Create an OVMS startup config with only the default LLM eagerly loaded."""

import copy
import json
import os
import posixpath
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


def _read_model_entries(config_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    with config_path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict) or not isinstance(
        config.get("model_config_list"), list
    ):
        raise ValueError(f"{config_path} must contain a model_config_list array")

    entries = {}
    for entry in config["model_config_list"]:
        model_config = entry.get("config") if isinstance(entry, dict) else None
        name = model_config.get("name") if isinstance(model_config, dict) else None
        if isinstance(name, str):
            entries[name] = entry
    return config, entries


def main() -> None:
    repository = Path(os.environ["MODEL_REPOSITORY_PATH"]).resolve()
    runtime_config_dir = Path(os.environ["OVMS_RUNTIME_CONFIG_DIR"])
    startup_model = os.environ["LLM_MODEL"]
    lazy_models = {
        os.environ["EMBEDDING_MODEL_NAME"],
        os.environ["RERANKER_MODEL"],
    }

    config, model_entries = _read_model_entries(repository / "config_all.json")
    missing_models = ({startup_model} | lazy_models) - model_entries.keys()
    if missing_models:
        raise FileNotFoundError(
            "OVMS startup configuration is missing downloaded model(s): "
            + ", ".join(sorted(missing_models))
        )

    startup_entry = copy.deepcopy(model_entries[startup_model])
    model_config = startup_entry["config"]
    relative_path = PurePosixPath(model_config["base_path"])
    if relative_path.is_absolute():
        model_config["base_path"] = str(relative_path)
    else:
        if ".." in relative_path.parts:
            raise ValueError(f"Unsafe base_path for model {startup_model!r}")
        model_config["base_path"] = posixpath.join(
            "/workspace/models", str(relative_path)
        )
    config["model_config_list"] = [startup_entry]
    runtime_config_dir.mkdir(parents=True, exist_ok=True)
    runtime_config_dir.chmod(0o777)
    runtime_config_path = runtime_config_dir / "config_active.json"
    temporary_path = runtime_config_path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")
    temporary_path.chmod(0o644)
    temporary_path.replace(runtime_config_path)
    print(f"Generated OVMS runtime configuration at {runtime_config_path}")


if __name__ == "__main__":
    main()
