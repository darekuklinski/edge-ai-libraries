#!/usr/bin/env bash
set -Eeuo pipefail

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $0 [--full-clean|--full_clean] [--dry-run] [--help]

Stop and remove this ChatQnA Compose project, its named volumes, orphan
containers, and service images. This permanently deletes the project's
database and object-store data.

Options:
  --full-clean, --full_clean
      Also remove the configured MODEL_PATH under this sample directory.
      The default cleanup preserves downloaded models.
  --dry-run
      Print the cleanup actions without performing them.
  -h, --help
      Show this help.

The script preserves .env and does not run a system-wide container prune.
EOF
}

sample_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
full_clean=false
dry_run=false

while (($#)); do
    case "$1" in
        --full-clean|--full_clean)
            full_clean=true
            ;;
        --dry-run)
            dry_run=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
    shift
done

[[ -r "$sample_dir/.env" ]] ||
    die "Missing $sample_dir/.env. Restore it before cleaning this Compose project."

requested_engine="${CONTAINER_ENGINE:-}"
requested_model_path="${MODEL_PATH:-}"
requested_project_name="${COMPOSE_PROJECT_NAME:-}"
set +u
set -a
# .env is already the launcher's shell-compatible Compose environment file.
# shellcheck disable=SC1091
source "$sample_dir/.env"
set +a
set -u
[[ -z "$requested_engine" ]] || CONTAINER_ENGINE="$requested_engine"
[[ -z "$requested_model_path" ]] || MODEL_PATH="$requested_model_path"
[[ -z "$requested_project_name" ]] || COMPOSE_PROJECT_NAME="$requested_project_name"

runtime_works() {
    case "$1" in
        docker)
            command -v docker >/dev/null 2>&1 &&
                docker compose version >/dev/null 2>&1 &&
                timeout 10 docker info >/dev/null 2>&1
            ;;
        podman)
            command -v podman >/dev/null 2>&1 &&
                podman compose version >/dev/null 2>&1 &&
                timeout 10 podman info >/dev/null 2>&1
            ;;
        *)
            return 1
            ;;
    esac
}

select_container_runtime() {
    local requested="${CONTAINER_ENGINE:-auto}"
    case "$requested" in
        auto)
            if runtime_works docker; then
                container_engine=docker
            elif runtime_works podman; then
                container_engine=podman
            else
                die "No working Docker Compose or Podman Compose installation is available."
            fi
            ;;
        docker|podman)
            runtime_works "$requested" ||
                die "$requested Compose is unavailable or its runtime is not accessible."
            container_engine="$requested"
            ;;
        *)
            die "CONTAINER_ENGINE must be auto, docker, or podman; received '$requested'."
            ;;
    esac

    if [[ "$container_engine" == podman ]]; then
        compose_command=(podman compose)
    else
        compose_command=(docker compose)
    fi
}

resolve_model_path() {
    local configured_model_path="${MODEL_PATH:-./ovms/models}"
    local lexical_model_path
    local resolved_model_path

    if [[ "$configured_model_path" == /* ]]; then
        lexical_model_path="$configured_model_path"
        resolved_model_path="$(realpath -m -- "$configured_model_path")"
    else
        lexical_model_path="$sample_dir/$configured_model_path"
        resolved_model_path="$(realpath -m -- "$sample_dir/$configured_model_path")"
    fi

    [[ ! -L "$lexical_model_path" ]] ||
        die "--full-clean refuses a symlink MODEL_PATH: $lexical_model_path"
    case "$resolved_model_path" in
        "$sample_dir"/*) ;;
        *)
            die "--full-clean only removes MODEL_PATH values inside $sample_dir; resolved path: $resolved_model_path"
            ;;
    esac
    [[ "$resolved_model_path" != "$sample_dir" ]] ||
        die "--full-clean refuses to remove the sample directory itself."
    model_path="$resolved_model_path"
}

if [[ "$full_clean" == true ]]; then
    resolve_model_path
fi

select_container_runtime
compose_command+=(--env-file "$sample_dir/.env")

printf 'Cleanup scope: ChatQnA Compose project (%s).\n' "$sample_dir"
printf 'Container runtime: %s\n' "$container_engine"
printf 'Will remove Compose containers, orphans, project volumes, and service images.\n'
printf 'Will preserve .env and resources belonging to other projects.\n'
if [[ "$full_clean" == true ]]; then
    printf 'Will also remove the model cache at %s.\n' "$model_path"
else
    printf 'Will preserve the model cache; pass --full-clean to remove it.\n'
fi

if [[ "$dry_run" == true ]]; then
    printf 'Would run: %s down --volumes --remove-orphans --rmi all --timeout 10\n' \
        "${compose_command[*]}"
    exit 0
fi

cd "$sample_dir"
"${compose_command[@]}" down --volumes --remove-orphans --rmi all --timeout 10

if [[ "$full_clean" == true && -e "$model_path" ]]; then
    printf 'Removing model cache at %s...\n' "$model_path"
    rm -rf -- "$model_path"
fi

printf 'ChatQnA cleanup complete. .env has been preserved.\n'
