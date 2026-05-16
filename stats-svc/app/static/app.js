/**
 * DX Cluster Stats — dashboard frontend
 *
 * - Fetches /api/* endpoints on load and every 30 seconds (POLL_INTERVAL_MS).
 * - Opens a WebSocket at /ws (same host, auto ws:// or wss://) for live spots.
 * - Reconnects WS on close with exponential back-off (max 30 s).
 * - Renders charts via Apache ECharts (loaded in index.html from CDN).
 * - No framework, no build step.
 */

(function () {
  'use strict';

  const POLL_INTERVAL_MS = 30_000;
  const WS_MAX_BACKOFF_MS = 30_000;
  const TICKER_MAX = 50;

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  let source = 'both';
  let wsBackoff = 1000;

  // ECharts instances (initialised on first render)
  let activityChart = null;
  let bandChart = null;
  let modeChart = null;
  let geoChart = null;

  // -------------------------------------------------------------------------
  // DOM helpers
  // -------------------------------------------------------------------------
  function $(id) { return document.getElementById(id); }

  function esc(s){return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

  function setUserCount(n) {
    $('userCount').textContent = n;
  }

  // -------------------------------------------------------------------------
  // API helpers
  // -------------------------------------------------------------------------
  async function apiFetch(path) {
    const resp = await fetch(path);
    if (!resp.ok) throw new Error(`GET ${path} → ${resp.status}`);
    return resp.json();
  }

  // -------------------------------------------------------------------------
  // ECharts helpers
  // -------------------------------------------------------------------------
  function getOrInit(container, ref) {
    if (ref) return ref;
    return echarts.init(container, 'dark');
  }

  function renderActivity(data) {
    activityChart = getOrInit($('activityChart'), activityChart);
    const hours = data.map(d => d.hour.substring(11, 16)); // HH:MM
    const counts = data.map(d => d.count);
    activityChart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: hours,
        axisLabel: { rotate: 45, fontSize: 10 },
        axisLine: { lineStyle: { color: '#2a2d3a' } },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#2a2d3a' } },
        splitLine: { lineStyle: { color: '#2a2d3a' } },
      },
      series: [{
        type: 'line',
        data: counts,
        smooth: true,
        areaStyle: { opacity: 0.25 },
        lineStyle: { color: '#4f9cf9' },
        itemStyle: { color: '#4f9cf9' },
      }],
      grid: { left: '5%', right: '3%', bottom: '18%', top: '6%' },
    }, true);
  }

  function renderPie(chartRef, container, data) {
    const inst = getOrInit(container, chartRef);
    inst.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: {
        orient: 'vertical', right: 0, top: 'center',
        textStyle: { color: '#8892a4', fontSize: 11 },
        type: 'scroll',
      },
      series: [{
        type: 'pie',
        radius: ['35%', '65%'],
        center: ['38%', '50%'],
        data: data.map(d => ({ name: d.label, value: d.value })),
        label: { show: false },
        emphasis: { label: { show: true, fontSize: 12 } },
      }],
    }, true);
    return inst;
  }

  function renderBand(data) {
    bandChart = renderPie(bandChart, $('bandChart'), data);
  }

  function renderMode(data) {
    modeChart = renderPie(modeChart, $('modeChart'), data);
  }

  function renderGeo(data) {
    geoChart = getOrInit($('geoChart'), geoChart);
    const labels = data.map(d => d.label);
    const values = data.map(d => d.value);
    geoChart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: labels,
        axisLabel: { rotate: 40, fontSize: 10 },
        axisLine: { lineStyle: { color: '#2a2d3a' } },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#2a2d3a' } },
        splitLine: { lineStyle: { color: '#2a2d3a' } },
      },
      series: [{
        type: 'bar',
        data: values,
        itemStyle: { color: '#38bdf8' },
      }],
      grid: { left: '5%', right: '3%', bottom: '25%', top: '6%' },
    }, true);
  }

  function renderTable(tableId, rows, cols) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    tbody.innerHTML = rows.map((row, i) =>
      `<tr><td>${i + 1}</td>${cols.map(c => `<td>${esc(row[c])}</td>`).join('')}</tr>`
    ).join('');
  }

  function renderUsers(data) {
    setUserCount(data.count);
    const list = $('usersList');
    list.innerHTML = data.users.map(u =>
      `<li><strong>${esc(u.callsign)}</strong><span class="conn-type">${esc(u.conn_type)}</span></li>`
    ).join('');
  }

  function renderRareDx(data) {
    renderTable('rareDxTable', data, ['callsign', 'count']);
  }

  // -------------------------------------------------------------------------
  // Callsign lookup
  // -------------------------------------------------------------------------
  async function lookupCallsign() {
    const call = ($('callsignInput').value || '').trim().toUpperCase();
    if (!call) return;
    try {
      const data = await apiFetch(`/api/callsign/${encodeURIComponent(call)}`);
      $('csCall').textContent = data.callsign;
      $('csAsSpotter').textContent = data.as_spotter;
      $('csAsDx').textContent = data.as_dx;

      const tbody = document.querySelector('#callsignRecentTable tbody');
      tbody.innerHTML = (data.recent || []).map(r => {
        const ts = (r.ts || '').substring(0, 19).replace('T', ' ');
        return `<tr>
          <td>${esc(ts)}</td>
          <td>${esc(r.spotter || '')}</td>
          <td>${esc(r.dx_call || '')}</td>
          <td>${esc(r.freq_khz != null ? Number(r.freq_khz).toFixed(1) : '')}</td>
          <td>${esc(r.band || '')}</td>
          <td>${esc(r.mode || '')}</td>
          <td>${esc(r.source || '')}</td>
        </tr>`;
      }).join('');

      $('callsignResult').hidden = false;
    } catch (err) {
      console.error('Callsign lookup failed:', err);
    }
  }

  // -------------------------------------------------------------------------
  // Ticker
  // -------------------------------------------------------------------------
  function pushTicker(spot) {
    const list = $('spotTicker');
    // Remove empty placeholder if present
    const empty = list.querySelector('.ticker-empty');
    if (empty) empty.remove();

    const li = document.createElement('li');
    const time = new Date().toISOString().substring(11, 19);
    const freq = spot.freq_khz ? ` ${Number(spot.freq_khz).toFixed(1)} kHz` : '';
    li.textContent = `${time}  ${spot.dx_call || '?'}${freq}  < ${spot.spotter || '?'}`;
    list.prepend(li);

    // Trim to max
    while (list.children.length > TICKER_MAX) {
      list.removeChild(list.lastChild);
    }
  }

  function initTicker() {
    const list = $('spotTicker');
    const li = document.createElement('li');
    li.className = 'ticker-empty';
    li.textContent = 'Waiting for live spots…';
    list.appendChild(li);
  }

  // -------------------------------------------------------------------------
  // Fetch and render all data
  // -------------------------------------------------------------------------
  async function refreshAll() {
    const src = source;
    const geoBy = $('geoBy').value;

    try {
      const [activity, bands, modes, geo, spotters, topDx, rareDxData, users] = await Promise.all([
        apiFetch(`/api/activity?source=${src}&hours=24`),
        apiFetch(`/api/bands?source=${src}`),
        apiFetch(`/api/modes?source=${src}`),
        apiFetch(`/api/geo?source=${src}&by=${geoBy}&top=15`),
        apiFetch(`/api/top/spotters?source=${src}&limit=10&hours=24`),
        apiFetch(`/api/top/dx?source=${src}&limit=10&hours=24`),
        apiFetch(`/api/top/rare-dx?source=${src}&limit=10&hours=24`),
        apiFetch('/api/users'),
      ]);

      renderActivity(activity);
      renderBand(bands);
      renderMode(modes);
      renderGeo(geo);
      renderTable('spottersTable', spotters, ['callsign', 'count']);
      renderTable('topDxTable', topDx, ['callsign', 'count']);
      renderRareDx(rareDxData);
      renderUsers(users);
    } catch (err) {
      console.error('Refresh failed:', err);
    }
  }

  // -------------------------------------------------------------------------
  // WebSocket
  // -------------------------------------------------------------------------
  function connectWs() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws`;
    let ws;

    try {
      ws = new WebSocket(url);
    } catch (e) {
      console.warn('WS unavailable, retrying in', wsBackoff, 'ms');
      scheduleWsReconnect();
      return;
    }

    ws.onopen = () => {
      console.log('WS connected');
      wsBackoff = 1000; // reset back-off on success
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }

      if (msg.type === 'spot' && msg.data) {
        pushTicker(msg.data);
      } else if (msg.type === 'users' && msg.data) {
        renderUsers(msg.data);
      }
    };

    ws.onclose = () => {
      console.log('WS closed, reconnecting in', wsBackoff, 'ms');
      scheduleWsReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  function scheduleWsReconnect() {
    setTimeout(() => {
      wsBackoff = Math.min(wsBackoff * 2, WS_MAX_BACKOFF_MS);
      connectWs();
    }, wsBackoff);
  }

  // -------------------------------------------------------------------------
  // Event listeners
  // -------------------------------------------------------------------------
  function attachEvents() {
    $('sourceFilter').addEventListener('change', (e) => {
      source = e.target.value;
      refreshAll();
    });

    $('geoBy').addEventListener('change', () => {
      refreshAll();
    });

    $('callsignBtn').addEventListener('click', lookupCallsign);
    $('callsignInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') lookupCallsign();
    });
  }

  // -------------------------------------------------------------------------
  // Responsive chart resize
  // -------------------------------------------------------------------------
  window.addEventListener('resize', () => {
    [activityChart, bandChart, modeChart, geoChart].forEach(c => c && c.resize());
  });

  // -------------------------------------------------------------------------
  // Bootstrap
  // -------------------------------------------------------------------------
  function init() {
    initTicker();
    attachEvents();
    refreshAll();
    setInterval(refreshAll, POLL_INTERVAL_MS);
    connectWs();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
