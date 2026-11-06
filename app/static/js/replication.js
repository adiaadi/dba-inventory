(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const labels = {healthy: 'HEALTHY', warning: 'WARNING', critical: 'CRITICAL', stale: 'STALE DATA', unknown: 'NO DATA'};
  let snapshot = null, receivedAt = 0, engine = 'all', paused = false, busy = false, timer, failed = false;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
  const date = clock => clock ? new Date(clock * 1000).toLocaleString() : 'No measurement';
  const badge = status => `<span class="replication-badge ${esc(status)}">${esc(labels[status] || status)}</span>`;
  function formatted(metric) {
    if (!metric || metric.value === null) return '—';
    if (typeof metric.value === 'string') return esc(metric.value.toUpperCase());
    if (metric.unit === 'bytes') return `${number(metric.value / 1048576)} MB`;
    if (metric.unit === 's' && metric.value >= 60) return `${number(metric.value / 60)} min`;
    return `${number(metric.value)}${metric.unit ? ' ' + esc(metric.unit) : ''}`;
  }
  function metricBox(m) {
    return `<div class="replication-metric"><small>${esc(m.label)}</small><strong class="metric-${esc(m.status)}" title="${esc(m.reason)}">${formatted(m)}</strong></div>`;
  }
  function step(label, host, m) {
    return `<div class="replication-step"><small>${esc(label)}</small><strong>${esc(host)}</strong><div class="step-value metric-${esc(m?.status)}">${formatted(m)}</div></div>`;
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
  function card(pair) {
    const m = Object.fromEntries(pair.metrics.map(metric => [metric.key, metric]));
    let steps, keys, health, caption, title;
    if (pair.engine === 'oracle') {
      steps = [step('Primary', pair.primary, m.archived_seq), step('Transferred', 'DR Site', m.copied_seq), step('Standby', pair.standby, m.applied_seq)];
      keys = ['archive_gap','pending_apply','last_success_age']; health = ['transfer_job','apply_job']; caption = 'Archive → Cron transfer → Apply'; title = 'Cron job & apply health';
    } else if (pair.engine === 'postgresql') {
      steps = [step('Leader', pair.primary, m.leader_lock), step('WAL stream', 'Primary → DR', m.stream_state), step('Replica', pair.standby, m.replica_state)];
      keys = ['wal_backlog','replay_lag','patroni_nodes']; health = ['leader_lock','replica_state','sync_state']; caption = 'Patroni HA cluster · WAL streaming'; title = 'Patroni & replication health';
    } else {
      steps = [step('1. Backup', pair.primary, m.backup_job), step('2. Copy', 'DR Site', m.copy_job), step('3. Restore', pair.standby, m.restore_job)];
      keys = ['backup_age','copy_age','restore_age','pending_files']; health = ['backup_job','copy_job','restore_job']; caption = 'Backup → Copy → Restore'; title = 'SQL Agent jobs';
    }
    return `<article class="replication-card"><header><div><h3>${esc(pair.title)}</h3><small>${esc(pair.name)} · ${esc(pair.environment)}</small></div>${badge(failed ? 'stale' : pair.status)}</header><div class="replication-card-grid"><div><div class="replication-caption">${caption}</div><div class="replication-flow">${steps.join('<span class="replication-arrow" aria-hidden="true">→</span>')}</div><div class="replication-metrics">${keys.map(k => metricBox(m[k])).join('')}</div></div><aside class="replication-health"><h4>${title}</h4>${pair.schedule ? `<div class="replication-health-row"><span>Schedule</span><span>${esc(pair.schedule)}</span></div>` : ''}${health.map(k => `<div class="replication-health-row"><span>${esc(m[k].label)}</span><span class="metric-${esc(m[k].status)}">${formatted(m[k])}</span></div>`).join('')}<div class="replication-trend">${trend(pair, m[pair.trend_key])}</div></aside></div><details><summary>Measurement details · oldest: ${esc(date(pair.oldest_measurement))}</summary><ul>${pair.metrics.map(metric => `<li>${esc(metric.label)}: ${formatted(metric)} — ${esc(labels[metric.status])}; ${esc(date(metric.clock))}${metric.reason ? ' · '+esc(metric.reason) : ''}</li>`).join('')}</ul></details></article>`;
  }
  function render() {
    if (!snapshot) return;
    const expanded = new Set(Array.from(document.querySelectorAll('#replication-pairs details[open]')).map(d=>d.closest('article').dataset.pair));
    const now = snapshot.fetched_at + (performance.now() - receivedAt) / 1000;
    const pairs = snapshot.pairs.filter(p => engine === 'all' || p.engine === engine).map(pair => {
      const metrics = pair.metrics.map(m => m.clock && now - m.clock > pair.stale_after_seconds ? {...m, status:'stale', reason:'Source measurement is stale'} : m);
      const status = ['critical','stale','unknown','warning'].find(s=>metrics.some(m=>m.status===s)) || 'healthy';
      return {...pair, metrics, status};
    });
    const counts = [['Replication pairs',pairs.length,''],['Healthy',pairs.filter(p=>!failed && p.status==='healthy').length,'healthy'],['Warning',pairs.filter(p=>!failed && p.status==='warning').length,'warning'],['Critical',pairs.filter(p=>!failed && p.status==='critical').length,'critical'],['No data / stale',pairs.filter(p=>failed || ['unknown','stale'].includes(p.status)).length,'unknown']];
    $('replication-summary').innerHTML = counts.map(([label,count,status])=>`<div class="replication-stat ${status}"><span>${label}</span><strong>${count}</strong></div>`).join('');
    $('replication-pairs').innerHTML = pairs.length ? pairs.map(card).join('') : `<div class="replication-empty">${snapshot.pairs.length ? 'No replication pairs for this database engine.' : 'No replication pairs configured. Configure Zabbix item mappings using REPLICATION_CONFIG_FILE on the server.'}</div>`;
    document.querySelectorAll('#replication-pairs article').forEach((article, index)=>{
      article.dataset.pair = pairs[index].id;
      article.querySelector('details').open = expanded.has(pairs[index].id);
    });
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
  document.querySelectorAll('[data-engine]').forEach(button => button.addEventListener('click',()=>{
    engine = button.dataset.engine;
    document.querySelectorAll('[data-engine]').forEach(b=>{ b.classList.toggle('active',b===button); b.setAttribute('aria-pressed',String(b===button)); }); render();
  }));
  $('refresh-poll').addEventListener('click',refresh);
  $('poll-interval').addEventListener('change',schedule);
  $('pause-poll').addEventListener('click',()=>{
    paused=!paused; $('pause-poll').textContent=paused?'Resume':'Pause'; $('pause-poll').setAttribute('aria-pressed',String(paused));
    $('poll-status').textContent=paused?'Paused · measurements will age':'Polling enabled';
    if (paused) schedule(); else refresh();
  });
  document.addEventListener('visibilitychange',()=>{ if (document.hidden) clearTimeout(timer); else if (!paused) refresh(); });
  // Age paused/failed snapshots without waiting for another successful network call.
  setInterval(()=>{ if (snapshot && !document.hidden && (paused || failed)) render(); }, 10000);
  refresh();
})();
