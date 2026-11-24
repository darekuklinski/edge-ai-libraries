#!/usr/bin/env bash
set -Eeuo pipefail

sample_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/sample/scripts" "$tmp_dir/bin"
cp "$sample_dir/easy-deploy.sh" "$tmp_dir/sample/"
for script in run_chatQnA.sh backup-pgvector.sh nuclear-cleanup.sh; do
    cat > "$tmp_dir/sample/scripts/$script" <<'EOF'
printf 'action=%s\n' "$(basename "$0")"
printf 'arg=%s\n' "$@"
EOF
done
launcher="$tmp_dir/sample/easy-deploy.sh"

output="$(bash "$launcher" deploy --help)"
[[ "$output" == $'action=run_chatQnA.sh\narg=--help' ]]
output="$(bash "$launcher" backup 'directory with spaces')"
[[ "$output" == $'action=backup-pgvector.sh\narg=directory with spaces' ]]
output="$(bash "$launcher" cleanup --full-clean --dry-run)"
[[ "$output" == $'action=nuclear-cleanup.sh\narg=--full-clean\narg=--dry-run' ]]

for choice in '1:run_chatQnA.sh' '2:backup-pgvector.sh' '3:nuclear-cleanup.sh'; do
    output="$(printf '%s\n' "${choice%%:*}" | bash "$launcher")"
    [[ "$output" == *"action=${choice#*:}"* ]]
done
output="$(printf 'invalid\nbackup\n' | bash "$launcher" 2>&1)"
[[ "$output" == *'Invalid selection.'* && "$output" == *'action=backup-pgvector.sh'* ]]
if bash "$launcher" </dev/null >"$tmp_dir/output" 2>&1; then
    echo 'Expected EOF without a selection to fail.' >&2
    exit 1
fi
grep -q 'No action selected' "$tmp_dir/output"
if bash "$launcher" invalid >"$tmp_dir/output" 2>&1; then
    echo 'Expected an unknown action to fail.' >&2
    exit 1
fi
grep -q 'Unknown action' "$tmp_dir/output"

cp "$sample_dir/scripts/backup-pgvector.sh" "$sample_dir/scripts/nuclear-cleanup.sh" "$tmp_dir/sample/scripts/"
cat > "$tmp_dir/sample/.env" <<'EOF'
CONTAINER_ENGINE=docker
MODEL_PATH=./ovms/models
EOF
cat > "$tmp_dir/bin/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$1 $2" == 'compose exec' ]]; then
    printf 'database dump'
elif [[ "$1 $*" == *' down '* ]]; then
    printf '%s\n' "$PWD" "$*" > "$DOCKER_LOG"
fi
EOF
chmod +x "$tmp_dir/bin/docker"
export PATH="$tmp_dir/bin:$PATH" DOCKER_LOG="$tmp_dir/docker.log"

output="$(cd / && bash "$launcher" backup "$tmp_dir/backups")"
backup_file="${output#Database backup saved to: }"
[[ "$(cat "$backup_file")" == 'database dump' ]]

mkdir -p "$tmp_dir/sample/ovms/models"
output="$(cd / && bash "$launcher" cleanup --full-clean --dry-run)"
[[ "$output" == *"$tmp_dir/sample/ovms/models"* ]]
[[ -d "$tmp_dir/sample/ovms/models" && ! -e "$DOCKER_LOG" ]]
(cd / && bash "$launcher" cleanup --full-clean > /dev/null)
[[ ! -e "$tmp_dir/sample/ovms/models" && -f "$tmp_dir/sample/.env" ]]
grep -Fxq "$tmp_dir/sample" "$DOCKER_LOG"
grep -Fq 'down --volumes --remove-orphans --rmi all --timeout 10' "$DOCKER_LOG"

printf 'easy-deploy tests passed.\n'
