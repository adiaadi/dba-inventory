"""Read-only archive audit and persistent receipts, specific to CBSETL/thread 1.

No archive deletion, cataloging, recovery or copying is performed here.
Archive counters use a bounded, complete primary metadata set, not MAX subtraction.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

LOCAL = Path('/u01/arch/CBSETL_seed')
REMOTE = '/oradata/backup/CBSETL_seed'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'ConnectTimeout=10', 'oracle@cbs-prod-db']
LIMIT = 10000
SID = 'CBSETL'
FILE_REGEX = r'1_[1-9][0-9]*_[1-9][0-9]*\.dbf'


def configure(sid, host):
    global SID, LOCAL, REMOTE, SSH, FILE_REGEX
    allowed = {'CBSETL': 'cbs-prod-db', 'CAPETL': 'cap-prod-db', 'DWH': 'dwh-prod-db'}
    if allowed.get(sid) != host:
        raise ValueError('Unsupported database/host')
    SID = sid
    LOCAL = Path('/u01/arch') / (sid + '_seed')
    REMOTE = '/oradata/archive' if sid == 'DWH' else '/oradata/backup/' + sid + '_seed'
    SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ConnectTimeout=10', 'oracle@' + host]
    FILE_REGEX = (r'[1-9][0-9]*_1_[1-9][0-9]*\.arc' if sid == 'CAPETL'
                  else r'1_[1-9][0-9]*_[1-9][0-9]*\.dbf')


def archive_name(seq, rid):
    return ('%d_1_%d.arc' if SID == 'CAPETL' else '1_%d_%d.dbf') % (seq, rid)



def identity(snapshot):
    return [snapshot['dbid'], snapshot['incarnation'], snapshot['resetlogs_time'],
            int(snapshot['resetlogs_id']), 1]


def sql_rows(applied, upper, resetlogs_id):
    a, b, rid = int(applied), int(upper), int(resetlogs_id)
    if not 0 <= a <= b or b-a > LIMIT or rid <= 0:
        raise ValueError('Archive window invalid or exceeds 10000 logs; manual review required')
    return """
