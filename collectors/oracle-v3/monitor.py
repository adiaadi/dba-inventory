#!/usr/bin/env python3
"""Multi-database stage 3: audit archive copies, run recovery, serve cached metrics.

run: oracle only, from run.sh; read: zabbix, no DB access.
The probe mode is read-only, including its optional SHA-256 checks.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import archives

BASE = Path(__file__).resolve().parent
SID = 'CBSETL'
PROFILE = dict(primary='cbs-prod-db01', dbid=3514081376, header_count=16)
STATE = Path('/var/lib/db-inv-oracle/CBSETL/state-v3.json')
MANIFEST = STATE.with_name('manifest-v3.json')
KEYS = ('archived_seq', 'copied_seq', 'applied_seq', 'archive_gap',
        'pending_apply', 'last_success_age', 'transfer_job', 'apply_job')
SQL = """
whenever oserror exit failure
whenever sqlerror exit failure
set pages 0 feedback off heading off verify off echo off lines 32767
set long 1000000 longchunksize 32767 trimspool on
select json_object(
 'dbid' value d.dbid, 'role' value d.database_role,
 'open_mode' value d.open_mode, 'controlfile_type' value d.controlfile_type,
 'incarnation' value to_char(d.resetlogs_change#, 'TM9'),
 'resetlogs_id' value (select resetlogs_id from v$database_incarnation where status='CURRENT'),
 'resetlogs_time' value to_char(d.resetlogs_time,'YYYY-MM-DD HH24:MI:SS'),
 'threads' value (select count(*) from v$thread),
 'thread' value (select min(thread#) from v$thread),
 'archived_seq' value (select max(sequence#) from v$archived_log
   where thread#=1 and resetlogs_change#=d.resetlogs_change# and archived='YES'
   and resetlogs_id=(select resetlogs_id from v$database_incarnation where status='CURRENT')),
 'applied_seq' value (select max(sequence#) from v$archived_log
   where thread#=1 and resetlogs_change#=d.resetlogs_change# and applied='YES'
   and resetlogs_id=(select resetlogs_id from v$database_incarnation where status='CURRENT')),
 'applied_end_scn' value (select to_char(max(next_change#),'TM9') from v$archived_log
   where thread#=1 and resetlogs_change#=d.resetlogs_change# and applied='YES'
   and resetlogs_id=(select resetlogs_id from v$database_incarnation where status='CURRENT')),
 'checkpoint_scn' value (select to_char(min(checkpoint_change#),'TM9') from v$datafile_header),
 'header_count' value (select count(*) from v$datafile_header),
 'bad_headers' value (select count(*) from v$datafile_header
   where error is not null or checkpoint_change# is null or fuzzy is null or fuzzy <> 'NO')
 returning clob) from v$database d;
exit success
"""


def sql_output(query, primary=False):
    if primary:
        cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=10', 'oracle@' + PROFILE['primary'],
               "bash -c '. /home/oracle/scripts/setEnv.sh >/dev/null; "
               f"export ORACLE_SID={SID}; sqlplus -L -s / as sysdba'"]
    else:
        cmd = ['sqlplus', '-L', '-s', '/', 'as', 'sysdba']
    p = subprocess.run(cmd, input=query, text=True, capture_output=True, timeout=45)
    if p.returncode or 'ORA-' in p.stdout or 'SP2-' in p.stdout:
        target = ('Primary ' + PROFILE['primary']) if primary else 'Standby'
        # Include the underlying SSH/SQL*Plus failure, not just a generic label.
        # Bound output because errors are also stored in the state JSON.
        details = '\n'.join(part.strip() for part in (p.stderr, p.stdout) if part.strip())
        raise ValueError(f'{target} SQL failed (SID={SID}, rc={p.returncode}): '
                         + (details[:2000] or 'No stdout/stderr'))
    return p.stdout.strip()


def sql_snapshot(primary=False):
    data = json.loads(sql_output(SQL, primary))
    if not isinstance(data.get('resetlogs_id'), int) or data['resetlogs_id'] <= 0:
        raise ValueError('Current RESETLOGS_ID unavailable')
    if (PROFILE['dbid'] is not None and data['dbid'] != PROFILE['dbid']) or data['threads'] != 1 or data['thread'] != 1:
        raise ValueError('Unexpected database identity or redo threads')
    if primary:
        if data['role'] != 'PRIMARY' or data['open_mode'] != 'READ WRITE':
            raise ValueError('Unexpected primary role/mode')
    elif (data['role'], data['open_mode'], data['controlfile_type']) != (
            'PHYSICAL STANDBY', 'MOUNTED', 'STANDBY'):
        raise ValueError('Unexpected standby role/mode')
    return data


def confirmed_applied(data):
    # Enforce the selected database layout; inspect may run before pins are set.
    if (PROFILE['header_count'] is not None and data['header_count'] != PROFILE['header_count']) or data['header_count'] <= 0 or data['bad_headers'] != 0:
        raise ValueError('Datafile headers require review')
    seq = data['applied_seq']
    if seq is None or data['applied_end_scn'] is None or data['checkpoint_scn'] is None:
        raise ValueError('Applied boundary unavailable')
    if int(data['checkpoint_scn']) < int(data['applied_end_scn']):
        raise ValueError('Checkpoint has not reached the reported applied boundary')
    return seq


def save(data, path=None):
    path = STATE if path is None else path
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            os.fchmod(f.fileno(), 0o640)
            json.dump(data, f)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(path=None):
    path = STATE if path is None else path
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def metadata(primary, standby):
    query = archives.sql_rows(standby['applied_seq'], primary['archived_seq'], primary['resetlogs_id'])
    output = sql_output(query, True)
    rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    # Detect role/incarnation changes around the separate metadata query.
    check = sql_snapshot(True)
    if archives.identity(check) != archives.identity(primary):
        raise ValueError('Primary identity changed during metadata collection')
    return rows


def job(name, args):
    # No forced timeout of RMAN. Hanging jobs become stale in read mode.
    return subprocess.run(['/bin/bash', str(BASE / name), *args]).returncode


def cycle(previous, write=save, query=sql_snapshot, execute=job, clock=time.time,
          read_manifest=lambda: load(MANIFEST), write_manifest=lambda m: save(m, MANIFEST),
          get_rows=metadata, verify=archives.receipt_for, present=None):
    data = {key: None for key in KEYS}
    data.update(sampled_at=int(clock()), cycle_ok=0, error='', archive_file=None,
                source_sampled_at=int(clock()),
                last_success_at=previous.get('last_success_at'),
                last_progress_at=previous.get('last_progress_at'),
                progress_seq=previous.get('progress_seq'),
                identity=previous.get('identity'))
    write(data)
    final_verified = False
    final_queue = False
    try:
        before = query(False)
        identity = archives.identity(before)
        if data['identity'] != identity:
            data.update(last_success_at=None, last_progress_at=None, progress_seq=None)
        data['identity'] = identity
        confirmed_applied(before)
        primary = query(True)
        if archives.identity(primary) != identity:
            raise ValueError('Primary and standby identity mismatch')
        manifest = read_manifest()
        if manifest and manifest.get('identity') != identity:
            raise ValueError('Manifest incarnation mismatch; inspect before reinitializing')

        def run_job(name, args, key):
            rc = execute(name, args)
            data[key] = 'success' if rc == 0 else ('skipped' if rc == 2 else 'failed')
            data[key + '_rc'] = rc
            data['sampled_at'] = int(clock())
            write(data)
            return rc

        transfer_rc = run_job('sync_seed_arch.monitored.sh',
                             [PROFILE['primary'], SID, str(primary['resetlogs_id'])], 'transfer_job')
        data['source_sampled_at'] = int(clock())
        primary = query(True)
        if archives.identity(primary) != identity:
            raise ValueError('Primary identity changed during transfer')
        rows = get_rows(primary, before)
        manifest, required, pending = archives.audit(primary, before, rows, manifest,
                                                     verify=verify, persist=write_manifest)
        data['archived_seq'] = primary['archived_seq']
        data['archive_file'] = manifest.get('last_verified_file')
        data['applied_seq'] = before['applied_seq']
        data.update(archives.queue_metrics(manifest, required, pending, before['applied_seq'],
                                           primary['archived_seq'], present=present))
        data['sampled_at'] = int(clock())
        write(data)
        # Preserve confirmed partial copies when sync fails; never run RMAN after that failure.
        if transfer_rc != 0:
            raise ValueError('transfer_job: non-success; recovery skipped')
        apply_rc = run_job('restore_arch_notify.monitored.sh', [SID], 'apply_job')
        # A failed RMAN may still have made partial progress; inspect without declaring success.
        after = query(False)
        if identity != archives.identity(after):
            raise ValueError('Standby incarnation changed during cycle')
        applied = confirmed_applied(after)
        if applied < before['applied_seq']:
            raise ValueError('Applied sequence moved backwards')
        final_verified = True
        data['applied_seq'] = applied
        if apply_rc == 0:
            data['last_success_at'] = int(clock())
        # Initial observation does not invent a historical progress timestamp.
        if applied > before['applied_seq'] or (
                data['progress_seq'] is not None and applied > data['progress_seq']):
            data['last_progress_at'] = int(clock())
        data['progress_seq'] = applied
        data.update(archives.queue_metrics(manifest, required, pending, applied,
                                           primary['archived_seq'], present=present))
        final_queue = True
        if apply_rc != 0:
            raise ValueError('apply_job: non-success; see RMAN log')
        if data['copied_seq'] is None:
            raise ValueError('No verified copy boundary; latest applied file may already be deleted')
        data['cycle_ok'] = 1
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        # A failed final SQL/audit must not publish provisional queue counters as current.
        if data['apply_job'] is not None:
            if not final_queue:
                data.update(copied_seq=None, archive_gap=None, pending_apply=None)
            if not final_verified:
                data['applied_seq'] = None
        data['error'] = type(exc).__name__ + ': ' + str(exc)
    data['sampled_at'] = int(clock())
    write(data)
    return data


def view(data, now=None):
    now = int(time.time()) if now is None else now
    if (not data or not 0 <= now - data.get('sampled_at', 0) <= 600 or
            not 0 <= now - data.get('source_sampled_at', data.get('sampled_at', 0)) <= 600):
        return dict({key: None for key in KEYS}, cycle_ok=0, snapshot_age=None, archive_file=None,
                    error='Snapshot missing, expired or timestamp is in the future')
    result = dict(data, snapshot_age=now-data['sampled_at'])
    for source, target in [('last_success_at', 'last_success_age'),
                           ('last_progress_at', 'last_progress_age')]:
        stamp = data.get(source)
        result[target] = now-stamp if stamp is not None and stamp <= now else None
    return result


def pinned():
    return all(type(PROFILE[k]) is int and PROFILE[k] > 0 for k in ('dbid', 'header_count'))


def configure(sid):
    global SID, PROFILE, STATE, MANIFEST
    allowed = {'CBSETL': 'cbs-prod-db01', 'CAPETL': 'cap-prod-db01', 'DWH': 'dwh-prod-db01'}
    if sid not in allowed:
        raise ValueError('Unsupported SID')
    profile = json.loads((BASE / 'databases.json').read_text())[sid]
    if profile['primary'] != allowed[sid]:
        raise ValueError('Unexpected primary host; review deployment mapping')
    for key in ('dbid', 'header_count'):
        if profile[key] is not None and (type(profile[key]) is not int or profile[key] <= 0):
            raise ValueError('Invalid identity pin: ' + key)
    SID, PROFILE = sid, profile
    os.environ['ORACLE_SID'] = sid
    STATE = Path('/var/lib/db-inv-oracle') / sid / 'state-v3.json'
    MANIFEST = STATE.with_name('manifest-v3.json')
    archives.configure(sid, profile['primary'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['inspect', 'probe', 'run', 'read'])
    p.add_argument('--sid', choices=['CBSETL', 'CAPETL', 'DWH'], default='CBSETL')
    args = p.parse_args()
    configure(args.sid)
    if args.mode in ('probe', 'run') and not pinned():
        p.error('Set verified dbid and header_count in databases.json after inspect')
    if args.mode == 'inspect':
        standby, primary = sql_snapshot(False), sql_snapshot(True)
        if archives.identity(standby) != archives.identity(primary):
            raise ValueError('Primary and standby identity mismatch')
        confirmed_applied(standby)
        print(json.dumps(dict(mode='inspect', sid=SID, standby=standby, primary=primary)))
        return 0
    if args.mode == 'probe':
        # Read-only: SQL + file hashing, with no jobs, manifest writes or state writes.
        standby = sql_snapshot(False)
        confirmed_applied(standby)
        primary = sql_snapshot(True)
        rows = metadata(primary, standby)
        manifest, required, pending = archives.audit(primary, standby, rows, load(MANIFEST))
        metrics = archives.queue_metrics(manifest, required, pending, standby['applied_seq'],
                                         primary['archived_seq'])
        print(json.dumps(dict(mode='probe', standby=standby, primary=primary, **metrics)))
    elif args.mode == 'read':
        try:
            result = view(load())
        except (OSError, ValueError, TypeError):
            result = view({})
        print(json.dumps(result))
    else:
        import fcntl
        STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        with (STATE.parent / 'chain.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 2
            # Retain the chain lock if the Python parent exits while a child runs.
            os.set_inheritable(lock.fileno(), True)
            def locked_job(name, values):
                return subprocess.run(['/bin/bash', str(BASE/name), *values],
                                      pass_fds=(lock.fileno(),)).returncode
            result = cycle(load(), execute=locked_job)
            print(json.dumps(view(result)))
            return 0 if result['cycle_ok'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
