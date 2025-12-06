SERVER_LIST="lax-01,hkg-01,tyo-01,dls-01,lax-02,ams-01"
IFS=',' read -ra ADDR <<< "$SERVER_LIST"
for i in "${ADDR[@]}"; do
    echo "Connecting to $i..."
    ssh "$i" "$@"
done
