const React=require('react');
const {weapons,allCamosForWeapon}=require('./camoCatalog');
const {captureWarnings}=require('./captureWarnings');

function CaptureHealthBanner({heartbeat,receivedAt,running}){
  const [now,setNow]=React.useState(Date.now());
  React.useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
  const issues=captureWarnings(heartbeat,receivedAt,running,now);
  if(!issues.length)return null;
  return <div className="error captureWarning" role="status">{issues.map(message=><div key={message}>{message}</div>)}</div>;
}

function ReliabilityPanel({settings,saveSettings,diagnostics,running}){
  const [busy,setBusy]=React.useState(false),[message,setMessage]=React.useState(''),[error,setError]=React.useState('');
  const [report,setReport]=React.useState(null),[scan,setScan]=React.useState(null),[selected,setSelected]=React.useState([]);
  const [weapon,setWeapon]=React.useState(weapons[0].name),[camo,setCamo]=React.useState('Military Camo 1');
  const [start,setStart]=React.useState('0'),[end,setEnd]=React.useState('10'),[expected,setExpected]=React.useState([]);
  React.useEffect(()=>{let alive=true;const off=window.tracker.onReliabilityProgress(value=>{if(typeof value.busy==='boolean')setBusy(value.busy);if(value.message!==undefined)setMessage(value.message);});window.tracker.getReliabilityState().then(info=>{if(!alive)return;setBusy(info.busy);setMessage(info.message||'');setError(info.error||'');setScan(info.scan);if(info.scan?.weapon)setWeapon(info.scan.weapon);setReport(info.report);});return()=>{alive=false;off();};},[]);
  const chosen=weapons.find(w=>w.name===weapon)||weapons[0];
  async function run(action){setError('');setBusy(true);try{const result=await action();if(!result.ok&&!result.cancelled)throw new Error(result.error||'Analysis failed');return result;}catch(e){setError(e.message);return null;}finally{setBusy(false);}}
  function addExpected(){const a=Number(start),b=Number(end);if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b<a){setError('Use popup times with 0 ≤ start ≤ end.');return;}setExpected(list=>[...list,{weapon,camo,start:a,end:b}]);}
  return <div className="reliabilityStack">
    <header><div><span className="eyebrow">RELIABILITY</span><h2>Replay, diagnose & recover</h2><p>Live watching pauses during analysis and resumes afterward.</p></div></header>
    {error&&<div className="error">{error}</div>}
    {busy&&<section className="card"><p role="status">{message||'Working…'}</p><button className="ghost" onClick={()=>window.tracker.cancelAnalysis()}>Cancel analysis</button></section>}
    <CaptureHealthBanner heartbeat={diagnostics.heartbeat} receivedAt={diagnostics.heartbeatAt} running={running}/>
    <section className="card settings"><h3>Capture timing</h3><p>Actual scan rate: {diagnostics.heartbeat?.captureFps??'—'} / {settings.scanFps} scans per second</p><p className="muted">Last scan: {diagnostics.heartbeat?.cycleMs??'—'} ms · Capture: {diagnostics.heartbeat?.grabMs??'—'} ms · Banner checks: {diagnostics.heartbeat?.inspectMs??'—'} ms · Target time per scan: {diagnostics.heartbeat?.targetBudgetMs??'—'} ms</p></section>
    <section className="card settings"><h3>Failed-read snapshots</h3>
      <label className="toggle"><input type="checkbox" checked={settings.collectDiagnostics!==false} disabled={busy} onChange={e=>saveSettings({collectDiagnostics:e.target.checked})}/><span>Save failed popup crops and recognized text locally</span></label>
      <p className="muted">Up to 60 entries, 50 MB and 7 days. These are cropped game popups; they are not uploaded.</p>
      <div className="buttons"><button className="ghost" onClick={async()=>{const r=await window.tracker.openDiagnostics();if(!r.ok)setError(r.error);}}>Open diagnostic folder</button></div>
      {diagnostics.health?.diagnosticError&&<p className="error">Could not save a diagnostic: {diagnostics.health.diagnosticError}</p>}
      <p className="muted">Retry recoveries: {diagnostics.health?.retryRecoveries||0} · Uncertain reads: {diagnostics.health?.uncertainReads||0} · Pending snapshots: {diagnostics.heartbeat?.pendingFrames||0} · Dropped snapshots: {diagnostics.heartbeat?.droppedFrames||0}</p>
    </section>
    <section className="card settings"><h3>Replay a recording</h3>
      <p className="muted">Run a full gameplay recording through the real detector at playback speed. Replays never change your saved camo progress.</p>
      <details><summary>Expected unlocks (optional accuracy scoring)</summary>
        <p className="muted">Add the unlocks you know appear in the clip and their time windows. Without these, missed and false unlocks are unscored.</p>
        <label>Weapon<select value={weapon} onChange={e=>{setWeapon(e.target.value);setCamo('Military Camo 1');setScan(null);setSelected([]);}}>{weapons.map(w=><option key={w.name}>{w.name}</option>)}</select></label>
        <label>Camo<select value={camo} onChange={e=>setCamo(e.target.value)}>{allCamosForWeapon(chosen).map(c=><option key={c.name}>{c.name}</option>)}</select></label>
        <div className="buttons"><label>From (seconds)<input type="number" min="0" value={start} onChange={e=>setStart(e.target.value)}/></label><label>To (seconds)<input type="number" min="0" value={end} onChange={e=>setEnd(e.target.value)}/></label></div>
        <button className="ghost" disabled={busy} onClick={addExpected}>Add expected unlock</button>
        {expected.map((e,i)=><div className="row" key={i}><span>{e.weapon} · {e.camo} · {e.start}–{e.end}s</span><button className="ghost" onClick={()=>setExpected(list=>list.filter((_,n)=>n!==i))}>Remove</button></div>)}
      </details>
      <div className="buttons"><button className="primary" disabled={busy} onClick={async()=>{const r=await run(()=>window.tracker.replayRecording(expected));if(r?.ok)setReport(r.report);}}>Choose recording & replay</button>{report&&<button className="ghost" onClick={()=>window.tracker.openReplayReport()}>Open saved report</button>}</div>
      {report&&<div><p>{report.events.length} detected unlock(s) · Typical read {report.medianReadMs==null?'—':(report.medianReadMs/1000).toFixed(2)+'s'} · {report.droppedFrames} dropped snapshot(s)</p><p>{report.scoring==='scored'?`${report.matched}/${report.expected} expected unlocks matched · ${report.missed.length} missed · ${report.falseDetections.length} false detections`:'Accuracy unscored: no expected unlocks were supplied.'}</p>{report.events.map((e,i)=><div className="row" key={i}><b>{e.weapon}</b><span>{e.camo||`${e.family} ${e.number}`} · {Number(e.sourceTime).toFixed(2)}s in recording</span></div>)}</div>}
    </section>
    <section className="card settings"><h3>Recover from the camo menu</h3>
      <p className="muted">Choose the weapon shown in the game. Start the scan, then switch to its camo menu within 3 seconds. Review the captured image before applying any completions.</p>
      <label>Weapon shown in game<select disabled={busy} value={weapon} onChange={e=>{setWeapon(e.target.value);setCamo('Military Camo 1');setScan(null);setSelected([]);}}>{weapons.map(w=><option key={w.name}>{w.name}</option>)}</select></label>
      <button className="primary" disabled={busy} onClick={async()=>{setScan(null);setSelected([]);const r=await run(()=>window.tracker.scanCamoMenu(weapon));if(r?.ok){setScan(r.scan);setSelected([]);}}}>Scan menu in 3 seconds</button>
      {scan&&<div><h4>Review {scan.weapon}</h4>{!scan.weaponTextSeen&&<p className="muted">The selected weapon name was not read. Verify the weapon in the screenshot before applying.</p>}<p className="muted">Lock icons may be unreadable. Nothing is selected automatically. Check only camos you can verify as earned.</p>{scan.preview&&<img src={scan.preview} alt="Captured game camo menu for verification" style={{width:'100%',borderRadius:8}}/>}
        {!scan.rows.length&&<p>No supported camo names were read. Move the visible camo menu into view and try again, or use the Weapons checklist.</p>}
        {scan.rows.map((row,i)=><label className="row toggle" key={row.name}><input type="checkbox" checked={selected.includes(i)} onChange={e=>setSelected(list=>e.target.checked?[...list,i]:list.filter(n=>n!==i))}/><b>{row.name}</b><span>{row.status==='unlocked'?'Text says unlocked':row.status==='locked'?'Text says locked':'Status unclear'} · {Math.round(row.confidence*100)}% text confidence</span></label>)}
        <div className="buttons"><button className="ghost" onClick={()=>setSelected(scan.rows.flatMap((row,i)=>row.status==='unlocked'?[i]:[]))}>Select rows with unlocked text</button><button className="primary" disabled={!selected.length||busy} onClick={async()=>{const r=await run(()=>window.tracker.applyMenuReconciliation(scan.id,selected));if(r?.ok){setMessage(`Applied ${r.applied} verified camo(s).`);setScan(null);setSelected([]);}}}>Apply selected completions</button></div>
      </div>}
      {!busy&&message&&<p role="status">{message}</p>}
    </section>
  </div>;
}
module.exports={ReliabilityPanel,CaptureHealthBanner};
