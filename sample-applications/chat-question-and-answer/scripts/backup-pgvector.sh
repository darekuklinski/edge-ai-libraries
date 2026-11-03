#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
sample_dir="$(cd -- "$script_dir/.." && pwd)"
backup_dir="${1:-"$sample_dir/backups"}"
mkdir -p "$backup_dir"

if [[ -r "$sample_dir/.env" ]]; then
  set +u
  set -a
  # The sample's .env is a trusted shell environment file.
  source "$sample_dir/.env"
  set +a
  set -u
fi

case "${CONTAINER_ENGINE:-auto}" in
  docker)
    compose_command=(docker compose)
    ;;
  podman)
    compose_command=(podman compose)
    ;;
  auto)
    if command -v docker >/dev/null 2>&1 &&
      docker compose version >/dev/null 2>&1 &&
      timeout 10 docker info >/dev/null 2>&1; then
      compose_command=(docker compose)
    elif command -v podman >/dev/null 2>&1 &&
      podman compose version >/dev/null 2>&1 &&
      timeout 10 podman info >/dev/null 2>&1; then
      compose_command=(podman compose)
    else
      echo "Neither Docker Compose nor Podman Compose is available." >&2
      exit 1
    fi
    ;;
  *)
    echo "CONTAINER_ENGINE must be auto, docker, or podman." >&2
    exit 1
    ;;
esac

backup_file="$backup_dir/pgvector-$(date +%Y%m%d-%H%M%S)-$$.dump"
if ! (cd "$sample_dir" && "${compose_command[@]}" exec -T pgvector sh -c \
  'exec pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"') \
  > "$backup_file"; then
  rm -f -- "$backup_file"
  echo "Failed to create pgvector backup; ensure the pgvector service is running." >&2
  exit 1
fi

echo "Database backup saved to: $backup_file"
