#!/usr/bin/env bash
set -Eeuo pipefail

database_volume_exists=false

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $0 [--help]

Install the required host utilities and start ChatQnA. Copy .env.example to
.env first; missing interactive settings are requested when this script runs.

Supported systems:
  Debian 12+, Ubuntu 22.04+, Linux Mint 21.3+
  Fedora 40+, RHEL 9+, Rocky Linux 9+
  Arch Linux and Manjaro

Set CONTAINER_ENGINE=docker or CONTAINER_ENGINE=podman in .env to select a
runtime. Docker must have its Compose plugin and an accessible daemon. Podman
uses its external Compose provider and runs rootless without a daemon.
EOF
}

version_at_least() {
    local current_major current_minor minimum_major minimum_minor
    IFS=. read -r current_major current_minor _ <<< "$1"
    IFS=. read -r minimum_major minimum_minor _ <<< "$2"
    current_minor="${current_minor:-0}"
    minimum_minor="${minimum_minor:-0}"
    (( current_major > minimum_major ||
       (current_major == minimum_major && current_minor >= minimum_minor) ))
}

detect_distribution() {
    [[ -r /etc/os-release ]] || die "Cannot identify this operating system (/etc/os-release is missing)."
    # shellcheck disable=SC1091
    source /etc/os-release

    case "$ID" in
        debian)
            version_at_least "$VERSION_ID" 12 || die "Debian 12 or newer is required."
            package_manager=apt
            ;;
        ubuntu)
            version_at_least "$VERSION_ID" 22.04 || die "Ubuntu 22.04 or newer is required."
            package_manager=apt
            ;;
        linuxmint)
            version_at_least "$VERSION_ID" 21.3 || die "Linux Mint 21.3 or newer is required."
            package_manager=apt
            ;;
        fedora)
            version_at_least "$VERSION_ID" 40 || die "Fedora 40 or newer is required."
            package_manager=dnf
            ;;
        rhel|rocky|almalinux)
            version_at_least "$VERSION_ID" 9 || die "RHEL or Rocky Linux 9 or newer is required."
            package_manager=dnf
            ;;
        arch|manjaro)
            package_manager=pacman
            ;;
        *)
            die "Unsupported distribution: $ID. See --help for the supported list."
            ;;
    esac
}

check_host_requirements() {
    [[ "$(uname -m)" == x86_64 ]] || die "This launcher supports x86_64 hosts only."
    local kernel_version kernel_major kernel_minor
    kernel_version="$(uname -r)"
    if [[ "$kernel_version" =~ ^([0-9]+)\.([0-9]+) ]]; then
        kernel_major="${BASH_REMATCH[1]}"
        kernel_minor="${BASH_REMATCH[2]}"
    else
        die "Cannot determine the host kernel version: $kernel_version"
    fi
    if (( 10#$kernel_major < 5 || (10#$kernel_major == 5 && 10#$kernel_minor < 15) )); then
        die "Linux kernel 5.15 or newer is required; found $kernel_version."
    fi
}

install_packages() {
    local packages=("$@")
    case "$package_manager" in
        apt)
            run_privileged apt-get update
            run_privileged apt-get install -y "${packages[@]}"
            ;;
        dnf)
            run_privileged dnf install -y "${packages[@]}"
            ;;
        pacman)
            run_privileged pacman -S --needed --noconfirm "${packages[@]}"
            ;;
    esac
}

run_privileged() {
    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    elif command -v doas >/dev/null 2>&1; then
        doas "$@"
    else
        die "Installing packages requires sudo or doas."
    fi
}

ensure_host_utilities() {
    local missing=false
    local utility
    for utility in curl git timeout awk sed stat hostname base64 head od tr mktemp; do
        if ! command -v "$utility" >/dev/null 2>&1; then
            missing=true
            break
        fi
    done
    if [[ "$missing" == false ]]; then
        return
    fi
    case "$package_manager" in
        apt) install_packages curl git coreutils gawk sed hostname ;;
        dnf) install_packages curl git coreutils gawk sed hostname ;;
        pacman) install_packages curl git coreutils gawk sed inetutils ;;
    esac
}

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

