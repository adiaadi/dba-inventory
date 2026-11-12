const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const template = JSON.parse(fs.readFileSync(path.join(__dirname, 'zabbix-template-8.0.json'), 'utf8')).zabbix_export.templates[0];
const example = JSON.parse(fs.readFileSync(path.join(__dirname, 'aml-host-macros.example.json'), 'utf8'));
const macros = Object.fromEntries(example.macros.map(m => [m.macro, m.value]));
for (const m of template.macros) {
  if (!['{$PATRONI.EXPECTED_NODES}', '{$PATRONI.LAG_WARN_BYTES}'].includes(m.macro)) assert.equal(m.value, '');
}
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
for (const field of ['receive_lag', 'replay_lag', 'receive_lsn', 'replay_lsn']) assert.equal(run('local2.' + field, data), null);
assert.throws(() => run('local1.replay_lag', data)); // Missing replica data must remain an error.
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

// The same template works with another cluster using only host macro overrides.
macros['{$PATRONI.SCOPE}'] = 'other-cluster';
macros['{$PATRONI.DR_MEMBER}'] = 'other-dr';
const other = {scope: 'other-cluster', members: [{name: 'other-primary', role: 'leader', state: 'running'}, {name: 'other-dr', role: 'replica', state: 'streaming', replay_lag: 42}]};
assert.equal(JSON.parse(run('raw', other)).scope, 'other-cluster');
assert.equal(run('leader', other), 'other-primary');
assert.equal(run('dr.replay_lag', other), 42);
console.log('Host macro overrides and leader-only sample discarding passed.');
