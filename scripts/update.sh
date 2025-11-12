#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") [git pull arguments]

Stops the dt-relay stack, updates the git repository, and restarts the stack.
Any additional arguments are forwarded to 'git pull'.
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "$script_dir/.." && pwd)
manager_script="$script_dir/dt-relay.sh"

if [[ ! -x "$manager_script" ]]; then
  echo "Error: required script '$manager_script' not found or not executable." >&2
  exit 1
fi

cd "$project_root"

echo "Stopping dt-relay stack..."
"$manager_script" stop

echo "Pulling latest changes..."
git pull --ff-only "$@"

echo "Updating submodules..."
git submodule update --init --recursive

echo "Restarting dt-relay stack..."
"$manager_script" start