install_podman() {
    case "$package_manager" in
        apt) install_packages podman podman-compose ;;
        dnf) install_packages podman podman-compose ;;
        pacman) install_packages podman podman-compose ;;
    esac
}

normalize_podman_local_image_refs() {
    [[ "$container_engine" == podman ]] || return 0

    local variable image first_component changed=false
    for variable in BE_IMAGE_NAME FE_IMAGE_NAME; do
        image="${!variable:-}"
        [[ -n "$image" ]] || continue
        first_component="${image%%/*}"
        if [[ "$first_component" != localhost &&
              "$first_component" != *.* &&
              "$first_component" != *:* ]]; then
            printf -v "$variable" 'localhost/%s' "$image"
            export "$variable"
            changed=true
        fi
    done
    [[ "$changed" == false ]] ||
        printf 'Using local image names for Podman-built ChatQnA services.\n'
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
                printf 'No working Docker Compose or Podman Compose installation found; installing Podman.\n'
                install_podman
                runtime_works podman || die "Podman Compose is not ready. Install Podman and a Compose provider, then retry."
                container_engine=podman
            fi
            ;;
        docker|podman)
            if ! runtime_works "$requested"; then
                if [[ "$requested" == podman ]]; then
                    printf 'Installing Podman and its Compose provider.\n'
                    install_podman
                fi
                runtime_works "$requested" ||
                    die "$requested is unavailable. Install it, its Compose provider, and (for Docker) ensure its daemon is accessible."
            fi
            container_engine="$requested"
            ;;
        *)
            die "CONTAINER_ENGINE must be auto, docker, or podman; received '$requested'."
            ;;
    esac

    normalize_podman_local_image_refs
    if [[ "$container_engine" == podman ]]; then
        CONTAINER_USERNS_MODE=keep-id
        compose_command=(podman compose)
    else
        CONTAINER_USERNS_MODE=host
        compose_command=(docker compose)
    fi
    export CONTAINER_ENGINE="$container_engine" CONTAINER_USERNS_MODE
    printf 'Using %s with its Compose interface.\n' "$container_engine"
}

warn_if_database_volume_exists() {
    local project_name="${COMPOSE_PROJECT_NAME:-${chatqna_dir##*/}}"
    local database_volume
    project_name="${project_name,,}"
    database_volume="${project_name}_pgvector-data"

    if "$container_engine" volume inspect "$database_volume" >/dev/null 2>&1; then
        database_volume_exists=true
        printf 'WARNING: Existing database volume "%s" will be reused.\n' "$database_volume" >&2
        printf 'The initial admin password only provisions a new database; it does not change existing account passwords.\n' >&2
        printf 'To intentionally erase this deployment data, run "%s compose down --volumes" from %s before deploying.\n' \
            "$container_engine" "$chatqna_dir" >&2
    fi
}

print_initial_admin_credentials() {
    [[ "$database_volume_exists" == false ]] || return 0

    printf '\nFirst deployment complete. Admin sign-in credentials:\n'
    printf '  Username: admin\n'
    printf '  Password: %s\n' "$CHATQNA_ADMIN_PASSWORD"
    printf 'Store these credentials securely; they are not shown on later deployments.\n'
}

resolve_paths() {
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    chatqna_dir="$(cd -- "${script_dir}/.." && pwd)"
    cd "$chatqna_dir"
}

