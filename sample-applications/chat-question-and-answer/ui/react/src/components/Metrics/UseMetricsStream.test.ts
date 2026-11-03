import { describe, expect, test } from "vitest";
import { parseMetricsPoint } from "./UseMetricsStream";

describe("parseMetricsPoint", () => {
  test("maps Telegraf samples from the metrics manager stream", () => {
    const point = parseMetricsPoint({
      timestamp: 1234,
      metrics: [
        { name: "cpu_usage_user", labels: { cpu: "cpu-total" }, value: 12 },
        { name: "cpu_usage_system", labels: { cpu: "cpu-total" }, value: 3 },
        { name: "mem_used_percent", value: 68.2 },
        { name: "npu_utilization", value: 4 },
        {
          name: "gpu_engine_usage_usage",
          labels: { engine: "compute", gpu_id: "0" },
          value: 25.5,
        },
      ],
    });

    expect(point).toEqual({
      timestamp: "1234",
      cpu: 15,
      gpu: { bcs: 9.09, rcs: 1.12, ccs: 25.5, vcs: 99.99, vecs: 100.00 },
      npu: 4,
      ram: 68.2,
    });
  });

  test("derives CPU usage from idle when user and system samples are absent", () => {
    const point = parseMetricsPoint({
      metrics: [
        { name: "cpu_usage_idle", labels: { cpu: "cpu-total" }, value: 72 },
      ],
    });

    expect(point.cpu).toBe(28);
  });
});