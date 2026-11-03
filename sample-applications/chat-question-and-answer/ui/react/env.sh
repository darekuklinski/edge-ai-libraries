#!/bin/sh
# Copyright (C) 2024 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

escape_json_string() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

for key in APP_ENDPOINT_URL APP_DATA_PREP_URL APP_MAX_TOKENS APP_METRICS_URL
do
  value=$(printenv "$key" 2>/dev/null || true)
  [ -n "$value" ] || continue
  escaped_value=$(escape_sed_replacement "$value")
  find /opt/share/nginx/html -type f \( -name '*.js' -o -name '*.css' \) \
    -exec sed -i "s|${key}|${escaped_value}|g" '{}' +
done

metrics_url=$(escape_json_string "${APP_METRICS_URL:-}")
system_info=$(escape_json_string "${APP_SYSTEM_INFO:-}")
printf 'window.__CHATQNA_RUNTIME_CONFIG__ = {"metricsUrl":"%s","systemInfo":"%s"};\n' \
  "$metrics_url" "$system_info" > /opt/share/nginx/html/runtime-config.js
