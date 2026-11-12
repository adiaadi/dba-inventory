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
5. Check host macros, especially `{$PATRONI.URL}` and `{$PATRONI.SCOPE}`.
6. Wait 30-60 seconds; inspect Latest data > Patroni: cluster snapshot,
   current leader, DR state, DR replay_lag and DR replay_lsn.

Default members: aml-prod-db01, aml-prod-db02, aml-prod-drdb.
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
- Local leader LSN/lag dependent items can be unsupported: Patroni omits replica
  fields for a leader. Missing/unknown values are not replaced with zero.
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
