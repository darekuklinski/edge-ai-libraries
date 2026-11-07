#!/usr/bin/env bash
set -Eeuo pipefail

sample_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$sample_dir/scripts/run_chatQnA.sh" "$@"