load_environment() {
    [[ -r "$chatqna_dir/.env" ]] || die "Missing $chatqna_dir/.env. Copy .env.example to .env and configure it first."
    local admin_password_override="${CHATQNA_ADMIN_PASSWORD:-}"
    local hf_token_override="${HUGGINGFACEHUB_API_TOKEN:-}"
    local device_override="${DEVICE:-}"
    local engine_override="${CONTAINER_ENGINE:-}"
    local llm_model_override="${LLM_MODEL:-}"
    local embedding_model_override="${EMBEDDING_MODEL_NAME:-}"
    local reranker_model_override="${RERANKER_MODEL:-}"
    local model_path_override="${MODEL_PATH:-}"
    local token_encryption_key_override="${HF_TOKEN_ENCRYPTION_KEY:-}"
    local token_exchange_key_override="${MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY:-}"
    local model_download_token_override="${MODEL_DOWNLOAD_SERVICE_TOKEN:-}"
    set +u
    set -a
    # .env is a shell environment file in this sample; only source a trusted local copy.
    source "$chatqna_dir/.env"
    set +a
    set -u
    [[ -z "$admin_password_override" ]] || CHATQNA_ADMIN_PASSWORD="$admin_password_override"
    [[ -z "$hf_token_override" ]] || HUGGINGFACEHUB_API_TOKEN="$hf_token_override"
    [[ -z "$device_override" ]] || DEVICE="$device_override"
    [[ -z "$engine_override" ]] || CONTAINER_ENGINE="$engine_override"
    [[ -z "$llm_model_override" ]] || LLM_MODEL="$llm_model_override"
    [[ -z "$embedding_model_override" ]] || EMBEDDING_MODEL_NAME="$embedding_model_override"
    [[ -z "$reranker_model_override" ]] || RERANKER_MODEL="$reranker_model_override"
    [[ -z "$model_path_override" ]] || MODEL_PATH="$model_path_override"
    [[ -z "$token_encryption_key_override" ]] || HF_TOKEN_ENCRYPTION_KEY="$token_encryption_key_override"
    [[ -z "$token_exchange_key_override" ]] || MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY="$token_exchange_key_override"
    [[ -z "$model_download_token_override" ]] || MODEL_DOWNLOAD_SERVICE_TOKEN="$model_download_token_override"
}

persist_env_value() {
    local name="$1" value="$2" temporary line found=false
    temporary="$(mktemp "${chatqna_dir}/.env.XXXXXX")"
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" == "${name}="* ]]; then
            [[ "$found" == false ]] || {
                rm -f -- "$temporary"
                die "Duplicate $name entries in .env."
            }
            printf '%s=%s\n' "$name" "$value" >> "$temporary"
            found=true
        else
            printf '%s\n' "$line" >> "$temporary"
        fi
    done < "$chatqna_dir/.env"
    if [[ "$found" == false ]]; then
        rm -f -- "$temporary"
        die "Missing $name entry in .env."
    fi
    chmod 600 "$temporary"
    mv -- "$temporary" "$chatqna_dir/.env"
}

ensure_deployment_secrets() {
    local generated
    if [[ -z "${HF_TOKEN_ENCRYPTION_KEY:-}" ]]; then
        generated="$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')"
        HF_TOKEN_ENCRYPTION_KEY="$generated"
        persist_env_value HF_TOKEN_ENCRYPTION_KEY "$generated"
    fi
    if [[ -z "${MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY:-}" ]]; then
        generated="$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')"
        MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY="$generated"
        persist_env_value MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY "$generated"
    fi
    if [[ -z "${MODEL_DOWNLOAD_SERVICE_TOKEN:-}" ]]; then
        generated="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
        MODEL_DOWNLOAD_SERVICE_TOKEN="$generated"
        persist_env_value MODEL_DOWNLOAD_SERVICE_TOKEN "$generated"
    fi
    export HF_TOKEN_ENCRYPTION_KEY MODEL_DOWNLOAD_TOKEN_EXCHANGE_KEY
    export MODEL_DOWNLOAD_SERVICE_TOKEN
    printf 'Generated missing local model-token encryption/service keys in .env.\n'
}

