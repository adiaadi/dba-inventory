#!/usr/bin/env bash
set -euo pipefail
SID="${2:-CBSETL}"
case "$SID" in CBSETL|CAPETL|DWH) ;; *) echo "Unsupported SID" >&2; exit 1 ;; esac
. /home/oracle/scripts/setEnv.sh
export ORACLE_SID="$SID"
exec /usr/bin/python3 /opt/db-inv-oracle-v3/monitor.py "${1:-probe}" --sid "$SID"
