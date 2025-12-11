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

check_ping() {
  local proto="$1"
  local target="$2"
  local output
  local avg

  if output=$(ping "$proto" -n -c "$count" -W "$timeout" "$target" 2>/dev/null); then
    avg=$(printf '%s\n' "$output" | tail -n 1 | awk -F '/' '{print $5}')
    echo "$avg"
  else
    echo ""
  fi
}

res4=$(check_ping "-4" "$host")
res6=$(check_ping "-6" "$host")

final_res=""

if [ -n "$res4" ] && [ -n "$res6" ]; then
  if awk "BEGIN {exit !($res4 < $res6)}"; then
    final_res="$res4"
  else
    final_res="$res6"
  fi
elif [ -n "$res4" ]; then
  final_res="$res4"
elif [ -n "$res6" ]; then
  final_res="$res6"
fi

if [ -n "$final_res" ]; then
  printf 'success:%s\n' "$final_res"
  exit 0
fi

echo "failed:0"
exit 0
