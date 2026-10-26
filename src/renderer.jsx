const React = require('react');
const { createRoot } = require('react-dom/client');

function fmtTime(ts) {
  if (!ts) return '—';
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function App() {
  const [state, setState] = React.useState({ settings:{ monitorIndex:1, scanFps:4, overlay:true, autoStart:true }, progress:{ weapons:{}, events:[] }, monitors:[] });
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState('');
  const [tab, setTab] = React.useState('dashboard');

  const refresh = React.useCallback(async () => setState(await window.tracker.getState()), []);

  React.useEffect(() => {
    refresh();
    window.tracker.onProgress(progress => setState(s => ({...s, progress})));
    window.tracker.onDetectorState(info => setRunning(Boolean(info?.running)));
    window.tracker.onDetectorError(msg => setError(String(msg || 'Unknown detector error')));
  }, [refresh]);

  const progress = state.progress || { weapons:{}, events:[] };
  const weapons = Object.entries(progress.weapons || {});
  const events = progress.events || [];
  const unlockCount = weapons.reduce((sum, [,w]) => sum + (w.unlocks?.length || 0), 0);
  const latest = events[0];

  async function saveSettings(patch) {
    const settings = { ...state.settings, ...patch };
    setState(s => ({...s, settings}));
    await window.tracker.saveSettings(settings);
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="logo">M4</div><div><h1>MW4 Camo Tracker</h1><p>Automatic screen tracker</p></div></div>
      {['dashboard','weapons','history','settings'].map(x => <button key={x} onClick={()=>setTab(x)} className={'nav '+(tab===x?'active':'')}>{x[0].toUpperCase()+x.slice(1)}</button>)}
      <div className="grow" />
      <div className="statusBox"><div><span className={'dot '+(running?'on':'')}></span><b>{running?'Watching':'Stopped'}</b></div><small>{state.monitors?.[state.settings.monitorIndex]?.label || 'Monitor 2'} · {state.settings.scanFps || 4} checks/sec</small></div>
    </aside>
    <main>
      {tab==='dashboard' && <>
        <header><div><span className="eyebrow">LIVE TRACKING</span><h2>Dashboard</h2><p>Read-only screen capture. No game memory reading and no gameplay automation.</p></div><div className="buttons"><button className="ghost" onClick={()=>window.tracker.stopDetector()}>Stop</button><button className="primary" onClick={()=>{setError('');window.tracker.startDetector()}}>Start watching</button></div></header>
        {error && <div className="error">{error}</div>}
        <div className="cards">
          <section className="card latest"><span className="eyebrow">LATEST DETECTION</span><h3>{latest?.weapon || 'No unlock detected yet'}</h3><p>{latest ? (latest.camo || `${latest.family || 'CAMO'} ${latest.number || ''}`) : 'Leave the tracker running while you play.'}</p></section>
          <section className="card metric"><span>Weapons seen</span><b>{weapons.length}</b></section>
          <section className="card metric"><span>Unlocks tracked</span><b>{unlockCount}</b></section>
          <section className="card metric"><span>Events saved</span><b>{events.length}</b></section>
        </div>
        <div className="twoCol">
          <section className="card"><span className="eyebrow">RECENT</span><h3>Recent unlocks</h3><div className="list">{events.length ? events.slice(0,8).map((e,i)=><div className="row" key={i}><div><b>{e.weapon}</b><span>{e.camo || `${e.family || 'CAMO'} ${e.number || ''}`}</span></div><small>{fmtTime(e.timestamp)}</small></div>) : <p className="muted">Nothing detected yet.</p>}</div></section>
          <section className="card"><span className="eyebrow">MISSED UNLOCK PROTECTION</span><h3>Automatic backfill</h3><p className="muted">If the next popup says Military Camo 5 but the tracker only had 1–3, it automatically fills Camo 4 as completed too.</p><div className="example"><span>Detected</span><b>MILITARY CAMO 5</b><span>Saved</span><b>1 → 5</b></div></section>
        </div>
      </>}

      {tab==='weapons' && <><header><div><span className="eyebrow">PROGRESS</span><h2>Weapons</h2><p>Confirmed unlocks by weapon.</p></div></header><div className="weaponGrid">{weapons.length ? weapons.map(([name,w])=><section className="card weapon" key={name}><h3>{name}</h3><p>{w.unlocks?.length || 0} unlocks</p><div className="chips">{(w.unlocks||[]).map(x=><span key={x}>{x}</span>)}</div><small>Last seen: {fmtTime(w.lastSeen)}</small></section>) : <section className="card muted">No weapons tracked yet.</section>}</div></>}

      {tab==='history' && <><header><div><span className="eyebrow">EVENT LOG</span><h2>History</h2><p>Latest detector events stored locally on this PC.</p></div></header><section className="card"><div className="list">{events.length ? events.map((e,i)=><div className="row" key={i}><div><b>{e.weapon}</b><span>{e.camo || `${e.family || 'CAMO'} ${e.number || ''}`}</span><small className="raw">{e.rawText || ''}</small></div><small>{fmtTime(e.timestamp)}</small></div>) : <p className="muted">No history yet.</p>}</div></section></>}

      {tab==='settings' && <><header><div><span className="eyebrow">CONFIGURATION</span><h2>Settings</h2><p>Defaults are tuned to stay lightweight while you game.</p></div></header><section className="card settings">
        <label>Capture display<select value={state.settings.monitorIndex ?? 1} onChange={e=>saveSettings({monitorIndex:Number(e.target.value)})}>{(state.monitors||[]).map(m=><option key={m.index} value={m.index}>{m.label} — {m.size.width}×{m.size.height}{m.primary?' (Primary)':''}</option>)}</select></label>
        <label>Screen checks per second<select value={state.settings.scanFps || 4} onChange={e=>saveSettings({scanFps:Number(e.target.value)})}><option value="2">2 — lowest power</option><option value="4">4 — recommended</option><option value="6">6 — faster detection</option></select></label>
        <label className="toggle"><input type="checkbox" checked={Boolean(state.settings.overlay)} onChange={e=>saveSettings({overlay:e.target.checked})}/><span>Show small unlock overlay</span></label>
        <label className="toggle"><input type="checkbox" checked={Boolean(state.settings.autoStart)} onChange={e=>saveSettings({autoStart:e.target.checked})}/><span>Start detector when app opens</span></label>
        <div className="powerNote"><b>Low-power mode</b><p>The detector captures only the right-side notification region, downsamples frames for a cheap change check, and runs OCR only after a meaningful visual change.</p></div>
        <button className="danger" onClick={async()=>{if(confirm('Clear all locally saved camo progress?')){await window.tracker.clearProgress();refresh();}}}>Clear local progress</button>
      </section></>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
