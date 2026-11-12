# Patroni cluster monitoring through Zabbix HTTP agent

Initial collection template for Zabbix 8.0. No PostgreSQL credentials, local
collector, UserParameter, cron or Patroni configuration changes are needed.
Only GET /cluster is called. Oracle configurations are unchanged.

## Install

1. From the Zabbix server or the proxy assigned to the host, verify:
   `curl -fsS --max-time 10 http://10.210.120.71:8008/cluster`
2. Import `zabbix-template-8.0.json` in Data collection > Templates.
3. Create a dedicated enabled host with technical Host name
   `aml-prod-cluster` (or use an existing host and record its exact technical
   name). Assign the reachable server/proxy. An agent interface is not required.
4. Link template `DB Inventory Patroni cluster HTTP`.
5. Set the five required host macros listed below; the template defaults are empty.
6. Wait 30-60 seconds; inspect Latest data > Patroni: cluster snapshot,
   current leader, DR state, DR replay_lag and DR replay_lsn.

## Required host macros and upgrading AML

Before importing this update, define these overrides on host `aml-prod-cluster`
(not on the template), so clearing the template defaults does not interrupt AML:

| Macro | AML host value |
| --- | --- |
| `{$PATRONI.URL}` | `http://10.210.120.71:8008` (or your verified VIP API URL) |
| `{$PATRONI.SCOPE}` | `aml-prod-cluster` |
| `{$PATRONI.LOCAL1}` | `aml-prod-db01` |
| `{$PATRONI.LOCAL2}` | `aml-prod-db02` |
| `{$PATRONI.DR_MEMBER}` | `aml-prod-drdb` |

`aml-host-macros.example.json` is a reference, not a Zabbix import file.
Keep any already configured VIP override. Import the updated template with
Update existing enabled, Delete missing disabled. UUIDs are unchanged.
Template defaults retain expected node count 3 and lag threshold 104857600 bytes;
these can also be overridden per host. For another cluster, link this same
template to a new logical host and define its own five macros.
This template supports two local members plus one DR; arbitrary member counts
require a future discovery-based template (LLD).

The current leader is discovered by role, never pinned to db02.
Macros LOCAL1 and LOCAL2 identify machines, not permanent roles.
The raw snapshot retains complete topology and tags for subsequent portal
integration. The scope is a cluster name, not an individual database name.

## Meaning and limitations

- receive_lag/replay_lag from /cluster are bytes, NOT seconds. Never map them
  into the portal's existing replay_lag metric in seconds.
- Running/streaming node count is reported cluster state, not an independent
  SQL or network probe of every member. /cluster uses Patroni's cluster view;
  it does not prove direct WAL streaming source or DR failover readiness.
- Local leader LSN/lag samples are discarded because these fields apply to replicas.
  Previous historical values may remain: always check current role and timestamp.
  Missing/unknown fields on a replica still raise an error, never a fabricated zero.
- No direct leader-lock confirmation is inferred from the role label.
- DR flags nofailover/nosync/noloadbalance are retained as tags, not failures.
- The single API source is independent of leader identity, but has no endpoint
  failover. If db01 API is unreachable, collection fails and the no-data trigger
  fires after 3 minutes. A reachable alternative can be set in PATRONI.URL.
- Defaults alert on leader count != 1, fewer than 3 running/streaming nodes,
  DR not streaming, or DR replay backlog >100 MiB for 3 minutes. Tune the lag
  threshold to operational requirements; it is not an RPO commitment.
- This package does not yet activate the portal's PostgreSQL page. That requires
  a topology-aware adapter rather than the existing generic seconds-based
  mappings. Record the Zabbix technical host name when connecting it.

## Checks

Run `node collectors/patroni/test-template.cjs` from the repository root.
The test executes actual template preprocessing with representative cluster
responses, including switchover, missing member and unknown lag.
A live Zabbix import and endpoint connectivity must be verified on deployment.

Reference: https://patroni.readthedocs.io/en/latest/rest_api.html
