#!/bin/sh
# Managed by Ansible
# DN42 latency probe helper. Emits "success:<avg_ms>" on success, "failed:0" otherwise.
set -eu

endpoint="${1-}"
count="${2-5}"
timeout="${3-2}"

if [ -z "$endpoint" ]; then
  echo "failed:0"
  exit 0
fi

case "$endpoint" in
  *']:'*)
    host="${endpoint%%]*}"
    host="${host#[}" # drop leading '['
    ;;
  *:*)
    host="${endpoint%%:*}"
    ;;
  *)
    host="$endpoint"
    ;;
esac

if [ -z "$host" ]; then
  echo "failed:0"
  exit 0
fi

if output=$(ping -n -c "$count" -W "$timeout" "$host" 2>&1); then
  avg=$(printf '%s\n' "$output" | tail -n 1 | awk -F '/' '{print $5}')
  if [ -n "$avg" ]; then
    printf 'success:%s\n' "$avg"
    exit 0
  fi
fi

echo "failed:0"
exit 0
