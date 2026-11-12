"""Merge the sample Patroni pair into portal config, preserving existing pairs."""
import json
import shutil
import sys
import time
from pathlib import Path

target = Path(sys.argv[1] if len(sys.argv) > 1 else 'config/replication.json')
data = json.loads(target.read_text(encoding='utf-8-sig'))
addition = json.loads(Path(__file__).with_name('replication.json').read_text(encoding='utf-8'))['pairs'][0]
if any(p['id'] == addition['id'] for p in data['pairs']):
    print('AML Patroni pair already configured; no changes made.')
else:
    backup = target.with_name(target.name + '.bak-' + str(time.time_ns()))
    shutil.copy2(target, backup)
    data['pairs'].append(addition)
    # Write in-place so existing Docker bind mounts continue to see this file.
    target.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print('Added AML Patroni pair. Backup:', backup)
