// Copyright (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { METRICS_URL } from "../../config";

type MetricValue = number | "N/A";

export const GPU_ENGINES = ["bcs", "rcs", "ccs", "vcs", "vecs"] as const;
export type GpuEngine = (typeof GPU_ENGINES)[number];

export type GpuMetricsPoint = Record<GpuEngine, MetricValue>;

export type MetricsPoint = {
  timestamp: string;
  cpu: MetricValue;
  gpu: GpuMetricsPoint;
  npu: MetricValue;
  ram: MetricValue;
};

const MAX_POINTS = 20;
const GPU_ENGINE_ALIASES: Record<GpuEngine, string[]> = {
  bcs: ["bcs", "copy", "Blitter"],
  rcs: ["rcs", "render", "Render/3D"],
  ccs: ["ccs", "compute", "Compute"],
  vcs: ["vcs", "video", "Video"],
  vecs: ["vecs", "videoenhance", "videoenhancement", "VideoEnhance", "VideoEnhancement"],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeValue(value: unknown): MetricValue {
  if (typeof value === "number") {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : "N/A";
  }

  return "N/A";
}

function normalizeGpuMetrics(value: unknown): GpuMetricsPoint {
  const gpuValue = isRecord(value) ? value : {};

  return {
    bcs: normalizeValue(gpuValue.bcs),
    rcs: normalizeValue(gpuValue.rcs),
    ccs: normalizeValue(gpuValue.ccs),
    vcs: normalizeValue(gpuValue.vcs),
    vecs: normalizeValue(gpuValue.vecs),
  };
}

export function parseMetricsPoint(raw: Record<string, unknown>): MetricsPoint {
  const samples = Array.isArray(raw.metrics) ? raw.metrics.filter(isRecord) : [];
  const metricValue = (name: string, labelName?: string, labelValue?: string): MetricValue => {
    const matchingSamples = samples.filter((sample) => {
      if (sample.name !== name) {
        return false;
      }

      if (!labelName) {
        return true;
      }

      const labels = isRecord(sample.labels) ? sample.labels : {};
      return labels[labelName] === labelValue;
    });

    const totalCpuSample = matchingSamples.find((sample) => {
      const labels = isRecord(sample.labels) ? sample.labels : {};
      return labels.cpu === "cpu-total";
    });
    const selectedSample = totalCpuSample ?? matchingSamples[0];
    return selectedSample ? normalizeValue(selectedSample.value) : "N/A";
  };

  const cpuUsage = [
    metricValue("cpu_usage_user", "cpu", "cpu-total"),
    metricValue("cpu_usage_system", "cpu", "cpu-total"),
  ].filter((value): value is number => typeof value === "number");
  const cpuIdle = metricValue("cpu_usage_idle", "cpu", "cpu-total");
  const cpu = cpuUsage.length
    ? cpuUsage.reduce((total, value) => total + value, 0)
    : typeof cpuIdle === "number"
      ? 100 - cpuIdle
      : normalizeValue(raw.cpu);

  const fallbackGpu = normalizeGpuMetrics(raw.gpu);
  const gpu = Object.fromEntries(
    GPU_ENGINES.map((engine) => {
      const aliases = GPU_ENGINE_ALIASES[engine];
      const values = samples
        .filter((sample) => sample.name === "gpu_engine_usage_usage")
        .filter((sample) => {
          const labels = isRecord(sample.labels) ? sample.labels : {};
          const metricEngine = String(labels.engine ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
          return aliases.includes(metricEngine);
        })
        .map((sample) => normalizeValue(sample.value))
        .filter((value): value is number => typeof value === "number");
      return [engine, values.length ? Math.max(...values) : fallbackGpu[engine]];
    })
  ) as GpuMetricsPoint;

  const npu = metricValue("npu_utilization");
  const ram = metricValue("mem_used_percent");

  return {
    timestamp: raw.timestamp == null ? "" : String(raw.timestamp),
    cpu,
    gpu,
    npu: npu === "N/A" ? normalizeValue(raw.npu) : npu,
    ram: ram === "N/A" ? normalizeValue(raw.ram) : ram,
  };
}

export function useMetricsStream(ramType: "gb" | "percent" = "percent") {
  const [points, setPoints] = useState<MetricsPoint[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const url = `${METRICS_URL}?ram_type=${ramType}`;

    fetchEventSource(url, {
      method: "GET",
      signal: controller.signal,
      openWhenHidden: true,

      async onopen(response) {
        if (!response.ok) {
          throw new Error(`Metrics stream failed: ${response.status} ${response.statusText}`);
        }

        setIsConnected(true);
      },

      onmessage(event) {
        if (!event.data) {
          return;
        }

        const raw = JSON.parse(event.data) as unknown;
        if (!isRecord(raw)) {
          return;
        }

        const point = parseMetricsPoint(raw);

        setPoints((prev) => [...prev, point].slice(-MAX_POINTS));
      },

      onerror(error) {
        setIsConnected(false);
        console.error("Metrics stream error:", error);
        throw error;
      },
    });

    return () => {
      controller.abort();
      setIsConnected(false);
    };
  }, [ramType]);

  return { points, isConnected };
}
