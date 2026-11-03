# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import io
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
READER_PATH = PROJECT_ROOT / "scripts" / "intel_gpu_top_reader.py"
TELEGRAF_CONF = PROJECT_ROOT / "telegraf.conf"


def load_reader():
    spec = importlib.util.spec_from_file_location(
        "intel_gpu_top_reader_under_test", READER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_iter_json_objects_reads_streamed_samples():
    reader = load_reader()
    output = io.StringIO(
        '[\n'
        '  {\n'
        '    "engines": {\n'
        '      "Render/3D": {\n'
        '        "busy": 12.5,\n'
        '        "unit": "%"\n'
        '      }\n'
        '    }\n'
        '  },\n'
        '  {\n'
        '    "engines": {\n'
        '      "Video": {\n'
        '        "busy": 0.0,\n'
        '        "unit": "%"\n'
        '      }\n'
        '    }\n'
        '  }\n'
        ']\n'
    )

    assert list(reader.iter_json_objects(output)) == [
        {"engines": {"Render/3D": {"busy": 12.5, "unit": "%"}}},
        {"engines": {"Video": {"busy": 0.0, "unit": "%"}}},
    ]


def test_extract_engine_busy_ignores_non_numeric_values():
    reader = load_reader()
    sample = {
        "engines": {
            "Render/3D": {"busy": 12.5},
            "Blitter": {"busy": 0.0},
            "Video": {"busy": "--"},
            "Compute": {"busy": float("nan")},
            "invalid": None,
        }
    }

    assert reader.extract_engine_busy(sample) == [
        ("Render/3D", 12.5),
        ("Blitter", 0.0),
    ]


def test_extract_engine_busy_clamps_values_to_percentage_range():
    reader = load_reader()

    assert reader.extract_engine_busy(
        {"engines": {"low": {"busy": -1}, "high": {"busy": 101}}}
    ) == [("low", 0.0), ("high", 100.0)]


def test_emits_busy_percent_in_influx_line_protocol(capsys):
    reader = load_reader()
    with patch.object(reader, "HOSTNAME", "test host"):
        reader.emit_engine_busy([("Render/3D", 12.5)], 1, 123456789)

    assert capsys.readouterr().out == (
        "intel_gpu_engine,engine=Render/3D,host=test\\ host,gpu_id=1 "
        "busy_percent=12.50 123456789\n"
    )


def test_reader_is_wired_as_telegraf_execd():
    config = TELEGRAF_CONF.read_text(encoding="utf-8")

    assert (
        'command = ["python3", "/app/scripts/intel_gpu_top_reader.py"]'
        in config
    )
    assert "[[inputs.execd]]" in config
