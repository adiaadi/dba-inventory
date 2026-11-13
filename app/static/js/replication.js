(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const labels = {healthy: 'HEALTHY', warning: 'WARNING', critical: 'CRITICAL', stale: 'STALE DATA', unknown: 'NO DATA'};
  let snapshot = null, receivedAt = 0, engine = null, selectedPair = null, paused = false, busy = false, timer, failed = false;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
  const date = clock => clock ? new Date(clock * 1000).toLocaleString() : 'No measurement';
  const badge = status => `<span class="replication-badge ${esc(status)}">${esc(labels[status] || status)}</span>`;
  const upper = value => String(value ?? '').toUpperCase();
  const logDate = clock => {
    if (!clock) return 'NO TIMESTAMP';
    const d = new Date(clock * 1000), pad = v => String(v).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };
  function formatted(metric) {
    if (!metric || metric.value === null) return '—';
    if (typeof metric.value === 'string') {
      const value = upper(metric.value);
      if (value === 'SUCCESS') return '<span class="replication-success">SUCCESS</span>';
      if (['FAILED', 'ERROR'].includes(value)) return '<span class="replication-error-text">ERROR</span>';
      return esc(value);
    }
    if (['archived_seq', 'copied_seq', 'applied_seq'].includes(metric.key)) return `#${esc(String(metric.value))}`;
    if (metric.unit === 'bytes') return `${number(metric.value / 1048576)} MB`;
    if (metric.unit === 's' && metric.value >= 60) return `${number(metric.value / 60)} min`;
    return `${number(metric.value)}${metric.unit ? ' ' + esc(metric.unit) : ''}`;
  }
  function metricBox(m) {
    return `<div class="replication-metric"><small>${esc(m.label)}</small><strong class="metric-${esc(m.status)}" title="${esc(m.reason)}">${formatted(m)}</strong></div>`;
  }
  function step(label, host, m) {
    return `<div class="replication-step"><small>${esc(label)}</small><strong>${esc(upper(host))}</strong><div class="step-value metric-${esc(m?.status)}">${formatted(m)}</div></div>`;
  }
  function terminal(pair) {
    const line = (clock, content) => `<div class="replication-log-line"><span class="replication-log-time">${esc(logDate(clock))} |</span> ${content}</div>`;
    const rows = [line(pair.oldest_measurement, `Database: ${esc(upper(pair.name))}`),
      line(pair.oldest_measurement, `Primary: ${esc(upper(pair.primary))} | Standby: ${esc(upper(pair.standby))}`)];
    pair.metrics.forEach(metric => {
      const status = metric.status === 'healthy' ? 'SUCCESS' : metric.status === 'critical' ? 'ERROR' : labels[metric.status] || 'NO DATA';
      const color = metric.status === 'healthy' ? 'replication-success' : metric.status === 'critical' ? 'replication-error-text' : 'replication-log-warning';
      rows.push(line(metric.clock, `${esc(metric.label)}: ${formatted(metric)} | <span class="${color}">${esc(status)}</span>${metric.reason ? ' | '+esc(metric.reason) : ''}`));
    });
    return `<div class="replication-terminal" role="region" aria-label="Latest replication measurements" tabindex="0"><div class="replication-terminal-title">$ replication status · Latest measurements · Local time${failed ? ' · CACHED / CONNECTION LOST' : ''}</div>${rows.join('')}</div>`;
  }
  function trend(pair, m) {
    const points = pair.trend;
    const period = 3600;
    const heading = `<div class="replication-caption">${esc(m.label)} · Last 60 min</div>`;
    if (pair.trend_error || points.length < 2) return heading + `<p class="small text-muted">${esc(pair.trend_error || 'Not enough history yet')}</p>`;
    const end = snapshot.fetched_at, start = end - period;
    const max = Math.max(1, ...points.map(p => p.value));
    const paths = [];
    points.forEach((p, i) => {
      const gap = i === 0 || p.clock - points[i-1].clock > 180;
      paths.push(`${gap ? 'M' : 'L'}${((p.clock-start)/period*300).toFixed(2)},${(100-p.value/max*90).toFixed(2)}`);
    });
    const color = pair.status === 'critical' ? '#df405a' : pair.status === 'healthy' ? '#00a67a' : '#c68a1a';
    return heading + `<svg viewBox="0 0 300 110" preserveAspectRatio="none" role="img" aria-label="${esc(m.label)} over the selected period"><path d="M0 10H300 M0 55H300 M0 100H300" stroke="#dce1e7" stroke-dasharray="3 4"/><path d="${paths.join(' ')}" fill="none" stroke="${color}" stroke-width="2.5"/></svg><div class="replication-trend-labels"><span>${esc(new Date(start*1000).toLocaleTimeString())}</span><span>Max ${number(max)} ${esc(m.unit)}</span><span>${esc(new Date(end*1000).toLocaleTimeString())}</span></div>`;
  }
  function renderSelector() {
    const engines = [['oracle', 'Oracle'], ['postgresql', 'PostgreSQL'], ['sqlserver', 'SQL Server']];
    const pairs = snapshot.pairs.filter(p => p.engine === engine).sort((a,b) => a.name.localeCompare(b.name));
    $('replication-selector').innerHTML = `<div class="replication-filters">${engines.map(([key,title]) => `<button type="button" data-engine="${key}" class="${engine === key ? 'active' : ''}" aria-pressed="${engine === key}">${title}</button>`).join('')}</div>${engine ? `<div class="replication-database-list" aria-label="Choose database">${pairs.length ? pairs.map(p => `<button type="button" data-engine="${engine}" data-pair="${esc(p.id)}" class="${selectedPair === p.id ? 'selected' : ''}" aria-pressed="${selectedPair === p.id}">${esc(upper(p.name))}</button>`).join('') : '<span>No databases configured</span>'}</div>` : ''}`;
  }
  function engineIcon(engine) {
    const engines = {oracle: ['oracle.png', 'Oracle'], postgresql: ['postgresql.png', 'PostgreSQL'], sqlserver: ['sqlserver.png', 'SQL Server']};
    const entry = engines[engine];
    return entry ? `<img class="replication-engine-icon" src="/static/img/${entry[0]}" alt="${entry[1]}">` : '';
  }
  function architecture(pair) {
    const cylinder = `<svg class="architecture-icon" viewBox="0 0 100 100" aria-hidden="true"><path d="M15 22v55c0 19 70 19 70 0V22" fill="#cfe6f7" stroke="#3679a4" stroke-width="2"/><ellipse cx="50" cy="22" rx="35" ry="13" fill="#eaf6ff" stroke="#3679a4" stroke-width="2"/><path d="M15 43c0 18 70 18 70 0M15 61c0 18 70 18 70 0" fill="none" stroke="#3679a4" stroke-width="2"/></svg>`;
    const logs = `<svg class="architecture-icon" viewBox="0 0 100 100" aria-hidden="true"><path d="M30 12h44l12 12v57H30z" fill="#fff2d9" stroke="#b5760c" stroke-width="2"/><path d="M17 25h44l12 12v56H17z" fill="#fff8eb" stroke="#b5760c" stroke-width="2"/><path d="M28 49h33M28 60h33M28 71h24" stroke="#b5760c" stroke-width="3"/></svg>`;
    const specs = {
      oracle: ['Archive log replication status', 'Production database', 'Archived logs', 'Cron · rsync over SSH', 'Verified archive copies', 'RMAN · catalog + recover', 'Physical standby', 'Mounted · redo applied'],
      postgresql: ['Streaming replication', 'Primary database', 'WAL records', 'Asynchronous WAL stream', 'Standby WAL', 'WAL replay', 'Standby database', 'Patroni manages cluster roles'],
      sqlserver: ['Log shipping', 'Primary database', 'Transaction log backup', 'Scheduled copy job', 'Copied log backups', 'Scheduled restore job', 'Secondary database', 'Log backups restored']
    };
    const [title, source, sourceNote, transfer, copies, apply, target, targetNote] = specs[pair.engine];
    const m = Object.fromEntries(pair.metrics.map(metric => [metric.key, metric]));
    const value = key => `<div class="architecture-live metric-${esc(m[key]?.status)}">${formatted(m[key])}</div>`;
    const file = !failed && m.copied_seq?.clock && snapshot && snapshot.fetched_at + (performance.now() - receivedAt) / 1000 - m.copied_seq.clock <= pair.stale_after_seconds && pair.archive_file ? `<div class="archive-file"><strong>Archivelog: ${esc(pair.archive_file.name)}</strong></div>` : '<div class="archive-file">File details unavailable</div>';
    const stats = pair.transfer_stats;
    const statsFresh = !failed && stats && snapshot && snapshot.fetched_at + (performance.now() - receivedAt) / 1000 - stats.completed_at <= pair.stale_after_seconds;
    const lastCopy = stats?.last_copy || (stats?.attempts > 0 && stats.bytes_received > 0 ? stats : null);
    const transferText = !statsFresh ? (pair.transfer_stats_configured === false ? 'Transfer metric not configured' : 'Copy speed / time: no recent data') :
      `${stats.attempts === 0 ? 'No new files · Last cycle<br>' : ''}${lastCopy ? `Last copy: ${number(lastCopy.bytes_per_second / 1048576)} MiB/s<br>Copy time: ${number(lastCopy.duration_seconds)} s<br>${esc(date(lastCopy.completed_at))}` : 'Waiting for a measured transfer'}`;
    const stageActive = key => !failed && !paused && m[key]?.status === 'healthy' && m[key]?.clock && snapshot &&
      snapshot.fetched_at + (performance.now() - receivedAt) / 1000 - m[key].clock <= pair.stale_after_seconds;
    const arrow = (label, key) => `<div class="architecture-link ${stageActive(key) ? 'architecture-active' : !failed && m[key]?.status === 'critical' ? 'architecture-error' : ''}"><span>${esc(label)}</span>${key ? value(key) : ''}${pair.engine === 'oracle' && key === 'transfer_job' ? `<small class="copy-speed">${transferText}</small>` : ''}<div class="architecture-track" aria-hidden="true"><i></i><b>▶</b></div></div>`;
    return `<section class="replication-architecture" aria-label="Replication architecture"><div class="architecture-heading">${pair.engine === 'oracle' ? `<div class="oracle-heading-title"><h2>${esc(title)}</h2><span>${esc(upper(pair.name))} · Primary → DR site</span></div>` : `<h2>${esc(title)}</h2><span>${esc(upper(pair.name))} · Primary → DR site</span>`}<div class="architecture-brand-status">${engineIcon(pair.engine)}${badge(failed ? 'stale' : pair.status)}</div></div><div class="architecture-flow"><div class="architecture-node site-main"><small class="replication-site-label">MAIN SITE</small>${cylinder}<strong>${esc(upper(pair.primary))}</strong><b>${esc(upper(pair.name))}</b><span>${esc(source)}</span><em>${esc(sourceNote)}</em>${value(pair.engine === 'oracle' ? 'archived_seq' : pair.engine === 'postgresql' ? 'leader_lock' : 'backup_age')}</div>${arrow(transfer, pair.engine === 'oracle' ? 'transfer_job' : pair.engine === 'postgresql' ? 'stream_state' : 'copy_job')}<div class="architecture-node architecture-archives">${logs}<strong>${esc(copies)}</strong>${pair.engine === 'oracle' ? '<em>Sequence / SCN + SHA-256 audit</em>' : ''}${value(pair.engine === 'oracle' ? 'copied_seq' : pair.engine === 'postgresql' ? 'wal_backlog' : 'copy_age')}${pair.engine === 'oracle' ? file : ''}</div>${arrow(apply, pair.engine === 'oracle' ? 'apply_job' : pair.engine === 'postgresql' ? 'replica_state' : 'restore_job')}<div class="architecture-node site-dr"><small class="replication-site-label">DR SITE · DATABASE</small>${cylinder}<strong>${esc(upper(pair.standby))}</strong><b>${esc(upper(pair.name))}</b><span>${esc(target)}</span><em>${esc(targetNote)}</em>${value(pair.engine === 'oracle' ? 'applied_seq' : pair.engine === 'postgresql' ? 'replay_lag' : 'restore_age')}</div></div>${pair.engine === 'oracle' ? '' : `<div class="architecture-counters">${(pair.engine === 'postgresql' ? ['sync_state','patroni_nodes'] : ['pending_files']).map(key => `<span>${esc(m[key]?.label || key)}: <strong>${formatted(m[key])}</strong></span>`).join('')}</div>`}</section>`;
  }
  function healthPanel(pair) {
    const m = Object.fromEntries(pair.metrics.map(metric => [metric.key, metric]));
    const keys = pair.engine === 'oracle' ? ['transfer_job', 'apply_job', 'archive_gap', 'pending_apply', 'last_success_age'] : pair.engine === 'postgresql' ? ['stream_state', 'replica_state'] : ['backup_job', 'copy_job', 'restore_job'];
    const heading = pair.engine === 'oracle' ? 'Cron job & apply health' : 'Replication health';
    return `<aside class="replication-health replication-side-health"><div class="replication-health-heading"><h4>${heading}</h4>${badge(failed ? 'stale' : pair.status)}</div><div class="replication-health-row"><span>Cron schedule</span><span>${esc(pair.schedule || 'Not configured')}</span></div>${keys.map(key => `<div class="replication-health-row"><span>${esc(m[key]?.label || key)}</span><span>${formatted(m[key])}</span></div>`).join('')}<div class="replication-trend">${trend(pair, m[pair.trend_key])}</div></aside>`;
  }
  function patroniCard(pair) {
    const stale = failed || ['stale','unknown'].includes(pair.status);
    const nodes = pair.topology || [];
    const leader = nodes.find(n => n.role === 'leader');
    const node = n => `<div class="architecture-node patroni-node ${n.is_dr ? 'site-dr' : 'site-main'}"><small class="replication-site-label">${n.is_dr ? 'DR SITE' : 'MAIN SITE'}</small><strong>${esc(upper(n.name))}</strong><b>${esc(upper(n.role).replaceAll('_',' '))}</b>${badge(stale ? 'stale' : n.status)}<span>${esc(n.host || '')} · Timeline ${esc(n.timeline ?? '—')}</span><span class="patroni-state ${stale ? 'patroni-state-stale' : ['running','streaming'].includes(n.state) ? 'patroni-state-ok' : ['stopped','failed','crashed','start failed','restart failed'].includes(n.state) ? 'patroni-state-error' : 'patroni-state-warning'}">${esc(upper(n.state || 'Unknown'))}</span></div>`;
    const replicas = nodes.filter(n => n.role !== 'leader');
    const mode = n => ['sync_standby','quorum_standby'].includes(n.role) ? 'SYNC' : n.role === 'replica' ? 'ASYNC' : 'UNKNOWN';
    const connectors = leader && replicas.length ? `<svg class="patroni-connectors" viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label="Leader to replicas">${replicas.map((n,i) => {
      const x = (i + .5) * 1000 / replicas.length;
      const route = `M500 0 V24 H${x} V92`;
      const fresh = !failed && snapshot && pair.oldest_measurement && snapshot.fetched_at + (performance.now() - receivedAt) / 1000 - pair.oldest_measurement <= pair.stale_after_seconds;
      const broken = fresh && (leader.status === 'critical' || n.status === 'critical');
      const active = fresh && !paused && !stale && leader.status === 'healthy' && n.status === 'healthy';
      return `<g class="${broken ? 'patroni-flow-error' : active ? 'patroni-flow-active' : ''}"><path class="patroni-flow-line" d="${route}"/><path class="patroni-flow-packet" d="${route}" pathLength="100"/><path class="patroni-flow-head" d="M${x-6} 88 L${x} 100 L${x+6} 88 Z"/></g>`;
    }).join('')}</svg>` : '';
    const flow = `<section class="replication-architecture"><div class="architecture-heading"><div class="patroni-heading-title"><h2>Patroni replication status</h2><span>${esc(upper(pair.scope))}${pair.vip ? ` · VIP: ${esc(pair.vip)}` : ''}</span></div><div class="architecture-brand-status">${engineIcon(pair.engine)}${badge(pair.status)}</div></div>${leader ? `<div class="patroni-leader">${node(leader)}</div>` : '<div class="replication-empty">No unique Leader available</div>'}<div class="patroni-distribution">${connectors}<div class="patroni-branches" style="--replicas:${Math.max(1,replicas.length)}">${replicas.map(n => `<div class="patroni-branch"><div class="patroni-mode">${esc(mode(n))}</div>${node(n)}</div>`).join('')}</div></div></section>`;
    const backlog = pair.metrics.find(m => m.key === 'wal_backlog');
    const replicaDetails = replicas.map(n => `<section class="patroni-replica-details"><h5>${esc(upper(n.name))} · ${esc(mode(n))}${stale ? ' · STALE DATA' : ''}</h5><div class="replication-health-row"><span>Receive LSN</span><strong>${esc(n.receive_lsn || '—')}</strong></div><div class="replication-health-row"><span>Replay LSN</span><strong>${esc(n.replay_lsn || '—')}</strong></div><div class="replication-health-row"><span>Receive lag</span><strong>${n.receive_lag == null ? '—' : number(n.receive_lag)+' B'}</strong></div><div class="replication-health-row"><span>Replay lag</span><strong>${n.replay_lag == null ? '—' : number(n.replay_lag)+' B'}</strong></div></section>`).join('');
    const health = `<aside class="replication-health replication-side-health"><div class="replication-health-heading"><h4>Patroni & DR health</h4>${badge(pair.status)}</div><div class="replication-health-row"><span>Current Leader</span><strong>${esc(upper(pair.primary))}</strong></div><div class="replication-health-row"><span>Reported members</span><strong>${nodes.length}</strong></div><div class="replication-health-row"><span>DR replay backlog</span><strong>${formatted(backlog)}</strong></div>${replicaDetails}</aside>`;
    return `<div class="replication-status-layout patroni-status-layout">${flow}${health}<section class="replication-measurements"><h4>Measurement details · ${esc(date(pair.oldest_measurement))}</h4>${terminal(pair)}</section></div>`;
  }
  function card(pair) {
    if (pair.patroni) return patroniCard(pair);
    return `<div class="replication-status-layout ${pair.engine === 'oracle' ? 'oracle-status-layout' : ''}">${architecture(pair)}${healthPanel(pair)}<section class="replication-measurements" aria-label="Measurement details"><h4>Measurement details · oldest: ${esc(date(pair.oldest_measurement))}</h4>${terminal(pair)}</section></div>`;
  }
  function overview(pairs) {
    pairs = pairs.filter(pair => pair.engine !== 'postgresql');
    const shownStatus = p => failed ? 'stale' : p.status;
    const counts = [
      ['Databases on DR', pairs.length, ''],
      ['Healthy', pairs.filter(p => shownStatus(p) === 'healthy').length, 'healthy'],
      ['Need attention', pairs.filter(p => ['warning','critical'].includes(shownStatus(p))).length, 'critical'],
      ['No data / stale', pairs.filter(p => ['unknown','stale'].includes(shownStatus(p))).length, 'unknown']
    ];
    const engines = {oracle:'Oracle', postgresql:'PostgreSQL', sqlserver:'SQL Server'};
    const rows = [...pairs].sort((a,b) => a.name.localeCompare(b.name)).map(pair => {
      const m = Object.fromEntries(pair.metrics.map(metric => [metric.key,metric]));
      const fresh = metric => !failed && metric && !['unknown','stale'].includes(metric.status) && metric.value !== null;
      const success = m.last_success_age;
      const last = fresh(success) && success.clock && success.value >= 0 && success.value <= success.clock ? `${esc(date(success.clock-success.value))}<small>${formatted(success)} at measurement</small>` : '—';
      const lagKeys = pair.engine === 'oracle' ? ['archive_gap','pending_apply'] : pair.engine === 'postgresql' ? (pair.patroni ? ['wal_backlog'] : ['replay_lag','wal_backlog']) : ['restore_age','pending_files'];
      const lag = lagKeys.map(key => `<div>${esc(m[key]?.label || key)}: <strong>${fresh(m[key]) ? formatted(m[key]) : '—'}</strong></div>`).join('');
      return `<tr data-open-pair="${esc(pair.id)}" data-open-engine="${esc(pair.engine)}"><td><button type="button" class="replication-database-link" aria-label="Open ${esc(upper(pair.name))} replication">${esc(upper(pair.name))}</button><small>${engines[pair.engine] || esc(pair.engine)}</small></td><td><strong>${esc(upper(pair.primary))}</strong><small>→ ${esc(upper(pair.standby))}</small></td><td>${badge(shownStatus(pair))}</td><td>${last}</td><td>${lag}</td></tr>`;
    }).join('');
    return `<section class="replication-overview"><h3>DR replication overview</h3><p class="replication-overview-hint">Select a database engine, then a database — or click a row below to open its replication diagram.</p><div class="replication-overview-summary">${counts.map(([label,count,status]) => `<div class="replication-stat ${status}"><span>${label}</span><strong>${count}</strong></div>`).join('')}</div>${pairs.length ? `<div class="replication-table-scroll"><table class="replication-overview-table"><thead><tr><th>Database</th><th>Primary → Standby</th><th>Status</th><th>Last successful cycle</th><th>Lag / backlog</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="replication-empty">No databases configured for this selection.</div>'}<p class="replication-overview-hint">Replication health does not confirm readiness for DR failover. “—” means the measurement is unavailable or stale.</p></section>`;
  }
  function render() {
    if (!snapshot) return;
    const candidates = snapshot.pairs.filter(p => p.engine === engine);
    if (!candidates.some(p => p.id === selectedPair)) selectedPair = null;
    renderSelector();
    $('dr-overview').hidden = !engine;
    const now = snapshot.fetched_at + (performance.now() - receivedAt) / 1000;
    const allPairs = snapshot.pairs.map(pair => {
      const metrics = pair.metrics.map(m => m.clock && now - m.clock > pair.stale_after_seconds ? {...m, status:'stale', reason:'Source measurement is stale'} : m);
      const status = ['critical','stale','unknown','warning'].find(s=>metrics.some(m=>m.status===s)) || 'healthy';
      return {...pair, metrics, status};
    });
    const pairs = allPairs.filter(p => p.id === selectedPair && p.engine === engine);
    $('replication-pairs').innerHTML = pairs.length ? pairs.map(card).join('') : engine === 'postgresql' ? `<div class="replication-empty">${candidates.length ? 'Select a PostgreSQL cluster above to view its replication diagram.' : 'No PostgreSQL clusters configured.'}</div>` : overview(allPairs.filter(p => !engine || p.engine === engine));
    $('snapshot-time').textContent = `Last fetch: ${date(snapshot.fetched_at)}${failed ? ' · Cached display' : ''}`;
  }
  function schedule() {
    clearTimeout(timer);
    if (!paused && !document.hidden) timer = setTimeout(refresh, Number($('poll-interval').value)*1000);
  }
  async function refresh() {
    if (busy) return;
    busy = true; $('refresh-poll').disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(()=>controller.abort(), 45000);
    $('poll-status').textContent = 'Refreshing…';
    try {
      const response = await fetch('/replication/api', {signal:controller.signal, cache:'no-store', headers:{Accept:'application/json'}});
      if (response.redirected || response.status === 401) throw new Error('Session expired. Sign in again.');
      if (!response.ok) throw new Error('Monitoring endpoint unavailable.');
      snapshot = await response.json(); receivedAt = performance.now(); failed = false;
      $('replication-error').hidden = !snapshot.error;
      $('replication-error').textContent = snapshot.error || '';
      $('poll-status').textContent = snapshot.error ? 'Source unavailable' : paused ? 'Paused' : 'Polling enabled';
    } catch (error) {
      failed = true; $('replication-error').hidden = false;
      $('replication-error').textContent = `${error.name === 'AbortError' ? 'Request timed out.' : error.message} Displayed measurements are not current.`;
      $('poll-status').textContent = 'Connection lost';
      if (!snapshot) $('replication-pairs').innerHTML = '<div class="replication-empty">Monitoring is unavailable. Use Refresh to retry.</div>';
    } finally {
      clearTimeout(timeout); busy = false; $('refresh-poll').disabled = false; render(); schedule();
    }
  }
  $('replication-selector').addEventListener('click', event => {
    const button = event.target.closest('button[data-engine]');
    if (!button) return;
    engine = button.dataset.engine;
    selectedPair = button.dataset.pair || null;
    render();
  });
  $('dr-overview').addEventListener('click', () => {
    engine = null; selectedPair = null; render();
  });
  $('replication-pairs').addEventListener('click', event => {
    const row = event.target.closest('[data-open-pair]');
    if (!row) return;
    engine = row.dataset.openEngine; selectedPair = row.dataset.openPair;
    render();
  });
  $('refresh-poll').addEventListener('click',refresh);
  $('poll-interval').addEventListener('change',schedule);
  $('pause-poll').addEventListener('click',()=>{
    paused=!paused; $('pause-poll').textContent=paused?'Resume':'Pause'; $('pause-poll').setAttribute('aria-pressed',String(paused));
    $('poll-status').textContent=paused?'Paused · measurements will age':'Polling enabled';
    render();
    if (paused) schedule(); else refresh();
  });
  document.addEventListener('visibilitychange',()=>{ if (document.hidden) clearTimeout(timer); else if (!paused) refresh(); });
  // Age paused/failed snapshots without waiting for another successful network call.
  setInterval(()=>{ if (snapshot && !document.hidden && (paused || failed)) render(); }, 10000);
  refresh();
})();
