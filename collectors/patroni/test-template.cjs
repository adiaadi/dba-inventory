const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const template = JSON.parse(fs.readFileSync(path.join(__dirname, 'zabbix-template-8.0.json'), 'utf8')).zabbix_export.templates[0];
const macros = Object.fromEntries(template.macros.map(m => [m.macro, m.value]));
function run(key, data) {
  const item = template.items.find(i => i.key === 'db.replication.patroni.' + key);
  let code = item.preprocessing[0].parameters[0];
  for (const [macro, value] of Object.entries(macros)) code = code.split(macro).join(value);
  return new Function('value', code)(JSON.stringify(data));
}
const data = {scope: 'aml-prod-cluster', members: [
  {name: 'aml-prod-db01', role: 'sync_standby', state: 'streaming', timeline: 123},
  {name: 'aml-prod-db02', role: 'leader', state: 'running', timeline: 123},
  {name: 'aml-prod-drdb', role: 'replica', state: 'streaming', timeline: 123,
   receive_lag: 0, replay_lag: 0, receive_lsn: 'A75/A607FE88', replay_lsn: 'A75/A607FE88', tags: {nofailover: true, nosync: true}}
]};
assert.equal(run('leader', data), 'aml-prod-db02');
assert.equal(run('healthy_nodes', data), 3);
assert.equal(run('dr.replay_lag', data), 0);
assert.equal(run('dr.replay_lsn', data), 'A75/A607FE88');
assert.deepEqual(JSON.parse(run('raw', data)), data);
assert.throws(() => run('raw', {...data, scope: 'wrong'}));
assert.throws(() => run('local2.replay_lag', data)); // Leader has no replica lag: never report a fabricated zero.
data.members[0].role = 'leader'; data.members[1].role = 'sync_standby';
assert.equal(run('leader', data), 'aml-prod-db01');
data.members[1].role = 'leader';
assert.throws(() => run('leader', data));
assert.equal(run('leader_count', data), 2);
data.members[2].replay_lag = 'unknown';
assert.throws(() => run('dr.replay_lag', data));
data.members.pop();
assert.throws(() => run('dr.state', data));
assert.equal(run('healthy_nodes', data), 2);
const keys = template.items.map(i => i.key);
assert.equal(new Set(keys).size, keys.length);
console.log('Patroni preprocessing checks passed: topology, switchover, missing DR, unknown lag, scope and duplicate leaders.');

// Validate every export object, including groups and nested triggers.
const exported = JSON.parse(fs.readFileSync(path.join(__dirname, 'zabbix-template-8.0.json'), 'utf8'));
const uuids = [];
function checkUuids(value) {
  if (!value || typeof value !== 'object') return;
  for (const [key, child] of Object.entries(value)) {
    if (key === 'uuid') {
      assert.match(child, /^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/);
      uuids.push(child);
    } else checkUuids(child);
  }
}
checkUuids(exported);
assert.ok(uuids.length > 0);
assert.equal(new Set(uuids).size, uuids.length);
console.log(`Validated ${uuids.length} unique UUIDv4 identifiers.`);
