"""Measure rsync receive traffic and elapsed copy-command time per cycle."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


def report_path(sid):
    if sid not in ('CBSETL', 'CAPETL', 'DWH'):
        raise ValueError('Unsupported SID')
    return Path('/var/lib/db-inv-oracle') / sid / 'transfer-v3.json'


def save(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.transfer-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o640)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def received_bytes(output):
    matches = re.findall(r'^Total bytes received:\s*([0-9,]+)\s*$', output, re.M)
    return int(matches[0].replace(',', '')) if len(matches) == 1 else None


def measure(args, run=subprocess.run, clock=time.monotonic):
    start = clock()
    result = run(['rsync', '--stats', *args], text=True, capture_output=True,
                 env=dict(os.environ, LC_ALL='C'))
    seconds = clock() - start
    # Preserve rsync diagnostics in the caller's existing log.
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    count = received_bytes(result.stdout)
    return result.returncode, count, seconds


def finish(data):
    duration = data['duration_seconds']
    data['completed_at'] = time.time()
    data['complete'] = True
    data['bytes_per_second'] = (data['bytes_received'] / duration
        if data['valid'] and data['attempts'] and duration > 0 else None)
    return data


def main():
    mode, sid, *args = sys.argv[1:]
    path = report_path(sid)
    if mode == 'reset':
        save(path, dict(started_at=time.time(), complete=False, valid=True,
                        bytes_received=0, duration_seconds=0, attempts=0))
        return 0
    data = json.loads(path.read_text())
    if mode == 'finish':
        save(path, finish(data))
        return 0
    if mode != 'copy':
        raise ValueError('Unsupported mode')
    rc, count, seconds = measure(args)
    data['attempts'] += 1
    data['valid'] = data['valid'] and count is not None and math.isfinite(seconds) and seconds > 0 and rc == 0
    data['bytes_received'] += count or 0
    data['duration_seconds'] += seconds
    save(path, data)
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
