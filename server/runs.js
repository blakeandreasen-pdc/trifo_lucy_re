// Run log list (/api/runs, run_log.py), shared by the control page's Runs fold (last 10) and the
// full list at /runs. One line per clean; tap a line for the detail. The server answers from its
// cache straight away and re-reads her logs in the background when they're over 5 minutes old
// (that takes ~15 s), so the list is drawn, then drawn again once the fresh read is in.
(function () {
  const css = document.createElement('style');
  css.textContent = `
 .run { border-top:1px solid var(--line); padding:8px 0; cursor:pointer; font-size:14px; }
 .run .rhead { display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }
 .run .rend { margin-left:auto; color:var(--mute); font-size:13px; }
 .rdot { width:9px; height:9px; border-radius:50%; display:inline-block; background:var(--teal); flex:0 0 auto; align-self:center; }
 .rdot.warn { background:var(--y); } .rdot.bad { background:var(--coral); }
 .run .rmore { display:none; color:var(--mute); font-size:13px; margin:6px 0 0 17px; line-height:1.5; }
 .run.open .rmore { display:block; }`;
  document.head.appendChild(css);

  const esc = t => String(t).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
  const fmt = iso => new Date(iso).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

  function row(r) {
    const probs = Object.entries(r.problems || {});
    const st = r.steadiness, b = r.battery;
    const cls = r.error_stops || probs.length ? 'bad' : (r.ended && r.ended !== 'finished') || (st && st.jumps) ? 'warn' : '';
    const div = document.createElement('div'); div.className = 'run';
    div.innerHTML = `<div class="rhead"><span class="rdot ${cls}"></span><b>${fmt(r.start)}</b><span>${r.minutes} min · ${r.area_m2} m²` +
      (b ? ` · ${b[0]}→${b[1]}%` : '') + `</span><span class="rend">${esc(r.ended || '')}</span></div>`;
    const more = [];
    more.push((r.kind ? r.kind[0].toUpperCase() + r.kind.slice(1) : 'Clean') +
      (r.started_by ? ', started from ' + (r.started_by === 'her button' ? 'her own button' : 'the page or schedule') : '') +
      (r.ended ? '; ' + r.ended : '') + '. Ended ' + new Date(r.end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + '.');
    if (b) more.push(`Battery ${b[0]}% → ${b[1]}% (lowest ${b[2]}%).`);
    if (probs.length || r.error_stops) more.push('Problems: ' + (probs.map(([k, n]) => `${k}${n > 1 ? ' ×' + n : ''}`).join(', ') || 'none named') +
      (r.error_stops ? `; stopped with an error ${r.error_stops}×` : '') + '.');
    if (st) more.push(`Relocalised ${r.relocalised}×. Position: typical correction ${st.median_cm} cm, ${st.jumps} big jump${st.jumps === 1 ? '' : 's'} (largest ${st.worst_m} m, ${st.worst_deg}° at ${st.worst_at}).`);
    else if (!r.logs) more.push('From before her current logs: only her own totals.');
    if (r.logs) more.push('Map saved: ' + (r.map_saved || 'no') + '.');
    div.innerHTML += `<div class="rmore">${more.map(esc).join('<br>')}</div>`;
    div.onclick = () => div.classList.toggle('open');
    return div;
  }

  // list: element to fill; note: element for the status line; limit: newest N (null = all)
  window.loadRuns = function (list, note, limit, force, again) {
    if (!again) note.textContent = 'Reading the run log…';
    const q = [limit ? 'limit=' + limit : '', force ? 'refresh=1' : ''].filter(Boolean).join('&');
    fetch('/api/runs' + (q ? '?' + q : '')).then(r => r.json()).then(d => {
      list.innerHTML = '';
      d.runs.forEach(r => list.appendChild(row(r)));
      if (!d.runs.length) list.textContent = 'No runs yet.';
      if (limit && d.total > d.runs.length) {
        const a = document.createElement('a'); a.href = '/runs'; a.className = 'pill'; a.textContent = `Show all ${d.total}`;
        a.style.cssText = 'display:inline-block;margin-top:8px';
        list.appendChild(a);
      }
      note.textContent = d.refreshing ? 'Checking her logs for newer runs…'
        : d.error ? 'Couldn’t reach her logs just now (' + d.error + '); showing what’s kept here.'
        : 'One line per clean, from her own logs. Tap one for the detail.';
      if (d.refreshing && !again) setTimeout(() => loadRuns(list, note, limit, false, true), 18000);
    }).catch(e => { note.textContent = 'No run log: ' + e; });
  };
})();
