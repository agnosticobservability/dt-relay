#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") <start|stop|restart> [docker compose args]

Manages the dt-relay Docker stack.
- start   Start the stack in detached mode (builds images).
- stop    Stop the stack and remove containers.
- restart Restart the stack by running stop then start.
Any additional arguments are passed to docker compose.
USAGE
}

if [[ ${1:-} == "" ]]; then
  usage
  exit 1
fi

action=$1
shift || true

if [[ "$action" == "-h" || "$action" == "--help" || "$action" == "help" ]]; then
  usage
  exit 0
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "$script_dir/.." && pwd)
compose_file="$project_root/docker-compose.yml"

# Determine the preferred docker compose command.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  compose_cmd=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose_cmd=(docker-compose)
else
  echo "Error: docker compose or docker-compose is required but not installed." >&2
  exit 1
fi

# Prefer a local .env file, fall back to config/defaults.env if present.
if [[ -f "$project_root/.env" ]]; then
  env_file="$project_root/.env"
elif [[ -f "$project_root/config/defaults.env" ]]; then
  env_file="$project_root/config/defaults.env"
else
  env_file=""
fi

env_args=()
if [[ -n "$env_file" ]]; then
  env_args=(--env-file "$env_file")
fi

cd "$project_root"

case "$action" in
  start)
    echo "Starting dt-relay stack..."
    "${compose_cmd[@]}" -f "$compose_file" "${env_args[@]}" up -d --build "$@"
    ;;
  stop)
    echo "Stopping dt-relay stack..."
    "${compose_cmd[@]}" -f "$compose_file" "${env_args[@]}" down "$@"
    ;;
  restart)
    "$script_dir/$(basename "$0")" stop "$@"
    "$script_dir/$(basename "$0")" start "$@"
    ;;
  *)
    echo "Error: Unknown action '$action'." >&2
    usage
    exit 1
    ;;
esac
