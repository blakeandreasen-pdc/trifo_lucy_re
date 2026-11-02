// ---- Parking view: top-down, her heading up. Kept deliberately light (it runs on a phone next to
// the video and the joystick); the projected path, echo arcs, beeps and camera-corner badges were
// tried on 2026-10-24 and dropped at Chloe's request (too jumpy, and they cost responsiveness).
//  - red/grey: occupied cells of her live map (value >= 150; >= 200 red), placed with her pose
//    plus the depth-vs-map correction from align.py
//  - yellow: what the depth camera saw since the last redraw (all frames, each placed at her pose
//    when it was captured); dim yellow: seen in the last 20 s
// Redraws ~2.5 times a second.
const park = document.getElementById('park'), pctx = park.getContext('2d');
const BODY_R = 0.175;
// The canvas fills the page width at 16:9 (like the camera); drawing uses device pixels so it's sharp.
let CX = 150, CY = 175, DPR = 1;
function fitPark() {
  DPR = window.devicePixelRatio || 1;
  const w = Math.max(200, park.clientWidth), h = Math.round(w * 9 / 16);
  park.width = Math.round(w * DPR); park.height = Math.round(h * DPR);
  CX = park.width / 2; CY = park.height * 0.62;
}
addEventListener('resize', () => { fitPark(); drawPark(); });
const OCC = 150, SURE = 200;
let PPM = 75;                              // pixels per metre (zoom: buttons / mouse wheel)
const setZoom = f => { PPM = Math.max(25, Math.min(220, PPM * f)); drawPark(); };
document.getElementById('parkin').onclick = () => setZoom(1.25);
document.getElementById('parkout').onclick = () => setZoom(0.8);
park.addEventListener('wheel', e => { e.preventDefault(); setZoom(e.deltaY < 0 ? 1.15 : 0.87); }, { passive: false });
// two-finger pinch on an element -> callback(scale change); used for the parking view and the camera
function pinch(el, cb) {
  const pts = new Map(); let last = 0;
  const dist = () => { const [a, b] = [...pts.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  el.addEventListener('pointerdown', e => { pts.set(e.pointerId, e); if (pts.size === 2) last = dist(); });
  el.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, e);
    if (pts.size === 2) { const d = dist(); if (last) cb(d / last); last = d; e.preventDefault(); }
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach(t => el.addEventListener(t, e => { pts.delete(e.pointerId); last = 0; }));
}
pinch(park, f => setZoom(f));

let pPose = null, pPoseAge = 99, pJumpAt = 0, pMapAt = 0, pCellsFor = null, pCells = null;
let aTick = 0, aCorr = null, aInfo = null;
let dLive = [], dAge = 99, dRecent = [], dMem = new Map(), dSeen = new Set();

function mapCells() {
  if (!lastMap) return null;
  if (pCellsFor !== lastMap) {
    const raw = atob(lastMap.cells_b64);
    pCells = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) pCells[i] = raw.charCodeAt(i);
    pCellsFor = lastMap;
  }
  return pCells;
}
function corrected(p) {                    // her pose with the depth-vs-map correction applied (align.py)
  if (!p || !aCorr) return p;
  const k = aCorr, c = Math.cos(k.dth), s = Math.sin(k.dth), rx = p.x - k.cx, ry = p.y - k.cy;
  return { x: k.cx + rx * c - ry * s + k.dx, y: k.cy + rx * s + ry * c + k.dy, theta: p.theta + k.dth };
}
// Map cells near her in map coordinates, rebuilt only when the map changes or she has moved 0.5 m.
let nearCache = { map: null, x: 1e9, y: 1e9, pts: [] };
function mapObstacles() {                  // [[forward m, left m, value], ...] within 2.5 m
  const c = mapCells(), m = lastMap, p = corrected(pPose);
  if (!c || !p) return [];
  if (nearCache.map !== m || Math.hypot(p.x - nearCache.x, p.y - nearCache.y) > 0.5) {
    const cs = m.cell_size, R = 3.0, pts = [];
    const r0 = Math.max(0, Math.floor((m.max_x - p.x - R) / cs)), r1 = Math.min(m.height - 1, Math.ceil((m.max_x - p.x + R) / cs));
    const c0 = Math.max(0, Math.floor((m.max_y - p.y - R) / cs)), c1 = Math.min(m.width - 1, Math.ceil((m.max_y - p.y + R) / cs));
    for (let r = r0; r <= r1; r++) for (let col = c0; col <= c1; col++) {
      const v = c[r * m.width + col];
      if (v >= OCC) pts.push([m.max_x - (r + 0.5) * cs, m.max_y - (col + 0.5) * cs, v]);
    }
    nearCache = { map: m, x: p.x, y: p.y, pts };
  }
  const cos = Math.cos(p.theta), sin = Math.sin(p.theta), out = [];
  for (const [x, y, v] of nearCache.pts) {
    const dx = x - p.x, dy = y - p.y;
    if (dx * dx + dy * dy <= 6.25) out.push([dx * cos + dy * sin, -dx * sin + dy * cos, v]);
  }
  return out;
}
function toHer(X, Y) {                     // map point (her raw pose frame) -> [forward, left]
  const c = Math.cos(pPose.theta), s = Math.sin(pPose.theta), dx = X - pPose.x, dy = Y - pPose.y;
  return [dx * c + dy * s, -dx * s + dy * c];
}

