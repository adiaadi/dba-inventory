#!/usr/bin/env bash
set -euo pipefail
. /home/oracle/scripts/setEnv.sh

# -----------------------------------------------------------------------------
# Sync archived logs from PRIMARY to STANDBY based on the last applied sequence.
# Run this script on STANDBY host (as oracle user).
#
# Usage:
#   ./sync_seed_arch.sh <PRIMARY_HOST> <AUX_SID>
#
# Examples:
#   ./sync_seed_arch.sh cap-prod-db CAPETL
#   ./sync_seed_arch.sh cbs-prod-db CBSETL
#   ./sync_seed_arch.sh dwh-prod-db DWH
#
# File name formats:
#   CAPETL -> <SEQ>_<THREAD>_<ID>.arc	e.g. 2293_1_1204738459.arc
#   default -> 1_<SEQ>_*.dbf			e.g. 1_2293_1204738459.dbf
#
# Primary directories:
#   DWH		-> /oradata/archive
#   default	-> /oradata/backup/${AUX_SID}_seed
# -----------------------------------------------------------------------------

usage() {
  cat <<EOF
Usage: $0 <PRIMARY_HOST> <AUX_SID>

Examples:
  $0 cap-prod-db CAPETL
  $0 cbs-prod-db CBSETL
  $0 dwh-prod-db DWH
EOF
  exit 1
}

PRIMARY_HOST="${1:-}"
AUX_SID="${2:-}"
RESETLOGS_ID="${3:-}"

case "$AUX_SID:$PRIMARY_HOST" in
  CBSETL:cbs-prod-db|CAPETL:cap-prod-db|DWH:dwh-prod-db) ;;
  *) printf 'Unsupported SID/primary pair\n' >&2; exit 1 ;;
esac
[[ "$RESETLOGS_ID" =~ ^[1-9][0-9]*$ ]] || exit 1

[[ -n "$PRIMARY_HOST" && -n "$AUX_SID" ]] || usage

export ORACLE_SID="${AUX_SID}"
PRIMARY_USER="oracle"

if [[ "$AUX_SID" == "DWH" ]]; then
  PRIMARY_DIR="/oradata/archive"
else
  PRIMARY_DIR="/oradata/backup/${AUX_SID}_seed"
fi

STANDBY_DIR="/u01/arch/${AUX_SID}_seed"
LOG_FILE="/home/oracle/log/sync_seed_arch_${AUX_SID}.log"
LOCK_FILE="/tmp/sync_seed_arch_${AUX_SID}.lock"

SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10"
RSYNC_OPTS="-a --no-perms --no-owner --no-group --omit-dir-times"

RETRY_ON_MISMATCH=1

