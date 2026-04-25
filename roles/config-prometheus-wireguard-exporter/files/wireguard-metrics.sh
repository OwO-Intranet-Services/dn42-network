#!/bin/bash
set -euo pipefail

OUTPUT_DIR="/var/lib/prometheus/node-exporter"
OUTPUT_FILE="${OUTPUT_DIR}/wireguard.prom"
TEMP_FILE="${OUTPUT_FILE}.$$"

wg show all dump | awk -F'\t' '
BEGIN {
    print "# HELP wireguard_latest_handshake_seconds UNIX timestamp of the latest handshake"
    print "# TYPE wireguard_latest_handshake_seconds gauge"
    print "# HELP wireguard_received_bytes_total Total bytes received"
    print "# TYPE wireguard_received_bytes_total counter"
    print "# HELP wireguard_sent_bytes_total Total bytes sent"
    print "# TYPE wireguard_sent_bytes_total counter"
}
NF == 9 {
    iface=$1; pubkey=$2; endpoint=$4; handshake=$6; rx=$7; tx=$8
    printf "wireguard_latest_handshake_seconds{interface=\"%s\",public_key=\"%s\"} %s\n", iface, pubkey, handshake
    printf "wireguard_received_bytes_total{interface=\"%s\",public_key=\"%s\"} %s\n", iface, pubkey, rx
    printf "wireguard_sent_bytes_total{interface=\"%s\",public_key=\"%s\"} %s\n", iface, pubkey, tx
}
' > "$TEMP_FILE"

mv "$TEMP_FILE" "$OUTPUT_FILE"