detect_system_info() {
    local cpu_model ram_total gpu_info os_name device device_path pci_address gpu_model memory_bytes memory_label
    cpu_model="$(awk -F: '/^model name[[:space:]]*:/ {sub(/^[[:space:]]*/, "", $2); print $2; exit}' /proc/cpuinfo)"
    ram_total="$(awk '/^MemTotal:/ {printf "%.1f GiB", $2 / 1048576}' /proc/meminfo)"
    gpu_info="N/A"
    os_name="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-Linux}") $(uname -r)"

    shopt -s nullglob
    local devices=(/sys/class/drm/card[0-9]/device)
    shopt -u nullglob
    for device in "${devices[@]}"; do
        [[ -r "$device/vendor" ]] || continue
        device_path="$(readlink -f "$device" 2>/dev/null || true)"
        pci_address="${device_path##*/}"
        gpu_model="$(lspci -s "$pci_address" 2>/dev/null | sed -E 's/^[^ ]+ [^:]+: //; s/ \([Rr]ev[^)]*\)$//' || true)"
        [[ -n "$gpu_model" ]] || gpu_model="GPU ${pci_address}"

        memory_bytes="$(cat "$device/mem_info_vram_total" 2>/dev/null || printf '0')"
        memory_label="VRAM N/A"
        if [[ "$memory_bytes" =~ ^[0-9]+$ ]] && (( memory_bytes > 0 )); then
            memory_label="$(awk -v bytes="$memory_bytes" 'BEGIN {printf "%.1f GiB VRAM", bytes / 1073741824}')"
        else
            memory_bytes="$(cat "$device/mem_info_gtt_total" 2>/dev/null || printf '0')"
            if [[ "$memory_bytes" =~ ^[0-9]+$ ]] && (( memory_bytes > 0 )); then
                memory_label="$(awk -v bytes="$memory_bytes" 'BEGIN {printf "%.1f GiB shared memory", bytes / 1073741824}')"
            fi
        fi
        gpu_info="$gpu_model $memory_label"
        break
    done

    printf 'CPU: %s | GPU: %s | RAM: %s | OS: %s' \
        "${cpu_model:-N/A}" "$gpu_info" "${ram_total:-N/A}" "$os_name"
}

host_ip_address() {
    local address=""
    if command -v ip >/dev/null 2>&1; then
        address="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' || true)"
    fi
    if [[ -z "$address" ]]; then
        address="$(hostname -I 2>/dev/null | awk '{print $1}')"
    fi
    printf '%s' "$address"
}

