#!/usr/bin/env bash
set -Eeuo pipefail

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $0 [--help]

Install the required host utilities and start ChatQnA with Docker Compose or
Podman Compose. Copy .env.example to .env and configure it before running.

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
    for utility in curl git tmux timeout awk sed stat hostname; do
        if ! command -v "$utility" >/dev/null 2>&1; then
            missing=true
            break
        fi
    done
    if [[ "$missing" == false ]]; then
        return
    fi
    case "$package_manager" in
        apt) install_packages curl git tmux coreutils gawk sed hostname ;;
        dnf) install_packages curl git tmux coreutils gawk sed hostname ;;
        pacman) install_packages curl git tmux coreutils gawk sed inetutils ;;
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

resolve_paths() {
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    chatqna_dir="$(cd -- "${script_dir}/.." && pwd)"
    cd "$chatqna_dir"
}

load_environment() {
    [[ -r "$chatqna_dir/.env" ]] || die "Missing $chatqna_dir/.env. Copy .env.example to .env and configure it first."
    set +u
    set -a
    # .env is a shell environment file in this sample; only source a trusted local copy.
    source "$chatqna_dir/.env"
    set +a
    set -u
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
    if [[ -z "${HUGGINGFACEHUB_API_TOKEN:-}" || "$HUGGINGFACEHUB_API_TOKEN" == replace-with-huggingface-token ]]; then
        read -r -s -p "Hugging Face API token (required): " HUGGINGFACEHUB_API_TOKEN
        printf '\n'
    fi
    [[ -n "$HUGGINGFACEHUB_API_TOKEN" ]] || die "A Hugging Face API token is required."

    local target_device="${DEVICE:-}"
    while [[ "$target_device" != CPU && "$target_device" != GPU ]]; do
        read -r -p "Target device (CPU or GPU): " target_device
        if [[ "$target_device" != CPU && "$target_device" != GPU ]]; then
            printf 'Enter CPU or GPU. NPU is not supported by this sample.\n' >&2
        fi
    done


    LLM_MODEL="${LLM_MODEL:-OpenVINO/gpt-oss-20b-int4-ov}"
    EMBEDDING_MODEL_NAME="${EMBEDDING_MODEL_NAME:-nomic-ai/nomic-embed-text-v1.5}"
    RERANKER_MODEL="${RERANKER_MODEL:-BAAI/bge-reranker-base}"
    DEVICE="$target_device"
    WEIGHT_FORMAT="${WEIGHT_FORMAT:-int8}"
    HOST_UID="$(id -u)"
    USER_GROUP_ID="$(id -g)"
    APP_SYSTEM_INFO="${APP_SYSTEM_INFO:-$(detect_system_info)}"
    RENDER_DEVICE_GID="${RENDER_DEVICE_GID:-0}"
    ALLOWED_HOSTS="${ALLOWED_HOSTS:-*}"
    REGISTRY="${REGISTRY:-intel/}"
    TAG="${TAG:-latest}"
    ENDPOINT_URL="http://ovms-service/v3"
    EMBEDDING_ENDPOINT_URL="http://ovms-service/v3"
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

    APP_METRICS_URL="http://${HOST_IP}:${HOST_METRICS_PORT:-9090}/metrics/stream"
    GETI_SERVER_SSL_VERIFY="${GETI_SERVER_SSL_VERIFY:-False}"
    export HUGGINGFACEHUB_API_TOKEN LLM_MODEL EMBEDDING_MODEL_NAME RERANKER_MODEL
    export DEVICE WEIGHT_FORMAT HOST_UID USER_GROUP_ID APP_SYSTEM_INFO RENDER_DEVICE_GID
    export COMPOSE_PROFILES ENDPOINT_URL EMBEDDING_ENDPOINT_URL STARTUP_MODELS_CONFIG_HOST_PATH
    export ALLOWED_HOSTS REGISTRY TAG APP_METRICS_URL HOST_IP GETI_SERVER_SSL_VERIFY MODEL_PATH
}

start_application() {
    if tmux has-session -t chatqna 2>/dev/null; then
        die "A tmux session named 'chatqna' already exists. Inspect or stop it before restarting."
    fi

    local compose_line session_command
    printf -v compose_line '%q ' "${compose_command[@]}" --env-file "$chatqna_dir/.env" up --build
    compose_line="${compose_line% }"
    printf -v session_command 'cd %q && %s; status=$?; printf "\\nCompose exited with status %%s. Press Enter to close this session.\\n" "$status"; read -r' \
        "$chatqna_dir" "$compose_line"

    tmux new-session -d -s chatqna -c "$chatqna_dir" \
        -e "HUGGINGFACEHUB_API_TOKEN=$HUGGINGFACEHUB_API_TOKEN" \
        -e "LLM_MODEL=$LLM_MODEL" \
        -e "EMBEDDING_MODEL_NAME=$EMBEDDING_MODEL_NAME" \
        -e "RERANKER_MODEL=$RERANKER_MODEL" \
        -e "DEVICE=$DEVICE" \
        -e "WEIGHT_FORMAT=$WEIGHT_FORMAT" \
        -e "HOST_UID=$HOST_UID" \
        -e "USER_GROUP_ID=$USER_GROUP_ID" \
        -e "APP_SYSTEM_INFO=$APP_SYSTEM_INFO" \
        -e "RENDER_DEVICE_GID=$RENDER_DEVICE_GID" \
        -e "COMPOSE_PROFILES=$COMPOSE_PROFILES" \
        -e "ENDPOINT_URL=$ENDPOINT_URL" \
        -e "EMBEDDING_ENDPOINT_URL=$EMBEDDING_ENDPOINT_URL" \
        -e "STARTUP_MODELS_CONFIG_HOST_PATH=$STARTUP_MODELS_CONFIG_HOST_PATH" \
        -e "ALLOWED_HOSTS=$ALLOWED_HOSTS" \
        -e "REGISTRY=$REGISTRY" \
        -e "TAG=$TAG" \
        -e "APP_METRICS_URL=$APP_METRICS_URL" \
        -e "HOST_IP=$HOST_IP" \
        -e "GETI_SERVER_SSL_VERIFY=$GETI_SERVER_SSL_VERIFY" \
        -e "MODEL_PATH=$MODEL_PATH" \
        -e "CONTAINER_ENGINE=$CONTAINER_ENGINE" \
        -e "CONTAINER_USERNS_MODE=$CONTAINER_USERNS_MODE" \
        "$session_command"
    printf 'ChatQnA is starting. Follow logs with: tmux attach-session -t chatqna\n'
}

wait_for_chatqna_api() {
    printf 'Waiting for ChatQnA health (up to 30 minutes)...\n'
    local response=""
    for ((attempt = 1; attempt <= 1800; attempt++)); do
        if ! tmux has-session -t chatqna 2>/dev/null; then
            die "The ChatQnA Compose session exited before the API became healthy."
        fi
        response="$(curl -fsS --max-time 2 "http://${HOST_IP}:8101/api/v1/health" 2>/dev/null || true)"
        if [[ "$response" == *'"status":"healthy"'* &&
              "$response" == *'LLM model server is ready to serve'* &&
              "$response" == *'Embedding model server is ready to serve'* ]]; then
            printf 'ChatQnA is ready at http://%s:8101\n' "$HOST_IP"
            printf 'Attach to the Compose logs with: tmux attach-session -t chatqna\n'
            return
        fi
        sleep 1
    done
    die "ChatQnA did not become healthy within 30 minutes. Inspect: tmux attach-session -t chatqna"
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
    configure_environment
    start_application
    wait_for_chatqna_api
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
