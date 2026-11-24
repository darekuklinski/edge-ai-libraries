#!/usr/bin/env bash
set -Eeuo pipefail

sample_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Usage: $0 [deploy|backup|cleanup] [options]

With no command, choose an action interactively.
  deploy   Start ChatQnA.
  backup   Back up pgvector (optional argument: backup directory).
  cleanup  Remove the project's containers, volumes, and service images.
           This permanently deletes database and object-store data.

Run '$0 deploy --help' or '$0 cleanup --help' for action-specific options.
EOF
}

if (($# == 0)); then
    printf 'Choose an action:\n  1) deploy\n  2) backup\n  3) cleanup (deletes database and object-store data)\n'
    while true; do
        printf 'Selection [1-3]: '
        if ! IFS= read -r selection; then
            printf '\nERROR: No action selected. Use deploy, backup, or cleanup.\n' >&2
            exit 1
        fi
        case "$selection" in
            1|deploy) set -- deploy; break ;;
            2|backup) set -- backup; break ;;
            3|cleanup) set -- cleanup; break ;;
            *) printf 'Invalid selection. Choose 1, 2, or 3.\n' >&2 ;;
        esac
    done
fi

action="$1"
shift
case "$action" in
    deploy) exec bash "$sample_dir/scripts/run_chatQnA.sh" "$@" ;;
    backup) exec bash "$sample_dir/scripts/backup-pgvector.sh" "$@" ;;
    cleanup) exec bash "$sample_dir/scripts/nuclear-cleanup.sh" "$@" ;;
    -h|--help) usage ;;
    *)
        printf 'ERROR: Unknown action: %s\n' "$action" >&2
        usage >&2
        exit 1
        ;;
esac
