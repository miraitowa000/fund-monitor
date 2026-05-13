#!/usr/bin/env sh
set -eu

CONTAINER_NAME="${1:-fund-monitor}"
INTERVAL="${INTERVAL:-5}"
WARN_CLOSE_WAIT="${WARN_CLOSE_WAIT:-50}"
WARN_FD="${WARN_FD:-1000}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing command: $1" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd nsenter
require_cmd ss
require_cmd awk
require_cmd sort
require_cmd uniq
require_cmd wc

while true; do
  clear 2>/dev/null || true
  echo "time: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "container: ${CONTAINER_NAME}"
  echo

  if ! docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "container not found: ${CONTAINER_NAME}" >&2
    sleep "$INTERVAL"
    continue
  fi

  PID="$(docker inspect --format '{{.State.Pid}}' "$CONTAINER_NAME")"
  STATUS="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$CONTAINER_NAME")"
  echo "status: ${STATUS}"
  echo "container_pid: ${PID}"
  echo

  CLOSE_WAIT_PEERS="$(nsenter -t "$PID" -n ss -tan state close-wait | awk '
    NR > 1 {
      count += 1
      for (i = 1; i <= NF; i += 1) {
        if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$/) {
          peer = $i
        }
      }
      if (peer) {
        print peer
      }
      peer = ""
    }
    END {
      if (count == 0) {
        print "__NO_CLOSE_WAIT__"
      }
    }
  ')"
  if printf '%s\n' "$CLOSE_WAIT_PEERS" | grep -q '^__NO_CLOSE_WAIT__$'; then
    CLOSE_WAIT=0
    CLOSE_WAIT_PEERS=""
  else
    CLOSE_WAIT="$(printf '%s\n' "$CLOSE_WAIT_PEERS" | sed '/^$/d' | wc -l | awk '{print $1}')"
  fi
  echo "close_wait: ${CLOSE_WAIT}"
  if [ "$CLOSE_WAIT" -ge "$WARN_CLOSE_WAIT" ]; then
    echo "WARN: close_wait >= ${WARN_CLOSE_WAIT}"
  fi
  echo

  echo "tcp states:"
  nsenter -t "$PID" -n ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c | sort -nr
  echo

  echo "gunicorn fd:"
  docker top "$CONTAINER_NAME" -eo pid,comm | awk '/gunicorn/ && NR>2 {print $1}' | while read -r worker_pid; do
    [ -n "$worker_pid" ] || continue
    fd_count="$(ls "/proc/$worker_pid/fd" 2>/dev/null | wc -l | awk '{print $1}')"
    printf 'pid=%s fd=%s' "$worker_pid" "$fd_count"
    if [ "$fd_count" -ge "$WARN_FD" ]; then
      printf ' WARN: fd >= %s' "$WARN_FD"
    fi
    printf '\n'
  done
  echo

  echo "container stats:"
  docker stats --no-stream "$CONTAINER_NAME" --format 'cpu={{.CPUPerc}} mem={{.MemUsage}} pids={{.PIDs}} net={{.NetIO}}'
  echo

  echo "top close_wait peers:"
  if [ "$CLOSE_WAIT" -eq 0 ]; then
    echo "-"
  else
    printf '%s\n' "$CLOSE_WAIT_PEERS" | sort | uniq -c | sort -nr | head -10
  fi
  echo

  sleep "$INTERVAL"
done
