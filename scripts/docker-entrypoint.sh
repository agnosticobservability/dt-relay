#!/usr/bin/env bash
set -euo pipefail

LOG_DIR=${LOG_DIR:-/app/logs}

ensure_log_dir_permissions() {
  mkdir -p "$LOG_DIR"

  if gosu appuser test -w "$LOG_DIR" 2>/dev/null; then
    return 0
  fi

  chown appuser:appuser "$LOG_DIR" 2>/dev/null || true
  chmod 775 "$LOG_DIR" 2>/dev/null || true

  if ! gosu appuser test -w "$LOG_DIR" 2>/dev/null; then
    echo "Warning: unable to ensure write access to $LOG_DIR for appuser" >&2
  fi
}

main() {
  if ! command -v gosu >/dev/null 2>&1; then
    echo "Error: gosu is required but not installed" >&2
    exit 1
  fi

  ensure_log_dir_permissions

  exec gosu appuser "$@"
}

main "$@"
