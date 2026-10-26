const React = require('react');
const { createRoot } = require('react-dom/client');
const { weapons: catalogWeapons, categories, globalCamos: baseGlobalCamos, allCamosForWeapon, pending } = require('./camoCatalog');

const globalCamos = [
  ...baseGlobalCamos,
  { name:'Chiral', type:'DMZ Mastery', requirement:'Get 2,500 kills on Tier 3 or higher enemies' },
  { name:'Ripple Tide', type:'DMZ Mastery', requirement:'Exfil with 2 LT dog tags in a single deployment 50 times' },
  { name:'Helio', type:'DMZ Mastery', requirement:'Get 25,000 kills with Legendary weapons while playing a max-level Operator' },
  { name:'Parallax', type:'Warzone Mastery', requirement:'Classified until Season 1' },
  { name:'Damascus Reforged', type:'Warzone Mastery', requirement:'Classified until Season 1' },
  { name:'Empyros', type:'Warzone Mastery', requirement:'Classified until Season 1' }
];

function fmtTime(ts) {
  if (!ts) return '—';
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}
function key(value) { return String(value || '').trim().toUpperCase(); }

function App() {
  const [state, setState] = React.useState({ settings:{ monitorIndex:1, scanFps:4, overlay:true, autoStart:true }, progress:{ weapons:{}, events:[] }, monitors:[], appVersion:'', update:{ status:'idle', percent:0, message:'' } });
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState('');
  const [tab, setTab] = React.useState('dashboard');
  const [category, setCategory] = React.useState('All');
  const [query, setQuery] = React.useState('');
  const [openWeapon, setOpenWeapon] = React.useState(null);

  const refresh = React.useCallback(async () => setState(await window.tracker.getState()), []);
  React.useEffect(() => {
    refresh();
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    window.tracker.onProgress(progress => setState(s => ({...s, progress})));
    window.tracker.onDetectorState(info => setRunning(Boolean(info?.running)));
    window.tracker.onDetectorError(msg => setError(String(msg || 'Unknown detector error')));
    window.tracker.onUpdateStatus(update => setState(s => ({...s, update})));
    return () => window.removeEventListener('focus', onFocus);
  }, [refresh]);

  const progress = state.progress || { weapons:{}, events:[] };
  const events = progress.events || [];
  const latest = events[0];
  const update = state.update || { status:'idle', percent:0, message:'' };

  function weaponProgress(w) {
    const aliases = [w.name, ...(w.aliases || [])].map(key);
    const merged = new Set();
    let lastSeen = null;
    for (const alias of aliases) {
      const record = progress.weapons?.[alias];
      if (!record) continue;
      for (const unlock of (record.unlocks || [])) merged.add(key(unlock));
      if (record.lastSeen && (!lastSeen || new Date(record.lastSeen) > new Date(lastSeen))) lastSeen = record.lastSeen;
    }
    return { unlocks:[...merged], lastSeen };
  }
  function isDone(w, camoName) { return (weaponProgress(w).unlocks || []).map(key).includes(key(camoName)); }
  function doneCount(w) { return allCamosForWeapon(w).filter(c => isDone(w, c.name)).length; }

  const totalWeaponCamos = catalogWeapons.reduce((sum,w)=>sum + allCamosForWeapon(w).length, 0);
  const totalWeaponDone = catalogWeapons.reduce((sum,w)=>sum + doneCount(w), 0);
  const weaponsStarted = catalogWeapons.filter(w => doneCount(w) > 0).length;
  const weaponsComplete = catalogWeapons.filter(w => doneCount(w) === allCamosForWeapon(w).length).length;
  const globalProgress = progress.weapons?.GLOBAL || { unlocks:[] };
  const globalUnlocks = (globalProgress.unlocks || []).map(key);
  const totalGlobalCamos = globalCamos.length;
  const totalGlobalDone = globalCamos.filter(c => globalUnlocks.includes(key(c.name))).length;
  const totalAllCamos = totalWeaponCamos + totalGlobalCamos;
  const totalAllDone = totalWeaponDone + totalGlobalDone;
  const overallCompletionPct = totalAllCamos ? Math.round((totalAllDone / totalAllCamos) * 1000) / 10 : 0;

  async function saveSettings(patch) {
    const settings = { ...state.settings, ...patch };
    setState(s => ({...s, settings}));
    await window.tracker.saveSettings(settings);
  }
  async function toggleCamo(w, camo, complete) { await window.tracker.setCamoStatus(w.name, camo.name, complete); }
  async function toggleGlobal(name, complete) { await window.tracker.setCamoStatus('GLOBAL', name, complete); }

  const visibleWeapons = catalogWeapons.filter(w => {
    const classMatch = category === 'All' || w.category === category;
    const q = query.trim().toLowerCase();
    return classMatch && (!q || w.name.toLowerCase().includes(q) || w.category.toLowerCase().includes(q));
  });

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="logo">M4</div><div><h1>MW4 Camo Tracker</h1><p>Automatic screen tracker</p></div></div>
      {['dashboard','weapons','history','settings'].map(x => <button key={x} onClick={()=>setTab(x)} className={'nav '+(tab===x?'active':'')}>{x[0].toUpperCase()+x.slice(1)}</button>)}
      <div className="grow" />
      <div className="statusBox"><div><span className={'dot '+(running?'on':'')}></span><b>{running?'Watching':'Stopped'}</b></div><small>{state.monitors?.[state.settings.monitorIndex]?.label || 'Monitor 2'} · {state.settings.scanFps || 4} checks/sec</small><small>v{state.appVersion || '—'}</small></div>
    </aside>
    <main>
      {tab==='dashboard' && <>
        <header><div><span className="eyebrow">LIVE TRACKING</span><h2>Dashboard</h2><p>Read-only screen capture. No game memory reading and no gameplay automation.</p></div><div className="buttons"><button className="ghost" onClick={()=>window.tracker.stopDetector()}>Stop</button><button className="primary" onClick={()=>{setError('');window.tracker.startDetector()}}>Start watching</button></div></header>
        {error && <div className="error">{error}</div>}
        <div className="cards">
          <section className="card latest"><span className="eyebrow">LATEST DETECTION</span><h3>{latest?.weapon || 'No unlock detected yet'}</h3><p>{latest ? (latest.camo || `${latest.family || 'CAMO'} ${latest.number || ''}`) : 'Leave the tracker running while you play.'}</p></section>
          <section className="card metric"><span>Overall complete</span><b>{overallCompletionPct}<em>%</em></b></section>
          <section className="card metric"><span>Weapon camos</span><b>{totalWeaponDone}<em>/{totalWeaponCamos}</em></b></section>
          <section className="card metric"><span>Weapons started</span><b>{weaponsStarted}<em>/33</em></b></section>
          <section className="card metric"><span>Weapons complete</span><b>{weaponsComplete}<em>/33</em></b></section>
        </div>
        <div className="overallBar"><div style={{width:`${overallCompletionPct}%`}}></div></div>
        <div className="twoCol">
          <section className="card"><span className="eyebrow">RECENT</span><h3>Recent unlocks</h3><div className="list">{events.length ? events.slice(0,8).map((e,i)=><div className="row" key={i}><div><b>{e.weapon}</b><span>{e.camo || `${e.family || 'CAMO'} ${e.number || ''}`}</span></div><small>{fmtTime(e.timestamp)}</small></div>) : <p className="muted">Nothing detected yet.</p>}</div></section>
          <section className="card"><span className="eyebrow">MISSED UNLOCK PROTECTION</span><h3>Automatic backfill</h3><p className="muted">If the next popup says Military Camo 5 but the tracker only had 1–3, it automatically fills Camo 4 as completed too.</p><div className="example"><span>Detected</span><b>MILITARY CAMO 5</b><span>Saved</span><b>1 → 5</b></div></section>
        </div>
      </>}

      {tab==='weapons' && <>
        <header><div><span className="eyebrow">FULL CAMO CHECKLIST</span><h2>Weapons</h2><p>All 33 launch weapons, their Multiplayer requirements, and your saved completion status.</p></div><div className="catalogSummary"><b>{totalWeaponDone}/{totalWeaponCamos}</b><span>{overallCompletionPct}% overall complete</span></div></header>
        <div className="filters"><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search weapon…" /><div className="filterChips">{['All',...categories].map(x=><button key={x} className={category===x?'selected':''} onClick={()=>setCategory(x)}>{x}</button>)}</div></div>
        <div className="weaponList">
          {visibleWeapons.map(w => {
            const camos = allCamosForWeapon(w), completed = doneCount(w), pct = Math.round((completed/camos.length)*100), expanded = openWeapon === w.name;
            return <section className={'card weaponCard '+(expanded?'expanded':'')} key={w.name}>
              <button className="weaponHeader" onClick={()=>setOpenWeapon(expanded?null:w.name)}><div><span className="classTag">{w.category}</span><h3>{w.name}</h3><small>Last detected: {fmtTime(weaponProgress(w).lastSeen)}</small></div><div className="weaponStats"><b>{completed}/{camos.length}</b><span>{pct}%</span><i>{expanded?'−':'+'}</i></div></button>
              <div className="weaponBar"><div style={{width:`${pct}%`}}></div></div>
              {expanded && <div className="camoTable"><div className="camoHead"><span>Status</span><span>Camo</span><span>Requirement</span></div>{camos.map(c => {
                const done = isDone(w,c.name), uncertain = c.requirement === pending || String(c.requirement).toLowerCase().includes('verify');
                return <label className={'camoRow '+(done?'done':'')} key={c.name}><span className="checkCell"><input type="checkbox" checked={done} onChange={e=>toggleCamo(w,c,e.target.checked)}/></span><span className="camoName"><b>{c.name}</b><small className={'type '+c.type.toLowerCase()}>{c.type}</small></span><span className="requirement">{c.requirement}{uncertain && <small className="verify">Verify in game</small>}{c.dmz && <small className="dmz">DMZ: {c.dmz}</small>}</span></label>;
              })}</div>}
            </section>;
          })}
        </div>
        <section className="card globalSection"><span className="eyebrow">ENDGAME / PRESTIGE</span><h3>Divergence, Mastery & Prestige</h3><p className="muted">These sit outside the 14-camo weapon boards. Check them manually as you earn them.</p><div className="globalGrid">{globalCamos.map(c=>{const done=globalUnlocks.includes(key(c.name));return <label className={'globalCamo '+(done?'done':'')} key={c.name}><input type="checkbox" checked={done} onChange={e=>toggleGlobal(c.name,e.target.checked)}/><div><b>{c.name}</b><small>{c.type}</small><p>{c.requirement}</p></div></label>;})}</div></section>
        <p className="sourceNote">Military camos unlock by weapon level. Special and completionist rows show Multiplayer requirements; DMZ alternatives are shown underneath when available. Warzone mastery challenges remain classified until Season 1.</p>
      </>}

      {tab==='history' && <><header><div><span className="eyebrow">EVENT LOG</span><h2>History</h2><p>Latest detector events stored locally on this PC.</p></div></header><section className="card"><div className="list">{events.length ? events.map((e,i)=><div className="row" key={i}><div><b>{e.weapon}</b><span>{e.camo || `${e.family || 'CAMO'} ${e.number || ''}`}</span><small className="raw">{e.rawText || ''}</small></div><small>{fmtTime(e.timestamp)}</small></div>) : <p className="muted">No history yet.</p>}</div></section></>}

      {tab==='settings' && <><header><div><span className="eyebrow">CONFIGURATION</span><h2>Settings</h2><p>Defaults are tuned to stay lightweight while you game.</p></div></header><section className="card settings">
        <div className="powerNote"><b>Program updates · v{state.appVersion || '—'}</b><p>{update.message || 'Check GitHub for a newer tracker build.'}</p>{update.status==='downloading' && <div className="overallBar"><div style={{width:`${update.percent || 0}%`}}></div></div>}<div className="buttons">{!['downloading','ready'].includes(update.status) && <button className="primary" onClick={()=>window.tracker.checkForUpdates()}>Check for updates</button>}{update.status==='available' && <button className="primary" onClick={()=>window.tracker.downloadUpdate()}>Download update</button>}{update.status==='ready' && <button className="primary" onClick={()=>window.tracker.installUpdate()}>Restart & install</button>}</div></div>
        <label>Capture display<select value={state.settings.monitorIndex ?? 1} onChange={e=>saveSettings({monitorIndex:Number(e.target.value)})}>{(state.monitors||[]).map(m=><option key={m.index} value={m.index}>{m.label} — {m.size.width}×{m.size.height}{m.primary?' (Primary)':''}</option>)}</select></label>
        <label>Screen checks per second<select value={state.settings.scanFps || 4} onChange={e=>saveSettings({scanFps:Number(e.target.value)})}><option value="2">2 — lowest power</option><option value="4">4 — recommended</option><option value="6">6 — faster detection</option></select></label>
        <label className="toggle"><input type="checkbox" checked={Boolean(state.settings.overlay)} onChange={e=>saveSettings({overlay:e.target.checked})}/><span>Show small unlock overlay</span></label>
        <label className="toggle"><input type="checkbox" checked={Boolean(state.settings.autoStart)} onChange={e=>saveSettings({autoStart:e.target.checked})}/><span>Start detector when app opens</span></label>
        <div className="powerNote"><b>Low-power mode</b><p>The detector watches two small percentage-based regions on the selected display, downsamples frames for a cheap change check, and runs OCR only after meaningful visual changes.</p></div>
        <button className="danger" onClick={async()=>{if(confirm('Clear all locally saved camo progress?')){await window.tracker.clearProgress();refresh();}}}>Clear local progress</button>
      </section></>}
    </main>
  </div>;
}
createRoot(document.getElementById('root')).render(<App />);