function drawPark() {
  const P = PPM * DPR, S = ([f, l]) => [CX - l * P, CY - f * P];
  pctx.clearRect(0, 0, park.width, park.height);
  pctx.strokeStyle = '#262626'; pctx.lineWidth = 1;
  pctx.fillStyle = '#555'; pctx.font = Math.round(10 * DPR) + 'px sans-serif'; pctx.textAlign = 'left';
  const step = PPM < 50 ? 1 : 0.5, far = Math.hypot(park.width, park.height);
  for (let rr = step; rr * P < far; rr += step) {
    pctx.beginPath(); pctx.arc(CX, CY, rr * P, 0, 2 * Math.PI); pctx.stroke();
    pctx.fillText(rr + ' m', CX + 3 * DPR, CY - rr * P - 2 * DPR);
  }
  const info = document.getElementById('parkinfo');
  const posOk = pPose && pPoseAge <= 2, trusted = posOk && Date.now() - pJumpAt > 30000;
  const cell = lastMap ? Math.max(2 * DPR, lastMap.cell_size * P) : 2 * DPR;
  const dot = (p, col) => { const [X, Y] = S(p); pctx.fillStyle = col; pctx.fillRect(X - cell / 2, Y - cell / 2, cell, cell); };
  if (trusted) {
    for (const o of mapObstacles()) dot(o, o[2] >= SURE ? '#e04848' : '#7a5a5a');
    if (liveOn.checked) for (const [X, Y] of dMem.values()) dot(toHer(X, Y), '#8a7628');
  }
  // depth since the last redraw: placed frames (exact pose) if we have them, else the newest raw frame
  if (!liveOn.checked) { /* yellow switched off */ }
  else if (posOk && dRecent.length) {
    for (const fr of dRecent) {
      const c = Math.cos(fr.pose.theta), s = Math.sin(fr.pose.theta);
      for (const [f, l] of fr.pts) dot(toHer(fr.pose.x + f * c - l * s, fr.pose.y + f * s + l * c), '#ffd23f');
    }
  } else if (dAge < 1.5) for (const p of dLive) dot(p, '#ffd23f');
  dRecent = [];
  pctx.fillStyle = 'rgba(52,152,219,0.85)'; pctx.strokeStyle = '#fff'; pctx.lineWidth = 1.5 * DPR;
  pctx.beginPath(); pctx.arc(CX, CY, BODY_R * P, 0, 2 * Math.PI); pctx.fill(); pctx.stroke();
  pctx.strokeStyle = '#00e5ff'; pctx.lineWidth = 3 * DPR; pctx.beginPath(); pctx.moveTo(CX, CY); pctx.lineTo(CX, CY - BODY_R * P); pctx.stroke();
  if (!posOk) info.textContent = 'No live position from her' + (pPose ? ` (last one ${pPoseAge.toFixed(0)} s old)` : '') + '.';
  else if (!trusted) info.textContent = 'Her position just jumped (she is lost, new map frame): map hidden for now.';
  else info.textContent = (aCorr ? `Map lined up: shifted ${(Math.hypot(aCorr.dx, aCorr.dy) * 100).toFixed(0)} cm, ${(aCorr.dth * 180 / Math.PI).toFixed(0)} deg.` : alignOn.checked ? 'Map not lined up yet (needs walls in view).' : 'Auto-align off (Re-align does a one-off fit).')
    + (aInfo && aInfo.decision ? ` Last check: ${aInfo.decision}.` : '');
  info.style.display = (alignOn.checked || !posOk || !trusted) ? '' : 'none';   // warnings, or auto-align's verdict
}

