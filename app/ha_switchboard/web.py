"""Dependency-free, ingress-safe operational dashboard for the Switchboard App."""

from __future__ import annotations


_DASHBOARD = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:;">
  <title>HA Switchboard</title>
  <style>
    :root { color-scheme: dark; --panel:#151c26; --line:#293548; --text:#e6edf3; --muted:#9aa8b8; --accent:#72b7ff; --good:#53d397; --warn:#f2bf5a; --bad:#ff7b72; }
    * { box-sizing:border-box; } body { margin:0; background:radial-gradient(circle at 10% 0%,#192a40 0,#0d1117 42%); color:var(--text); font:15px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { max-width:1180px; margin:auto; padding:32px 20px 56px; } header { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; margin-bottom:24px; }
    h1,h2,h3,p { margin:0; } h1 { font-size:clamp(1.8rem,4vw,2.7rem); letter-spacing:-.04em; } h2 { font-size:1rem; margin-bottom:14px; } h3 { font-size:.92rem; margin-bottom:5px; } .eyebrow { color:var(--accent); font-weight:700; text-transform:uppercase; letter-spacing:.12em; font-size:.72rem; margin-bottom:6px; } .lede { color:var(--muted); margin-top:8px; max-width:720px; }
    button,.link { border:1px solid #41678e; border-radius:8px; background:#1b3855; color:var(--text); cursor:pointer; font:inherit; padding:9px 14px; text-decoration:none; display:inline-block; } button:hover,button:focus-visible,.link:hover,.link:focus-visible { background:#264e75; outline:2px solid var(--accent); outline-offset:2px; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; } .card { background:color-mix(in srgb,var(--panel) 92%,transparent); border:1px solid var(--line); border-radius:14px; padding:20px; box-shadow:0 10px 30px #0002; } .wide { grid-column:1/-1; }
    .metric { display:flex; justify-content:space-between; gap:15px; padding:10px 0; border-bottom:1px solid var(--line); } .metric:last-child { border-bottom:0; } .label { color:var(--muted); } .value { text-align:right; font-weight:650; overflow-wrap:anywhere; }
    .pill { display:inline-flex; align-items:center; gap:7px; border-radius:999px; padding:3px 10px; font-size:.82rem; font-weight:700; } .pill::before { content:""; width:7px; height:7px; border-radius:50%; background:currentColor; } .ok { color:var(--good); background:#153d30; } .degraded,.stale { color:var(--warn); background:#493718; } .disabled,.error { color:var(--bad); background:#4b211f; }
    .sections,.actions { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:9px; } .section { border:1px solid var(--line); border-radius:9px; padding:10px 12px; } .section strong { display:block; font-size:.9rem; } .section span { color:var(--muted); font-size:.8rem; } .empty { color:var(--muted); } .foot { color:var(--muted); font-size:.82rem; margin-top:18px; } .intro { margin-bottom:18px; }
    @media (max-width:700px) { main { padding:22px 14px 40px; } header { flex-direction:column; } .grid { grid-template-columns:1fr; } .wide { grid-column:auto; } .metric { align-items:flex-start; } }
  </style>
</head>
<body>
<main>
  <header>
    <div><div class="eyebrow">Home Assistant App</div><h1>HA Switchboard</h1><p class="lede">A local-first operational view of the gateway and its sanitized Home Assistant profile. Credentials, raw entity identifiers, and provider endpoints never appear here.</p></div>
    <div class="actions"><button id="refresh" type="button">Refresh status</button><button id="scan" type="button">Scan Home Assistant now</button></div>
  </header>
  <div class="grid" aria-live="polite">
    <section class="card"><h2>Gateway health</h2><div class="metric"><span class="label">Liveness</span><span id="health" class="value">Loading…</span></div><div class="metric"><span class="label">Readiness</span><span id="ready" class="value">Loading…</span></div><div class="metric"><span class="label">Decision service</span><span id="jev" class="value">Loading…</span></div><div class="metric"><span class="label">Gateway authentication</span><span id="gatewayAuth" class="value">Loading…</span></div></section>
    <section class="card"><h2>App configuration</h2><div class="metric"><span class="label">Gateway mode</span><span id="gatewayMode" class="value">Loading…</span></div><div class="metric"><span class="label">Web UI access</span><span id="ingress" class="value">Loading…</span></div><div class="metric"><span class="label">Privacy mode</span><span id="privacy" class="value">Loading…</span></div><div class="metric"><span class="label">Fallback route</span><span id="fallback" class="value">Loading…</span></div><div class="metric"><span class="label">Profile refresh</span><span id="refreshMinutes" class="value">Loading…</span></div></section>
    <section class="card"><h2>Home Assistant integration</h2><p id="integrationSummary" class="lede intro">Checking the latest profile…</p><div class="metric"><span class="label">Profile state</span><span id="profileState" class="value">Loading…</span></div><div class="metric"><span class="label">Capabilities exposed</span><span id="capabilities" class="value">—</span></div><div class="metric"><span class="label">Last reconciled</span><span id="reconciled" class="value">—</span></div><p class="foot intro">To use Switchboard, open Settings → Voice assistants, edit or add an assistant, and select HA Switchboard as its Conversation agent. This gateway cannot tell which pipeline is selected.</p><div class="actions"><a class="link" href="/config/integrations" target="_top">Manage integration</a><a class="link" href="/config/voice-assistants" target="_top">Configure Assist</a></div></section>
    <section class="card"><h2>Profile monitor</h2><div class="metric"><span class="label">Adapter connection</span><span id="connected" class="value">—</span></div><div class="metric"><span class="label">Pending sections</span><span id="pending" class="value">—</span></div><div class="metric"><span class="label">Last source event</span><span id="event" class="value">—</span></div><p id="message" class="foot" role="status">Checking gateway status…</p></section>
    <section class="card wide"><h2>Profile sections</h2><p class="foot intro">Each section is a redacted freshness signal. The dashboard intentionally does not list entities, IDs, states, or service payloads. Scan now asks the Core integration to take a fresh snapshot; it cannot scan until that integration is installed and running.</p><div id="sections" class="sections"><p class="empty">Loading section freshness…</p></div></section>
    <section class="card wide"><h2>Configuration guidance</h2><p class="lede">App options are managed by Home Assistant Supervisor, and the Core integration stores its gateway connection in Home Assistant. This UI is read-only by design; use the links above or Home Assistant Settings to change configuration, then refresh this page.</p><div class="actions"><a class="link" href="/config" target="_top">Open Home Assistant settings</a><a class="link" href="/config/integrations/dashboard" target="_top">View integrations</a></div></section>
  </div>
  <p class="foot">Switchboard does not execute Home Assistant services from this page and does not grant the gateway permission to mutate Supervisor settings. Use Home Assistant Assist or the configured conversation agent for requests.</p>
</main>
<script>
(() => {
  const el = id => document.getElementById(id);
  const api = path => { const current = window.location.pathname.endsWith('/') ? window.location.pathname : window.location.pathname + '/'; return new URL(current + path, window.location.origin).toString(); };
  const statusClass = value => value === 'ok' || value === 'ready' || value === 'active' || value === 'connected' ? 'ok' : value === 'degraded' || value === 'stale' ? 'degraded' : 'disabled';
  const displayTime = value => value ? new Date(value).toLocaleString() : 'Not available';
  const setText = (id, value) => { el(id).textContent = String(value ?? 'Not available'); };
  const setPill = (id, label, status) => { const node = el(id); node.textContent = ''; const pill = document.createElement('span'); pill.className = `pill ${statusClass(status)}`; pill.textContent = String(label); node.appendChild(pill); };
  const setSections = sections => { const target = el('sections'); target.textContent = ''; const entries = Object.entries(sections || {}); if (!entries.length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'No profile has been reconciled yet.'; target.appendChild(empty); return; } entries.forEach(([name, item]) => { const card = document.createElement('div'); card.className = 'section'; const title = document.createElement('strong'); title.textContent = name.replaceAll('_', ' '); const state = document.createElement('span'); state.textContent = item && item.status ? item.status : 'unknown'; card.append(title, state); target.appendChild(card); }); };
  async function refresh() {
    setText('message', 'Refreshing…');
    try {
      const responses = await Promise.all([fetch(api('healthz')), fetch(api('readyz')), fetch(api('v1/profile/status')), fetch(api('v1/app/status'))]);
      if (responses.some(response => !response.ok && response.status !== 503)) throw new Error('gateway request failed');
      const [health, ready, profile, app] = await Promise.all(responses.map(response => response.json()));
      setPill('health', health.status === 'ok' ? 'Operational' : 'Unavailable', health.status); setPill('ready', ready.status === 'ready' ? 'Ready' : 'Needs attention', ready.status); setText('jev', ready.jev_configured ? 'Endpoint set; compatibility unverified' : 'Not configured'); setText('gatewayAuth', app.auth_configured ? 'Token configured' : 'No token configured');
      setText('gatewayMode', app.gateway_mode || 'adapter_only'); setText('ingress', app.ingress_only ? 'Supervisor ingress only' : 'Standalone/direct mode'); setText('privacy', app.privacy_mode || 'local_only'); setText('refreshMinutes', `${app.profile_refresh_minutes ?? 15} minutes`);
      setText('fallback', app.fallback_configured ? `${app.fallback_provider || 'configured'} (reachability unverified)` : 'Not configured');
      setPill('profileState', profile.status, profile.status); setText('capabilities', profile.capability_count ?? 0); setText('reconciled', displayTime(profile.last_reconciled_at));
      const monitor = profile.monitor || ready.monitor || {}; setPill('connected', monitor.connected ? 'Connected' : 'Not connected', monitor.connected ? 'connected' : 'disabled'); const pending = monitor.pending_sections || []; setText('pending', pending.length ? pending.join(', ') : 'None'); setText('event', monitor.last_event_at ? displayTime(monitor.last_event_at) : 'None reported'); setSections(profile.sections);
      setText('integrationSummary', profile.status === 'active' && monitor.connected ? 'The Core integration or adapter has supplied a current profile.' : 'The gateway is running, but a current Home Assistant profile is not available.'); setText('message', ready.status === 'ready' ? 'The profile is ready. Decision-service compatibility and Assist pipeline selection still need separate checks.' : 'The gateway is running but the profile needs attention before control requests can proceed.');
    } catch (error) { ['health','ready','profileState','connected'].forEach(id => setPill(id, 'Unavailable', 'error')); setText('message', 'Unable to read gateway status. Check the App logs and try again.'); setText('integrationSummary', 'Status is temporarily unavailable.'); }
  }
  async function scan() {
    const button = el('scan'); button.disabled = true; setText('message', 'Requesting a new Home Assistant scan…');
    try {
      const response = await fetch(api('v1/profile/scan'), {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      if (response.status !== 202) throw new Error('scan request failed');
      setText('message', 'Scan requested. The Core integration should reconcile the profile within about 10 seconds.');
      window.setTimeout(refresh, 1500); window.setTimeout(refresh, 12000);
    } catch (error) { setText('message', 'Could not request a scan. Check the App logs and try again.'); }
    finally { button.disabled = false; }
  }
  el('refresh').addEventListener('click', refresh); el('scan').addEventListener('click', scan); refresh();
})();
</script>
</body>
</html>
"""


def dashboard_html() -> bytes:
    """Return the static dashboard without any runtime configuration values."""

    return _DASHBOARD.encode("utf-8")