configure_environment() {
    if [[ "${HUGGINGFACEHUB_API_TOKEN:-}" == replace-with-huggingface-token ]]; then
        HUGGINGFACEHUB_API_TOKEN=""
    fi
    if [[ -z "${HUGGINGFACEHUB_API_TOKEN:-}" && -t 0 ]]; then
        read -r -s -p "Hugging Face API token (optional; press Enter for public models): " HUGGINGFACEHUB_API_TOKEN
        printf '\n'
    fi

    local target_device="${DEVICE:-}"
    while [[ "$target_device" != CPU && "$target_device" != GPU ]]; do
        [[ -t 0 ]] || die "Set DEVICE=CPU or DEVICE=GPU in .env or the environment for an unattended deployment."
        read -r -p "Target device (CPU or GPU): " target_device
        if [[ "$target_device" != CPU && "$target_device" != GPU ]]; then
            printf 'Enter CPU or GPU. NPU is not supported by this sample.\n' >&2
        fi
    done

    if [[ -z "${CHATQNA_ADMIN_PASSWORD:-}" ]]; then
        [[ -t 0 ]] || die "Set CHATQNA_ADMIN_PASSWORD in .env or the environment for an unattended deployment."
        local password_confirmation
        while true; do
            read -r -s -p "Initial admin password (8-128 characters): " CHATQNA_ADMIN_PASSWORD
            printf '\n'
            if [[ ${#CHATQNA_ADMIN_PASSWORD} -lt 8 || ${#CHATQNA_ADMIN_PASSWORD} -gt 128 ]]; then
                CHATQNA_ADMIN_PASSWORD=""
                printf 'The initial admin password must be 8-128 characters. Try again.\n' >&2
                continue
            fi
            read -r -s -p "Confirm initial admin password: " password_confirmation
            printf '\n'
            [[ "$CHATQNA_ADMIN_PASSWORD" == "$password_confirmation" ]] && break
            CHATQNA_ADMIN_PASSWORD=""
            printf 'Passwords do not match. Try again.\n' >&2
        done
    elif [[ ${#CHATQNA_ADMIN_PASSWORD} -lt 8 || ${#CHATQNA_ADMIN_PASSWORD} -gt 128 ]]; then
        die "CHATQNA_ADMIN_PASSWORD must be 8-128 characters."
    fi

    LLM_MODEL="${LLM_MODEL:-TinyLlama/TinyLlama-1.1B-Chat-v1.0}"
    EMBEDDING_MODEL_NAME="${EMBEDDING_MODEL_NAME:-BAAI/bge-base-en-v1.5}"
    RERANKER_MODEL="${RERANKER_MODEL:-cross-encoder/ms-marco-MiniLM-L-2-v2}"
    DEVICE="$target_device"
    WEIGHT_FORMAT="${WEIGHT_FORMAT:-int8}"
    HOST_UID="$(id -u)"
    USER_GROUP_ID="$(id -g)"
    APP_SYSTEM_INFO="${APP_SYSTEM_INFO:-$(detect_system_info)}"
    RENDER_DEVICE_GID="${RENDER_DEVICE_GID:-0}"
    ALLOWED_HOSTS="${ALLOWED_HOSTS:-*}"
    REGISTRY="${REGISTRY:-intel/}"
    TAG="${TAG:-latest}"
    ENDPOINT_URL="http://ovms-service:8080/v3"
    EMBEDDING_ENDPOINT_URL="http://ovms-service:8080/v3"
    COMPOSE_PROFILES=OVMS
    if [[ "$DEVICE" == GPU ]]; then
        shopt -s nullglob
        local render_devices=(/dev/dri/render*)
        shopt -u nullglob
        ((${#render_devices[@]} > 0)) || die "GPU selected but no /dev/dri/render device was found."
        RENDER_DEVICE_GID="$(stat -c '%g' "${render_devices[0]}")"
        COMPOSE_PROFILES=GPU-OVMS
    fi

    local startup_config="${STARTUP_MODELS_CONFIG_HOST_PATH:-}"
    if [[ -z "$startup_config" ||
          "$startup_config" == "./startup-models-cpu.yaml" ||
          "$startup_config" == "./startup-models-gpu.yaml" ||
          "$startup_config" == "${chatqna_dir}/startup-models-cpu.yaml" ||
          "$startup_config" == "${chatqna_dir}/startup-models-gpu.yaml" ]]; then
        startup_config="${chatqna_dir}/startup-models-${DEVICE,,}.yaml"
    fi
    STARTUP_MODELS_CONFIG_HOST_PATH="$startup_config"
    [[ "$STARTUP_MODELS_CONFIG_HOST_PATH" == /* ]] ||
        STARTUP_MODELS_CONFIG_HOST_PATH="${chatqna_dir}/${STARTUP_MODELS_CONFIG_HOST_PATH#./}"
    [[ -r "$STARTUP_MODELS_CONFIG_HOST_PATH" ]] || die "Missing model startup config: $STARTUP_MODELS_CONFIG_HOST_PATH"

    MODEL_PATH="${MODEL_PATH:-${chatqna_dir}/ovms/models}"
    [[ "$MODEL_PATH" == /* ]] || MODEL_PATH="${chatqna_dir}/${MODEL_PATH#./}"
    mkdir -p "$MODEL_PATH"
    MODEL_PATH="$(cd -- "$MODEL_PATH" && pwd)"

    HOST_IP="${HOST_IP:-$(host_ip_address)}"
    [[ -n "$HOST_IP" ]] || die "Could not determine the host IP address. Set HOST_IP in .env and retry."
    APP_METRICS_URL="http://${HOST_IP}:${HOST_METRICS_PORT:-9090}/metrics/stream"
    GETI_SERVER_SSL_VERIFY="${GETI_SERVER_SSL_VERIFY:-False}"
    export HUGGINGFACEHUB_API_TOKEN CHATQNA_ADMIN_PASSWORD
    export LLM_MODEL EMBEDDING_MODEL_NAME RERANKER_MODEL
    export DEVICE WEIGHT_FORMAT HOST_UID USER_GROUP_ID APP_SYSTEM_INFO RENDER_DEVICE_GID
    export COMPOSE_PROFILES ENDPOINT_URL EMBEDDING_ENDPOINT_URL STARTUP_MODELS_CONFIG_HOST_PATH
    export ALLOWED_HOSTS REGISTRY TAG APP_METRICS_URL HOST_IP GETI_SERVER_SSL_VERIFY MODEL_PATH
}

start_application() {
    local logs_command
    cd "$chatqna_dir"
    printf 'Building local Compose images before starting dependent services...\n'
    "${compose_command[@]}" --env-file "$chatqna_dir/.env" build
    "${compose_command[@]}" --env-file "$chatqna_dir/.env" up -d
    printf -v logs_command '%q ' \
        "${compose_command[@]}" --env-file "$chatqna_dir/.env" logs -f
    printf 'ChatQnA is starting. Follow logs with: %s\n' "${logs_command% }"
}

wait_for_chatqna_api() {
    printf 'Waiting for ChatQnA health (up to 30 minutes)...\n'
    local response="" logs_command project_name service_status failed_services status_line
    project_name="${COMPOSE_PROJECT_NAME:-${chatqna_dir##*/}}"
    project_name="${project_name,,}"
    for ((attempt = 1; attempt <= 1800; attempt++)); do
        response="$(curl -fsS --max-time 2 "http://${HOST_IP}:8101/v1/chatqna/health" 2>/dev/null || true)"
        if [[ "$response" == *'"status":"healthy"'* &&
              "$response" == *'LLM model server is ready to serve'* &&
              "$response" == *'Embedding model server is ready to serve'* ]]; then
            printf 'ChatQnA is ready at http://%s:8101\n' "$HOST_IP"
            printf -v logs_command '%q ' \
                "${compose_command[@]}" --env-file "$chatqna_dir/.env" logs -f
            printf 'View logs with: %s\n' "${logs_command% }"
            print_initial_admin_credentials
            return
        fi
        service_status="$("$container_engine" ps --all \
            --filter "label=com.docker.compose.project=$project_name" \
            --format '{{.Names}} {{.Status}}' 2>/dev/null || true)"
        failed_services=""
        while IFS= read -r status_line; do
            if [[ "$status_line" =~ [[:space:]](Exited|Dead|Restarting)([[:space:]]|$) ]]; then
                failed_services+="${status_line}"$'\n'
            fi
        done <<< "$service_status"
        if [[ -n "$failed_services" ]]; then
            printf 'ERROR: ChatQnA services exited or are restarting before becoming healthy:\n%s' \
                "$failed_services" >&2
            printf 'Recent Compose logs:\n' >&2
            "${compose_command[@]}" --env-file "$chatqna_dir/.env" logs --tail 80 >&2 || true
            return 1
        fi
        sleep 1
    done
    printf 'ERROR: ChatQnA did not become healthy within 30 minutes.\n' >&2
    printf 'Current Compose services:\n' >&2
    "${compose_command[@]}" --env-file "$chatqna_dir/.env" ps >&2 || true
    printf 'Recent Compose logs:\n' >&2
    "${compose_command[@]}" --env-file "$chatqna_dir/.env" logs --tail 80 >&2 || true
    exit 1
}

main() {
    if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
        [[ $# -eq 1 ]] || die "--help does not accept other arguments."
        usage
        return
    fi
    [[ $# -eq 0 ]] || die "Unknown argument: $1"
    [[ "$EUID" -ne 0 ]] || die "Run this script as your regular user; it uses sudo only when installing packages."

    resolve_paths
    load_environment
    detect_distribution
    check_host_requirements
    ensure_host_utilities
    select_container_runtime
    warn_if_database_volume_exists
    configure_environment
    ensure_deployment_secrets
    start_application
    wait_for_chatqna_api
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
