SERVER_LIST="lax-01,hkg-01,tyo-01,dls-01,lax-02,ams-01,tlv-01,bom-01"
IFS=',' read -ra ADDR <<< "$SERVER_LIST"

OUTPUT_DIR=$(mktemp -d)
trap 'rm -rf "$OUTPUT_DIR"; exit' EXIT INT TERM

PIDS=()

run_ssh_and_capture() {
    local server="$1"
    local output_file="$2"
    shift 2
    echo "Connecting to $server..." > "$output_file" 2>&1
    if ! ssh "$server" "$@" >> "$output_file" 2>&1; then
        echo "Error connecting to $server or command failed." >> "$output_file"
    fi
}

for i in "${ADDR[@]}"; do
    tmp_file="${OUTPUT_DIR}/output_${i//[^a-zA-Z0-9_.-]/_}.txt"
    
    ( run_ssh_and_capture "$i" "$tmp_file" "$@" ) &
    PIDS+=($!)
done

for pid in "${PIDS[@]}"; do
    wait "$pid" || true
done

for i in "${ADDR[@]}"; do
    tmp_file="${OUTPUT_DIR}/output_${i//[^a-zA-Z0-9_.-]/_}.txt"
    echo "--- Output from $i ---"
    cat "${tmp_file}"
    echo "----------------------"
done
