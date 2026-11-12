"""Topology-aware Patroni monitoring; lag from /cluster is measured in bytes."""
import json


def build_patroni(pair, items, now):
    from app.services.replication import ItemMapping, metric_value, pair_status
    mapping = pair.metrics.get('topology')
    item = items.get(mapping.itemid) if mapping else None
    members, clock, reason = [], None, 'Topology unavailable'
    try:
        if not item or str(item.get('status')) != '0' or str(item.get('state')) != '0':
            raise ValueError()
        clock = int(item['lastclock'])
        if clock <= 0 or clock > now + 60:
            raise ValueError()
        data = json.loads(item['lastvalue'])
        if not isinstance(data, dict) or data.get('scope') != pair.patroni_scope or not isinstance(data.get('members'), list):
            raise ValueError()
        members = data['members']
        if not members or len(members) > 100 or any(not isinstance(m, dict) or not isinstance(m.get('name'), str) for m in members):
            raise ValueError()
        if len({m['name'] for m in members}) != len(members):
            raise ValueError()
        reason = ''
    except (ValueError, TypeError, KeyError):
        members, clock = [], None
    metrics = []

    def metric(key, label, value, unit='', healthy=None, warning=None, critical=None):
        source = dict(status='0', state='0', lastclock=clock, lastvalue=value) if clock and value is not None else None
        result = metric_value(key, (label, unit, warning, critical, healthy), ItemMapping(itemid='1'), source, now, pair.stale_after_seconds)
        metrics.append(result)
        return result

    leaders = [m for m in members if m.get('role') == 'leader']
    leader = leaders[0] if len(leaders) == 1 else None
    metric('leader_count', 'Exactly one Leader', 'ok' if leader else 'error' if members else None, healthy={'ok'})
    metric('member_count', 'Expected members present', 'ok' if len(members) == pair.expected_patroni_nodes else 'error' if members else None, healthy={'ok'})
    metric('dr_present', 'DR member present', 'ok' if any(m['name'] == pair.standby for m in members) else 'error' if members else None, healthy={'ok'})
    nodes = []
    for member in members:
        name, role = member['name'], member.get('role', '')
        state = member.get('state', '')
        metric(name + '.role', name.upper() + ' role recognized', 'ok' if role in ('leader', 'replica', 'sync_standby', 'quorum_standby') else 'error', healthy={'ok'})
        status = metric(name + '.state', name.upper() + ' state', state if state in ('running', 'streaming') else 'error', healthy={'running'} if role == 'leader' else {'streaming'})
        timeline_status = metric(name + '.timeline', name.upper() + ' timeline matches Leader', 'ok' if leader and type(member.get('timeline')) is int and member['timeline'] == leader.get('timeline') else 'error' if leader else None, healthy={'ok'})
        node = {k: member.get(k) for k in ('name', 'host', 'role', 'state', 'timeline', 'receive_lsn', 'replay_lsn', 'tags')}
        node['is_dr'] = name == pair.standby
        node_metrics = [status, timeline_status]
        if role != 'leader':
            for field in ('receive_lag', 'replay_lag'):
                value = member.get(field)
                if type(value) is not int or value < 0:
                    value = None
                node[field] = value
                key = 'wal_backlog' if node['is_dr'] and field == 'replay_lag' else name + '.' + field
                node_metrics.append(metric(key, ('DR ' if node['is_dr'] else name.upper() + ' ') + field.replace('_', ' '), value, 'bytes', warning=104857600, critical=1073741824))
        node['status'] = pair_status(node_metrics)
        nodes.append(node)
    if not any(m['key'] == 'wal_backlog' for m in metrics):
        metric('wal_backlog', 'DR replay backlog', None, 'bytes')
    return dict(id=pair.id, name=pair.name, engine='postgresql', title='PostgreSQL · Patroni',
                primary=leader['name'] if leader else 'Unknown Leader', standby=pair.standby,
                environment=pair.environment, schedule='', stale_after_seconds=pair.stale_after_seconds,
                status=pair_status(metrics), metrics=metrics, oldest_measurement=clock,
                trend=[], trend_key='wal_backlog', trend_error=None, patroni=True,
                topology=nodes, topology_error=reason, scope=pair.patroni_scope)
