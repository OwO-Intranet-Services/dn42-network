#!/bin/sh
set -eu

endpoint="https://dn42.g-load.eu/utilityAPI/ca/v1/request"
token_file="token.txt"

performRequest() {
  if [ ! -f "request.csr" ]; then
    echo "Certificate signing request (CSR) missing. It needs to be present under the filename 'request.csr'"
    echo "You can generate a CSR using this command:"
    echo 'openssl req -nodes -newkey rsa:4096 -keyout server.key -out request.csr -subj "/CN=your-domain.dn42"'
    exit 2
  fi

  if [ ! -f "$token_file" ]; then
    echo "Token file '$token_file' is missing."
    exit 2
  fi

  exit_code=0
  result=$(curl --fail-with-body --silent "$endpoint" -F "csr=@request.csr" -F "token=@$token_file") || exit_code=$?
  if [ $exit_code -ne 0 ]; then
    echo "Error"
    echo "$result"
    exit 1
  fi
  
  echo "$result" > signed.crt
  echo "Saved signed certificate to 'signed.crt'"
  echo "Success"
  echo "--- The following files need to be configured in your webserver ---"
  echo "Private key: server.key"
  echo "Signed certificate: signed.crt"
}


get_certificate() {
  domain="$1"
  echo "Requesting signature for ${domain}..."
  if [ ! -f "request.csr" ] || [ ! -f "server.key" ]; then
      echo "Generating new CSR and Key..."
      openssl req -nodes -newkey rsa:4096 -keyout server.key -out request.csr -subj "/CN=${domain}" 2> /dev/null
  else
      echo "Using existing CSR and Key..."
  fi
  performRequest "$domain"
}

print_usage() {
    echo "Usage: $0 [-t token_file] <command> [args...]"
    echo "Commands:"
    echo "  get_certificate <domain.dn42>"
    echo "  sign_csr"
}

# Parse options
while getopts ":t:" opt; do
  case $opt in
    t)
      token_file="$OPTARG"
      ;;
    \?)
      echo "Invalid option: -$OPTARG" >&2
      print_usage
      exit 1
      ;;
    :)
      echo "Option -$OPTARG requires an argument." >&2
      print_usage
      exit 1
      ;;
  esac
done
shift $((OPTIND-1))

if [ -z ${1+x} ]; then
    print_usage
    exit 0
fi


case "$1" in
  ("get_certificate")
    if [ -z "${2-}" ]; then
      echo "domain argument missing"
      exit 1
    fi
    get_certificate "$2"
    exit 0
    ;;

  ("sign_csr")
    performRequest
    exit 0
    ;;

  (*)
    print_usage
    exit 0
    ;;
esac