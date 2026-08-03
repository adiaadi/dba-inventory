#!/usr/bin/env bash
set -euo pipefail

PFX_FILE="${PFX_FILE:-./certs/db-inv.bnkc.com.pfx}"
CERT_FILE="${TLS_CERT_FILE_HOST:-./certs/db-inv.bnkc.com.crt}"
KEY_FILE="${TLS_KEY_FILE_HOST:-./certs/db-inv.bnkc.com.key}"

if [ ! -f "$PFX_FILE" ]; then
  echo "PFX file not found: $PFX_FILE" >&2
  exit 1
fi

mkdir -p "$(dirname "$CERT_FILE")" "$(dirname "$KEY_FILE")"

PASSIN_ARGS=()
if [ -n "${PFX_PASSWORD:-}" ]; then
  PASSIN_ARGS=(-passin "pass:${PFX_PASSWORD}")
fi

openssl pkcs12 -in "$PFX_FILE" "${PASSIN_ARGS[@]}" -clcerts -nokeys -out "$CERT_FILE"
CHAIN_FILE="$(mktemp)"
if openssl pkcs12 -in "$PFX_FILE" "${PASSIN_ARGS[@]}" -cacerts -nokeys -out "$CHAIN_FILE"; then
  cat "$CHAIN_FILE" >> "$CERT_FILE"
fi
rm -f "$CHAIN_FILE"

openssl pkcs12 -in "$PFX_FILE" "${PASSIN_ARGS[@]}" -nocerts -nodes -out "$KEY_FILE"

chmod 644 "$CERT_FILE"
chmod 600 "$KEY_FILE"

echo "Certificate written to: $CERT_FILE"
echo "Private key written to: $KEY_FILE"
