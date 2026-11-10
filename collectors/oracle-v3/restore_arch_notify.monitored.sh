#!/usr/bin/env bash
set -euo pipefail
. /home/oracle/scripts/setEnv.sh
export PROXY_URL="http://10.210.120.87:3128"

# -----------------------------------------------------------------------------
# Usage:
#   ./restore_arch_notify.sh <AUX_SID>
#
# Examples:
#   ./restore_arch_notify.sh CAPETL
#   ./restore_arch_notify.sh CBSETL
#   ./restore_arch_notify.sh DWH
#
# File name formats:
#   CAPETL -> <SEQ>_<THREAD>_<ID>.arc
#   default -> 1_<SEQ>_*.dbf
# -----------------------------------------------------------------------------

usage() {
  cat <<EOF
Usage: $0 <AUX_SID>

Examples:
  $0 CAPETL
  $0 CBSETL
  $0 DWH
EOF
  exit 1
}

AUX_SID="${1:-}"
case "$AUX_SID" in CBSETL|CAPETL|DWH) ;; *) usage ;; esac

IN_DIR="/u01/arch/${AUX_SID}_seed"
LOG_DIR="/home/oracle/log"
LOG_FILE="${LOG_DIR}/restore_arch_${AUX_SID}.log"

LOCK_FILE="/tmp/restore_arch_${AUX_SID}.lock"
SYNC_LOCK_FILE="/tmp/sync_seed_arch_${AUX_SID}.lock"

LAG_WARN_SEQ=3

mkdir -p "$LOG_DIR" "$IN_DIR"

export ORACLE_SID="${AUX_SID}"

if [[ "$AUX_SID" == "CAPETL" ]]; then
  FILE_PATTERN="*.arc"
  FILE_FORMAT_DESC="<SEQ>_<THREAD>_<ID>.arc"
else
  FILE_PATTERN="1_*_*.dbf"
  FILE_FORMAT_DESC="1_<SEQ>_*.dbf"
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

notify() {
  if [[ -n "${TG_BOT_TOKEN:-}" && -n "${TG_CHAT_ID:-}" ]]; then
    local msg="$1"
    curl -sS --max-time 10 \
      --proxy "$PROXY_URL" \
      -d "chat_id=${TG_CHAT_ID}" \
      --data-urlencode "text=${msg}" \
      "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" >/dev/null || true
  fi
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  exit 2
fi

# If nothing to process, check lag and exit
shopt -s nullglob
FILES=("${IN_DIR}/"${FILE_PATTERN})
shopt -u nullglob

HOSTNAME_SHORT="$(hostname)"

log "START restore_arch for AUX_SID=${AUX_SID}"
log "Incoming pieces: ${#FILES[@]}"
log "Input dir: ${IN_DIR}"
log "Expected file format: ${FILE_FORMAT_DESC}"

# Check role/mode + lags
SQL_OUT="$(sqlplus -L -s / as sysdba <<'SQL'
whenever oserror exit failure
whenever sqlerror exit failure
set pages 0 feedback off heading off verify off echo off lines 200
select 'ROLE='||database_role||' OPEN_MODE='||open_mode||' CF='||controlfile_type from v$database;
select 'LAST_RECEIVED='||nvl(to_char(max(sequence#)),'NULL') from v$archived_log where thread#=1 and resetlogs_change#=(select resetlogs_change# from v$database);
select 'LAST_APPLIED='||nvl(to_char(max(sequence#)),'NULL') from v$archived_log where applied='YES' and thread#=1 and resetlogs_change#=(select resetlogs_change# from v$database);
SQL
)"

# Write SQL output line-by-line with timestamp
while IFS= read -r line; do
  [[ -n "$line" ]] && log "$line"
done <<< "$SQL_OUT"

# Get numeric values
LAST_R="$(echo "$SQL_OUT" | awk -F= '/LAST_RECEIVED=/{print $2}')"
LAST_A="$(echo "$SQL_OUT" | awk -F= '/LAST_APPLIED=/{print $2}')"
ROLE_L="$(echo "$SQL_OUT" | awk '/ROLE=/{print $0}')"

[[ "$LAST_R" =~ ^[0-9]+$ || "$LAST_R" == "NULL" ]] || { log "Invalid received sequence"; exit 1; }
[[ "$LAST_A" =~ ^[0-9]+$ || "$LAST_A" == "NULL" ]] || { log "Invalid applied sequence"; exit 1; }

# Check lag if available
if [[ "$LAST_R" != "NULL" && "$LAST_A" != "NULL" ]]; then
  LAG=$(( LAST_R - LAST_A ))
  if (( LAG >= LAG_WARN_SEQ )); then
    notify "РІС™В РїС‘РЏ [DR: ${AUX_SID}] lag=${LAG} seq (received=${LAST_R}, applied=${LAST_A}). ${ROLE_L}"
    log "WARN Standby lag=${LAG} seq (received=${LAST_R}, applied=${LAST_A}). ${ROLE_L}"
  fi
fi

# exit if no new files
if [[ ${#FILES[@]} -eq 0 ]]; then
  log "No new files matching ${FILE_PATTERN} in ${IN_DIR}. Exit."
  log "DONE restore_arch"
  exit 0
fi

log "Running RMAN: catalog + recover database"

set +e
rman target / 2>&1 <<RMAN | while IFS= read -r line; do log "$line"; done
catalog start with '${IN_DIR}/' noprompt;
run {
  allocate channel c1 device type disk;
  recover database;
  release channel c1;
}
RMAN
RC_RMAN=${PIPESTATUS[0]}
set -e

if [[ $RC_RMAN -ne 0 ]]; then
  log "ERROR RMAN failed RC=$RC_RMAN"
  notify "РІС™В РїС‘РЏ DR: ${AUX_SID} Recover failed"
  exit "$RC_RMAN"
fi

log "RMAN completed successfully"
log "DONE restore_arch"