whenever oserror exit failure
whenever sqlerror exit failure
set pages 0 feedback off heading off verify off echo off lines 32767 trimspool on
select json_object('seq' value sequence#,
 'first' value to_char(min(first_change#),'TM9'),
 'next' value to_char(min(next_change#),'TM9'),
 'first_max' value to_char(max(first_change#),'TM9'),
 'next_max' value to_char(max(next_change#),'TM9'))
from v$archived_log
where thread#=1 and archived='YES'
 and resetlogs_change#=(select resetlogs_change# from v$database)
 and resetlogs_id=%d and sequence#>%d and sequence#<=%d
group by sequence# order by sequence#;
exit success
""" % (rid, a, b)


def validate_rows(rows, applied, upper, boundary_scn):
    if upper < applied or upper-applied > LIMIT:
        raise ValueError('Invalid archive range')
    result = {}
    next_seq = applied + 1
    next_scn = int(boundary_scn)
    for row in rows:
        seq = int(row['seq'])
        first, end = int(row['first']), int(row['next'])
        if seq != next_seq or first != next_scn or first >= end:
            raise ValueError('Archive metadata is incomplete or has a sequence/SCN hole')
        if first != int(row['first_max']) or end != int(row['next_max']):
            raise ValueError('Conflicting archive metadata for the same sequence')
        result[seq] = row
        next_seq, next_scn = seq+1, end
    if next_seq != upper+1:
        raise ValueError('Primary archive records missing; queue size cannot be trusted')
    return result


def remote_digest(filename):
    if not re.fullmatch(FILE_REGEX, filename):
        raise ValueError('Unexpected archive filename')
    path = REMOTE + '/' + filename
    script = '''set -euo pipefail
f="$1"
if [[ ! -e "$f" ]]; then printf 'MISSING\\n'; exit 0; fi
[[ -f "$f" && ! -L "$f" && -r "$f" ]] || exit 1
before=$(stat -c '%s:%Y:%Z:%i' -- "$f")
digest=$(sha256sum -- "$f")
after=$(stat -c '%s:%Y:%Z:%i' -- "$f")
[[ "$before" == "$after" ]] || exit 1
printf '%s %s\\n' "${before%%:*}" "${digest%% *}"
'''
    p = subprocess.run(SSH + ['bash -s -- ' + path], input=script, text=True,
                       capture_output=True, timeout=120)
    if p.returncode:
        raise ValueError('Primary archive hash failed (SSH/read/change); queue unknown')
    value = p.stdout.strip()
    if value == 'MISSING':
        return None
    if not re.fullmatch(r'[1-9][0-9]* [a-f0-9]{64}', value):
        raise ValueError('Invalid primary archive hash response')
    size, digest = value.split()
    return int(size), digest


def fingerprint(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError('Archive is not a regular file')
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def receipt_for(seq, rid, previous=None, directory=None, remote=remote_digest):
    directory = LOCAL if directory is None else directory
    name = archive_name(seq, rid)
    path = directory/name
    try:
        before = fingerprint(path)
    except FileNotFoundError:
        return None
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    if fingerprint(path) != before:
        raise ValueError('Local archive changed during verification')
    # Filesystems may preserve all stat fields across a same-size rewrite.
    # Only reuse a receipt after checking the actual local bytes as well.
    if (previous and previous['fingerprint'] == before and
            (previous['size'], previous['sha256']) == (before[2], digest.hexdigest())):
        return previous
    origin = remote(name)
    if origin is None:
        # Previously verified bytes can survive cleanup of the primary source.
        if not previous or (previous['size'], previous['sha256']) != (before[2], digest.hexdigest()):
            return None
    elif origin != (before[2], digest.hexdigest()):
        return None
    if fingerprint(path) != before:
        raise ValueError('Local archive changed during verification')
    return dict(size=before[2], sha256=digest.hexdigest(), fingerprint=before,
                verified_at=int(time.time()))


def audit(snapshot, standby, rows, manifest, verify=receipt_for, persist=lambda m: None):
    ident = identity(snapshot)
    if identity(standby) != ident:
        raise ValueError('Archive audit identity mismatch')
    applied = int(standby['applied_seq'])
    upper = int(snapshot['archived_seq'])
    required = validate_rows(rows, applied, upper, standby['applied_end_scn'])
    if manifest and manifest.get('identity') != ident:
        raise ValueError('Manifest belongs to another incarnation; inspect before reinitializing')
    manifest = manifest or dict(version=2, identity=ident, receipts={}, copied_seq=None,
                                applied_floor=applied)
    if applied < manifest['applied_floor']:
        raise ValueError('Applied sequence moved behind the manifest baseline')
    receipts = manifest['receipts']
    # Retain historical high-water mark; old applied files need not remain on disk.
    copied = manifest.get('copied_seq')
    pending = set()
    # Seed the initial copy boundary only from a matching file, never from MAX(APPLIED).
    candidates = sorted(required)
    if copied is None or copied < applied:
        candidates.insert(0, applied)
    for seq in candidates:
        receipt = verify(seq, int(snapshot['resetlogs_id']), receipts.get(str(seq)))
        if receipt:
            receipts[str(seq)] = receipt
            copied = max(copied or 0, seq)
            manifest['copied_seq'] = copied
            if seq in required:
                pending.add(seq)
        else:
            receipts.pop(str(seq), None)
        # Persist each receipt before recovery; a later failure must not lose it.
        persist(manifest)
    for key in list(receipts):
        if int(key) <= applied:
            del receipts[key]
    manifest['applied_floor'] = applied
    persist(manifest)
    return manifest, required, pending


def queue_metrics(manifest, required, pending, applied, upper, present=None):
    # Recheck pending file identity after RMAN: nightly find can remove files at any time.
    if present is None:
        def present(seq, receipt):
            try:
                path = LOCAL/archive_name(seq, manifest['identity'][3])
                return fingerprint(path) == receipt['fingerprint']
            except FileNotFoundError:
                return False
    outstanding = {seq for seq in required if seq > applied}
    available = {seq for seq in pending if seq in outstanding and
                 present(seq, manifest['receipts'][str(seq)])}
    copied = manifest.get('copied_seq')
    if applied > upper:
        raise ValueError('Recovery exceeded sampled primary boundary; retry collection')
    return dict(copied_seq=copied if copied is not None and copied >= applied else None,
                archive_gap=len(outstanding-available), pending_apply=len(available))