async function pollPose() {
  try {
    const [d, dd] = await Promise.all([
      fetch('/api/pose').then(r => r.json()),
      liveOn.checked ? fetch('/api/depth').then(r => r.json()).catch(() => null) : null]);
    if (dd) {
      dLive = dd.pts || []; dAge = dd.age == null ? 99 : dd.age;
      const now = Date.now(), keep = now - pJumpAt > 30000;
      for (const fr of dd.placed || []) {
        if (dSeen.has(fr.ts)) continue;
        dSeen.add(fr.ts);
        dRecent.push(fr);
        if (!keep) continue;
        const c = Math.cos(fr.pose.theta), s = Math.sin(fr.pose.theta);
        for (const [f, l] of fr.pts) {
          const X = fr.pose.x + f * c - l * s, Y = fr.pose.y + f * s + l * c;
          dMem.set(Math.round(X * 50) + ',' + Math.round(Y * 50), [X, Y, now]);
        }
      }
      if (dSeen.size > 200) dSeen = new Set([...dSeen].slice(-50));
      const cut = now - 20000;
      for (const [k, v] of dMem) if (v[2] < cut) dMem.delete(k);
    }
    if (d.pose) {
      // a jump of > 0.5 m between updates means she's lost and started a fresh map frame
      if (pPose && Math.hypot(d.pose.x - pPose.x, d.pose.y - pPose.y) > 0.5) pJumpAt = Date.now();
      pPose = d.pose; pPoseAge = d.age;
    }
    if (alignOn.checked && ++aTick % 5 === 0) {
      const a = await fetch('/api/align').then(r => r.json()).catch(() => null);
      if (a) { aCorr = a.corr; aInfo = a; }
    }
  } catch (e) { pPoseAge = 99; }
  if (!lastMap || Date.now() - pMapAt > 60000) { pMapAt = Date.now(); refreshMap(); }   // ~2 MB from her: rarely
}

// Yellow on/off (remembered): handy to see the mismatch; once lined up it can go.
const liveOn = document.getElementById('liveon');
liveOn.checked = localStorage.getItem('liveOff') !== '1';
liveOn.onchange = () => { localStorage.setItem('liveOff', liveOn.checked ? '0' : '1'); drawPark(); };
// Auto-align on/off (remembered; off by default since 2026-10-25): it only shifts this view, never
// Lucy. Off = no correction; Re-align still does a one-off fit, which then stays until the next one.
const alignOn = document.getElementById('alignon');
alignOn.checked = localStorage.getItem('alignOn') === '1';
alignOn.onchange = () => { localStorage.setItem('alignOn', alignOn.checked ? '1' : '0'); if (!alignOn.checked) { aCorr = null; aInfo = null; } drawPark(); };
// Re-align now: the server forgets its correction and fits again from scratch at once.
document.getElementById('realign').onclick = async () => {
  aCorr = null;
  await fetch('/api/align?now=1').catch(() => null);
  setTimeout(async () => { const a = await fetch('/api/align').then(r => r.json()).catch(() => null); if (a) { aCorr = a.corr; aInfo = a; } drawPark(); }, 2500);
};
// On/off (remembered on this device): with it off, nothing is polled or drawn.
const parkOn = document.getElementById('parkon');
parkOn.checked = localStorage.getItem('parkOff') !== '1';
// The page's "Live map" button drives this (hidden) switch; the whole live map and its tools fold away.
const showPark = () => { document.getElementById('parkcard').classList.toggle('hidden', !parkOn.checked); if (window.showSecs) showSecs(); if (parkOn.checked) { fitPark(); drawPark(); } };
parkOn.onchange = () => { localStorage.setItem('parkOff', parkOn.checked ? '0' : '1'); showPark(); };
showPark();
// With the camera off (window.LUCY_CAM_OFF, set by the page) the phone and Lucy have room to spare:
// poll and redraw about 2-3x as often.
let pollBusy = false;
(function pollLoop() {
  setTimeout(pollLoop, window.LUCY_CAM_OFF ? 120 : 250);
  if (!parkOn.checked || document.hidden || pollBusy || window.LIVE_CLOSED) return;
  pollBusy = true;
  pollPose().finally(() => { pollBusy = false; });
})();
(function drawLoop() {
  setTimeout(drawLoop, window.LUCY_CAM_OFF ? 150 : 400);
  if (parkOn.checked && !document.hidden && !window.LIVE_CLOSED) drawPark();
})();

// ---- Driving mode (?drive): camera + parking view + stick, page zoom/scroll off; pinch zooms the
// parking view and the camera picture (double-tap the camera to reset).
if (/[?&]drive(=|&|$)/.test(location.search)) {
  document.body.classList.add('drive');
  document.querySelector('meta[name=viewport]').content = 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no';
  parkOn.checked = true; showPark();
  const vid = document.getElementById('main');
  let vz = 1;
  pinch(vid.parentElement, f => { vz = Math.max(1, Math.min(4, vz * f)); vid.style.transform = `scale(${vz})`; });
  vid.parentElement.addEventListener('dblclick', () => { vz = 1; vid.style.transform = ''; });
  document.addEventListener('touchmove', e => { if (e.touches.length > 1 || !e.target.closest('#stick')) e.preventDefault(); }, { passive: false });
  fitPark();
}
