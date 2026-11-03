// Copyright (C) 2025 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

type ChatQnaRuntimeConfig = {
  metricsUrl?: string;
  systemInfo?: string;
};

type SystemInfo = {
  cpu?: string;
  gpu?: string;
  ram?: string;
  os?: string;
};

declare global {
  interface Window {
    __CHATQNA_RUNTIME_CONFIG__?: ChatQnaRuntimeConfig;
  }
}

const runtimeConfig =
  typeof window === "undefined" ? undefined : window.__CHATQNA_RUNTIME_CONFIG__;

export const DATA_PREP_URL: string =
  import.meta.env.VITE_DATA_PREP_SERVICE_URL + '/documents';
export const LINK_PREP_URL: string =
  import.meta.env.VITE_DATA_PREP_SERVICE_URL + '/urls';

export const CHAT_QNA_URL: string =
  import.meta.env.VITE_BACKEND_SERVICE_ENDPOINT + '/chat';
export const HEALTH_CHECK_URL: string =
  import.meta.env.VITE_BACKEND_SERVICE_ENDPOINT + '/health';
export const MODEL_URL: string =
  import.meta.env.VITE_BACKEND_SERVICE_ENDPOINT + '/model';
export const CONVERSATION_HISTORY_URL: string =
  import.meta.env.VITE_BACKEND_SERVICE_ENDPOINT + '/conversations';
export const AUTH_URL: string =
  import.meta.env.VITE_BACKEND_SERVICE_ENDPOINT + '/auth';
export const MAX_TOKENS: number =
  Number(import.meta.env.VITE_MAX_TOKENS) || 512;

export const METRICS_URL: string =
  import.meta.env.VITE_BACKEND_SERVICE_ENDPOINT + '/metrics?ram_type=percent';

export function parseSystemInfo(value: string | undefined): SystemInfo {
  if (!value) {
    return {};
  }

  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      const info = parsed as Record<string, unknown>;
      return {
        cpu: typeof info.CPU === "string" ? info.CPU : undefined,
        gpu: typeof info.GPU === "string" ? info.GPU : undefined,
        ram: typeof info.RAM === "string" ? info.RAM : undefined,
        os: typeof info.OS === "string" ? info.OS : undefined,
      };
    }
  } catch {
    const info: SystemInfo = {};
    for (const part of value.split("|")) {
      const match = part.trim().match(/^(CPU|GPU|RAM|OS):\s*(.+)$/i);
      if (match) {
        const key = match[1].toLowerCase() as keyof SystemInfo;
        info[key] = match[2].trim();
      }
    }
    return info;
  }

  return {};
}

const viteSystemInfo = import.meta.env.VITE_SYSTEM_INFO;
export const SYSTEM_INFO = parseSystemInfo(
  runtimeConfig?.systemInfo ?? (viteSystemInfo === "VITE_SYSTEM_INFO" ? undefined : viteSystemInfo)
);
