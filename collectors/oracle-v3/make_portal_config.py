"""Generate a CBSETL portal pair from item.get output scoped to ONE Zabbix host."""
import argparse
import json
from pathlib import Path

KEYS=('archived_seq','copied_seq','applied_seq','archive_gap','pending_apply',
      'last_success_age','transfer_job','apply_job')


def build(data, services=None):
    rows=data.get('result') if isinstance(data,dict) else data
    if not isinstance(rows,list): raise ValueError('Expected item.get result array')
    selected=[]
    metrics={}
    for key in KEYS:
        matches=[r for r in rows if r.get('key_')=='db.replication.oracle.'+key]
        if len(matches)!=1: raise ValueError('Missing or duplicate item: '+key)
        row=matches[0];value=str(row.get('itemid',''))
        if not value.isdecimal() or int(value)<=0: raise ValueError('Invalid itemid for '+key)
        selected.append(row)
        metrics[key]={'itemid':value}
    if len({m['itemid'] for m in metrics.values()})!=len(KEYS):
        raise ValueError('Duplicate itemid')
    hosts={str(r['hostid']) for r in selected if 'hostid' in r}
    if len(hosts)>1: raise ValueError('Export exactly one host')
    metrics['archive_gap'].update(warning=1,critical=10)
    metrics['pending_apply'].update(warning=1,critical=10)
    metrics['last_success_age'].update(warning=600,critical=1800)
    return {'pairs':[dict(id='oracle-cbsetl-thread1',name='CBSETL / thread 1',engine='oracle',
        primary='cbs-prod-db',standby='cbs-dr-db',environment='production',
        schedule='Every 3 min (01,04,...,58)',stale_after_seconds=180,metrics=metrics)]}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('items')
    p.add_argument('--service',action='append',default=[])
    args=p.parse_args()
    try:
        result=build(json.loads(Path(args.items).read_text(encoding='utf-8-sig')),args.service)
    except (ValueError,OSError,TypeError) as exc:
        p.exit(1,str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
