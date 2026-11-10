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
    const heading = `<div class="replication-caption">${esc(m.label)} · Last 60 min</div>`;
    if (pair.trend_error || points.length < 2) return heading + `<p class="small text-muted">${esc(pair.trend_error || 'Not enough history yet')}</p>`;
    const end = snapshot.fetched_at, start = end - 3600;
    const max = Math.max(1, ...points.map(p => p.value));
    const paths = [];
    points.forEach((p, i) => {
      const gap = i === 0 || p.clock - points[i-1].clock > 180;
      paths.push(`${gap ? 'M' : 'L'}${((p.clock-start)/3600*300).toFixed(2)},${(100-p.value/max*90).toFixed(2)}`);
    });
    const color = pair.status === 'critical' ? '#df405a' : pair.status === 'healthy' ? '#00a67a' : '#c68a1a';
    return heading + `<svg viewBox="0 0 300 110" role="img" aria-label="${esc(m.label)} over the last hour"><path d="M0 10H300 M0 55H300 M0 100H300" stroke="#dce1e7" stroke-dasharray="3 4"/><path d="${paths.join(' ')}" fill="none" stroke="${color}" stroke-width="2.5"/></svg><div class="replication-trend-labels"><span>${esc(new Date(start*1000).toLocaleTimeString())}</span><span>Max ${number(max)} ${esc(m.unit)}</span><span>${esc(new Date(end*1000).toLocaleTimeString())}</span></div>`;
  }
  function renderSelector() {
    const engines = [['oracle', 'Oracle'], ['postgresql', 'PostgreSQL'], ['sqlserver', 'SQL Server']];
    const pairs = snapshot.pairs.filter(p => p.engine === engine).sort((a,b) => a.name.localeCompare(b.name));
    $('replication-selector').innerHTML = `<div class="replication-filters">${engines.map(([key,title]) => `<button type="button" data-engine="${key}" class="${engine === key ? 'active' : ''}" aria-pressed="${engine === key}">${title}</button>`).join('')}</div>${engine ? `<div class="replication-database-list" aria-label="Choose database">${pairs.length ? pairs.map(p => `<button type="button" data-engine="${engine}" data-pair="${esc(p.id)}" class="${selectedPair === p.id ? 'selected' : ''}" aria-pressed="${selectedPair === p.id}">${esc(upper(p.name))}</button>`).join('') : '<span>No databases configured</span>'}</div>` : ''}`;
  }
  function architecture(pair) {
    const cylinder = `<svg class="architecture-icon" viewBox="0 0 100 100" aria-hidden="true"><path d="M15 22v55c0 19 70 19 70 0V22" fill="#cfe6f7" stroke="#3679a4" stroke-width="2"/><ellipse cx="50" cy="22" rx="35" ry="13" fill="#eaf6ff" stroke="#3679a4" stroke-width="2"/><path d="M15 43c0 18 70 18 70 0M15 61c0 18 70 18 70 0" fill="none" stroke="#3679a4" stroke-width="2"/></svg>`;
    const logs = `<svg class="architecture-icon" viewBox="0 0 100 100" aria-hidden="true"><path d="M30 12h44l12 12v57H30z" fill="#fff2d9" stroke="#b5760c" stroke-width="2"/><path d="M17 25h44l12 12v56H17z" fill="#fff8eb" stroke="#b5760c" stroke-width="2"/><path d="M28 49h33M28 60h33M28 71h24" stroke="#b5760c" stroke-width="3"/></svg>`;
    const specs = {
      oracle: ['Archive log replication', 'Production database', 'Archived logs', 'Cron · rsync over SSH', 'Verified archive copies', 'RMAN · catalog + recover', 'Physical standby', 'Mounted · redo applied'],
      postgresql: ['Streaming replication', 'Primary database', 'WAL records', 'Asynchronous WAL stream', 'Standby WAL', 'WAL replay', 'Standby database', 'Patroni manages cluster roles'],
      sqlserver: ['Log shipping', 'Primary database', 'Transaction log backup', 'Scheduled copy job', 'Copied log backups', 'Scheduled restore job', 'Secondary database', 'Log backups restored']
    };
    const [title, source, sourceNote, transfer, copies, apply, target, targetNote] = specs[pair.engine];
    const active = !failed && !paused && pair.status === 'healthy';
    const m = Object.fromEntries(pair.metrics.map(metric => [metric.key, metric]));
    const value = key => `<div class="architecture-live metric-${esc(m[key]?.status)}">${formatted(m[key])}</div>`;
    const arrow = (label, key) => `<div class="architecture-link"><span>${esc(label)}</span>${key ? value(key) : ''}<div class="architecture-track" aria-hidden="true"><i></i><b>▶</b></div></div>`;
    return `<section class="replication-architecture ${active ? 'architecture-active' : ''}" aria-label="Replication architecture"><div class="architecture-heading"><h2>${esc(title)}</h2><span>${esc(upper(pair.name))} · Primary → DR site</span>${badge(failed ? 'stale' : pair.status)}</div><div class="architecture-flow"><div class="architecture-node"><small>PRODUCTION</small>${cylinder}<strong>${esc(upper(pair.primary))}</strong><b>${esc(upper(pair.name))}</b><span>${esc(source)}</span><em>${esc(sourceNote)}</em>${value(pair.engine === 'oracle' ? 'archived_seq' : pair.engine === 'postgresql' ? 'leader_lock' : 'backup_age')}</div>${arrow(transfer, pair.engine === 'oracle' ? 'transfer_job' : pair.engine === 'postgresql' ? 'stream_state' : 'copy_job')}<div class="architecture-node architecture-archives"><small>DR SITE · ARCHIVES</small>${logs}<strong>${esc(copies)}</strong><span>${esc(upper(pair.standby))}</span>${pair.engine === 'oracle' ? '<em>Sequence / SCN + SHA-256 audit</em>' : ''}${value(pair.engine === 'oracle' ? 'copied_seq' : pair.engine === 'postgresql' ? 'wal_backlog' : 'copy_age')}</div>${arrow(apply, pair.engine === 'oracle' ? 'apply_job' : pair.engine === 'postgresql' ? 'replica_state' : 'restore_job')}<div class="architecture-node"><small>DR SITE · DATABASE</small>${cylinder}<strong>${esc(upper(pair.standby))}</strong><b>${esc(upper(pair.name))}</b><span>${esc(target)}</span><em>${esc(targetNote)}</em>${value(pair.engine === 'oracle' ? 'applied_seq' : pair.engine === 'postgresql' ? 'replay_lag' : 'restore_age')}</div></div><div class="architecture-counters">${(pair.engine === 'oracle' ? ['archive_gap','pending_apply','last_success_age'] : pair.engine === 'postgresql' ? ['sync_state','patroni_nodes'] : ['pending_files']).map(key => `<span>${esc(m[key]?.label || key)}: <strong>${formatted(m[key])}</strong></span>`).join('')}</div><p class="architecture-note">Arrows show data direction${active ? ' · Animation indicates healthy monitoring, not a live transfer' : ' · Animation paused'}</p></section>`;
  }
  function card(pair) {
    return architecture(pair) + `<section class="replication-measurements" aria-label="Measurement details"><h4>Measurement details · oldest: ${esc(date(pair.oldest_measurement))}</h4>${terminal(pair)}</section>`;
  }
  function render() {
    if (!snapshot) return;
    const candidates = snapshot.pairs.filter(p => p.engine === engine);
    if (!candidates.some(p => p.id === selectedPair)) selectedPair = null;
    renderSelector();
    const now = snapshot.fetched_at + (performance.now() - receivedAt) / 1000;
    const pairs = candidates.filter(p => p.id === selectedPair).map(pair => {
      const metrics = pair.metrics.map(m => m.clock && now - m.clock > pair.stale_after_seconds ? {...m, status:'stale', reason:'Source measurement is stale'} : m);
      const status = ['critical','stale','unknown','warning'].find(s=>metrics.some(m=>m.status===s)) || 'healthy';
      return {...pair, metrics, status};
    });
    $('replication-pairs').innerHTML = pairs.length ? pairs.map(card).join('') : `<div class="replication-empty">${!engine ? 'Select Oracle, PostgreSQL or SQL Server.' : candidates.length ? 'Select a database above to view replication status.' : 'No databases configured for this engine.'}</div>`;
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
