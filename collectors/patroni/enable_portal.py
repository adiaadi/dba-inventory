"""Merge the sample Patroni pair into portal config, preserving existing pairs."""
import json
import shutil
import argparse
import re
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('config', nargs='?', default='config/replication.json')
parser.add_argument('--scope', help='Exact Patroni scope; requires --dr-member')
parser.add_argument('--dr-member', help='Exact DR member name')
parser.add_argument('--zabbix-host', help='Technical Zabbix host name; defaults to scope')
parser.add_argument('--expected-nodes', type=int, default=3)
args = parser.parse_args()
if bool(args.scope) != bool(args.dr_member):
    parser.error('--scope and --dr-member must be provided together')
if args.zabbix_host and not args.scope:
    parser.error('--zabbix-host requires --scope')
if args.expected_nodes < 1:
    parser.error('--expected-nodes must be positive')
if args.scope and (len(args.scope) > 92 or not re.fullmatch(r'[A-Za-z0-9_.-]+', args.scope)):
    parser.error('--scope must be 1-92 letters, digits, dots, underscores or hyphens')
for value in (args.dr_member, args.zabbix_host):
    if value is not None and (not value.strip() or len(value) > 160):
        parser.error('Member and host names must be nonempty and at most 160 characters')
target = Path(args.config)
data = json.loads(target.read_text(encoding='utf-8-sig'))
addition = json.loads(Path(__file__).with_name('replication.json').read_text(encoding='utf-8'))['pairs'][0]
if args.scope:
    addition.update(id='patroni-' + args.scope, name=args.scope.upper(),
                    patroni_scope=args.scope, standby=args.dr_member,
                    zabbix_host=args.zabbix_host or args.scope)
addition['expected_patroni_nodes'] = args.expected_nodes
if any(p['id'] == addition['id'] for p in data['pairs']):
    print(addition['name'], 'already configured; no changes made.')
else:
    backup = target.with_name(target.name + '.bak-' + str(time.time_ns()))
    shutil.copy2(target, backup)
    data['pairs'].append(addition)
    # Write in-place so existing Docker bind mounts continue to see this file.
    target.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print('Added', addition['name'], 'Backup:', backup)