# === HELPERS (minimal) ===
log() { printf '%s | %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE"; }
die() { log "ERROR: $*"; exit 1; }

command -v sqlplus >/dev/null 2>&1 || die "sqlplus not found"
command -v ssh     >/dev/null 2>&1 || die "ssh not found"
command -v rsync   >/dev/null 2>&1 || die "rsync not found"
command -v flock   >/dev/null 2>&1 || die "flock not found"
command -v stat    >/dev/null 2>&1 || die "stat not found"
command -v awk     >/dev/null 2>&1 || die "awk not found"
command -v sort    >/dev/null 2>&1 || die "sort not found"

mkdir -p "$(dirname "$LOG_FILE")" "$STANDBY_DIR"

if [[ "$AUX_SID" == "CAPETL" ]]; then
  FILE_GLOB="*.arc"
  FILE_FORMAT_DESC="<SEQ>_<THREAD>_<ID>.arc"
else
  FILE_GLOB="1_*_*.dbf"
  FILE_FORMAT_DESC="1_<SEQ>_*.dbf"
fi

# === SINGLE-INSTANCE LOCK ===
exec 200>"$LOCK_FILE"
flock -n 200 || { log "Already running for AUX_SID=${AUX_SID}, exit."; exit 2; }

log "==== START sync ${AUX_SID}_seed archivelogs ===="
log "Primary host: ${PRIMARY_HOST}"
log "Primary: ${PRIMARY_USER}@${PRIMARY_HOST}:${PRIMARY_DIR}"
log "Standby: ${STANDBY_DIR}"
log "Expected file format: ${FILE_FORMAT_DESC}"

# 1) Get last applied sequence on STANDBY
max_applied="$(sqlplus -L -s / as sysdba <<'SQL'
whenever oserror exit failure
whenever sqlerror exit failure
set pages 0 feedback off verify off heading off echo off trimspool on
SELECT NVL(MAX(al.sequence#),0)
  FROM v$archived_log al
 WHERE al.applied='YES'
   AND al.thread#=1
   AND al.resetlogs_id = (SELECT resetlogs_id FROM v$database_incarnation WHERE status='CURRENT')
   AND al.resetlogs_change# = (SELECT d.resetlogs_change# FROM v$database d);
exit
SQL
)"
max_applied="$(echo "$max_applied" | tr -d '[:space:]')"
[[ "$max_applied" =~ ^[0-9]+$ ]] || die "Invalid max_applied: '$max_applied'"
log "Standby MAX(APPLIED) sequence#: $max_applied"

# 2) List candidate files on PRIMARY: "SEQ FULLPATH", only SEQ > max_applied
listing="$(
  ssh $SSH_OPTS "${PRIMARY_USER}@${PRIMARY_HOST}" AUX_SID="${AUX_SID}" PRIMARY_DIR="${PRIMARY_DIR}" RESETLOGS_ID="${RESETLOGS_ID}" bash <<'EOSSH' | awk -v last="$max_applied" '$1 > last {print $0}' | sort -n -k1,1
set -euo pipefail
[[ -d "$PRIMARY_DIR" && -r "$PRIMARY_DIR" && -x "$PRIMARY_DIR" ]] || exit 1
shopt -s nullglob

if [[ "$AUX_SID" == "CAPETL" ]]; then
  for f in "${PRIMARY_DIR}"/*_1_"${RESETLOGS_ID}".arc; do
    b=$(basename "$f")
    s=${b%%_*}
    [[ "$s" =~ ^[0-9]+$ ]] || continue
    echo "$s $f"
  done
else
  for f in "${PRIMARY_DIR}"/1_*_"${RESETLOGS_ID}".dbf; do
    b=$(basename "$f")
    s=${b#1_}; s=${s%%_*}
    [[ "$s" =~ ^[0-9]+$ ]] || continue
    echo "$s $f"
  done
fi
EOSSH
)" || die "Remote archive listing failed"
rows=()
if [[ -n "$listing" ]]; then
  mapfile -t rows <<< "$listing"
fi

if [[ "${#rows[@]}" -eq 0 ]]; then
  log "No new files (seq > $max_applied)."
  log "==== FINISH ===="
  exit 0
fi

log "Found ${#rows[@]} file(s) to copy."

# 3) Copy + size verification (re-copy on mismatch once)
for row in "${rows[@]}"; do
  seq="${row%% *}"
  rpath="${row#* }"
  base="$(basename "$rpath")"
  lpath="${STANDBY_DIR}/${base}"

  log "COPY seq=$seq file=$base"

  # Copy from PRIMARY to STANDBY directory
  rsync $RSYNC_OPTS -e "ssh $SSH_OPTS" \
    "${PRIMARY_USER}@${PRIMARY_HOST}:${rpath}" \
	"${lpath}" >>"$LOG_FILE" 2>&1 || die "Copy failed: $base"

  # Verify sizes and optionally re-copy once if mismatch
  attempt=0
  while true; do
    rsz="$(ssh $SSH_OPTS "${PRIMARY_USER}@${PRIMARY_HOST}" "stat -c%s \"$rpath\"")"
    lsz="$(stat -c%s "$lpath")"

    if [[ "$rsz" == "$lsz" ]]; then
      log "OK size: $base ($lsz bytes)"
      break
    fi

    log "SIZE MISMATCH: $base (primary=$rsz standby=$lsz)"
    ((attempt++)) || true
    if [[ "$attempt" -le "$RETRY_ON_MISMATCH" ]]; then
      log "Re-copy attempt #$attempt: $base"
      rsync $RSYNC_OPTS -e "ssh $SSH_OPTS" \
        "${PRIMARY_USER}@${PRIMARY_HOST}:${rpath}" \
        "${lpath}" >>"$LOG_FILE" 2>&1 || die "Re-copy failed: $base"
    else
      die "Size mismatch persists after retries: $base"
    fi
  done
done

log "==== FINISH OK ===="
exit 0
