const React=require('react');
const {weapons,allCamosForWeapon}=require('./camoCatalog');

function rememberedWeapon(){
  try{const value=window.localStorage.getItem('review-last-weapon');return weapons.some(w=>w.name===value)?value:'';}catch(_){return '';}
}
function ReviewCard({item,onResolve,lastWeapon,onWeaponChange}){
  const [weapon,setWeapon]=React.useState('');
  const [weaponSearch,setWeaponSearch]=React.useState('');
  const [choosingWeapon,setChoosingWeapon]=React.useState(true);
  const [camoSearch,setCamoSearch]=React.useState('');
  const [showOthers,setShowOthers]=React.useState(false);
  const [busy,setBusy]=React.useState(false);
  const [error,setError]=React.useState('');
  const [imageOpen,setImageOpen]=React.useState(false);
  const [actualSize,setActualSize]=React.useState(false);
  const imageClose=React.useRef(null);
  const imageOpener=React.useRef(null);
  React.useEffect(()=>{
    if(!imageOpen)return;
    imageClose.current?.focus();
    const escape=e=>{if(e.key==='Escape'){setImageOpen(false);imageOpener.current?.focus();}};
    window.addEventListener('keydown',escape);
    return()=>window.removeEventListener('keydown',escape);
  },[imageOpen]);
  const selected=weapons.find(w=>w.name===weapon);
  function chooseWeapon(name){setWeapon(name);onWeaponChange(name);setChoosingWeapon(false);setWeaponSearch('');setCamoSearch('');}
  const matchingWeapons=weapons.filter(w=>[w.name,w.category,...(w.aliases||[])].join(' ').toLowerCase().includes(weaponSearch.trim().toLowerCase()));
  const camos=selected?allCamosForWeapon(selected):[];
  const filteredCamos=camos.filter(c=>[c.name,c.requirement].join(' ').toLowerCase().includes(camoSearch.trim().toLowerCase()));
  async function resolve(camo){
    setBusy(true);setError('');
    try{const result=await onResolve(item.id,camo?weapon:null,camo||null);if(!result?.ok)setError(result?.error||'Unable to save.');}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }
  return <section className="card" style={{marginBottom:16}}>
    <span className="eyebrow">BANNER NEEDS REVIEW</span>
    <p>{item.rawText}</p>
    <div style={{margin:'14px 0'}}>
      <div className="buttons" style={{alignItems:'center',flexWrap:'wrap',marginBottom:10}}>
        <b>{selected?`Weapon: ${selected.name}`:'Choose this banner’s weapon'}</b>
        {selected&&<button className="ghost" disabled={busy} onClick={()=>setChoosingWeapon(value=>!value)}>Change weapon</button>}
        <button className="ghost" disabled={busy} onClick={()=>resolve(null)}>Dismiss banner</button>
      </div>
      {choosingWeapon&&<div>
        {lastWeapon&&<button className="ghost" disabled={busy} style={{marginBottom:10}} onClick={()=>chooseWeapon(lastWeapon)}>Recent: {lastWeapon}</button>}
        <input aria-label="Search weapons" placeholder="Type your gun name…" value={weaponSearch} disabled={busy} onChange={e=>setWeaponSearch(e.target.value)} style={{width:'100%',padding:12,marginBottom:8}}/>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))',gap:8,maxHeight:220,overflow:'auto'}}>
          {matchingWeapons.map(w=><button key={w.name} aria-label={`Choose ${w.name}`} className="ghost" disabled={busy} onClick={()=>chooseWeapon(w.name)}>{w.name}<small style={{display:'block',opacity:.65}}>{w.category}</small></button>)}
          {!matchingWeapons.length&&<p>No weapons found.</p>}
        </div>
      </div>}
      {selected&&<div style={{marginTop:12}}>
        <p className="muted">Click a camo to assign it to {selected.name}.</p>
        <div className="buttons" style={{flexWrap:'wrap'}}>
          {filteredCamos.filter(c=>c.type==='Completionist').map(c=><button key={c.name} className="primary" disabled={busy} title={c.requirement} onClick={()=>resolve(c.name)}>Assign {c.name}</button>)}
        </div>
        <div className="buttons" style={{flexWrap:'wrap',marginTop:12}}>
          <input aria-label="Search camos" placeholder="Find another camo…" value={camoSearch} disabled={busy} onChange={e=>setCamoSearch(e.target.value)} style={{padding:10,minWidth:220}}/>
          {!camoSearch&&<button className="ghost" disabled={busy} onClick={()=>setShowOthers(value=>!value)}>{showOthers?'Hide other camos':'Other camos'}</button>}
        </div>
        {(camoSearch||showOthers)&&<div className="buttons" style={{flexWrap:'wrap',marginTop:10}}>
          {filteredCamos.filter(c=>c.type!=='Completionist').map(c=><button key={c.name} className="ghost" disabled={busy} title={c.requirement} onClick={()=>resolve(c.name)}>Assign {c.name}</button>)}
          {!filteredCamos.length&&<p>No camos found.</p>}
        </div>}
      </div>}
      {error&&<p className="error">{error}</p>}
    </div>
    {item.image&&<div>
      <img src={item.image} alt="Captured completion banner with surrounding screen" style={{display:'block',width:'100%',maxWidth:1200,height:'auto',objectFit:'contain'}}/>
      <button ref={imageOpener} className="ghost" onClick={()=>{setActualSize(false);setImageOpen(true);}}>View larger image</button>
    </div>}
    {imageOpen&&<div role="dialog" aria-modal="true" aria-label="Captured banner image" style={{position:'fixed',inset:0,zIndex:1000,background:'#080c12',display:'flex',flexDirection:'column',padding:20}}>
      <div className="buttons" style={{flexShrink:0,marginBottom:16}}>
        <button className="ghost" onClick={()=>setActualSize(value=>!value)}>{actualSize?'Fit image':'Actual size'}</button>
        <button ref={imageClose} className="primary" onClick={()=>{setImageOpen(false);imageOpener.current?.focus();}}>Close image</button>
      </div>
      <div style={{overflow:'auto',flex:1,minHeight:0}}>
        <img src={item.image} alt="Enlarged captured completion banner" style={actualSize?{display:'block',maxWidth:'none',height:'auto'}:{display:'block',width:'100%',height:'100%',objectFit:'contain'}}/>
      </div>
    </div>}
    <p className="muted">This banner was captured without a confirmed weapon and camo. Choose its weapon and click the camo above, or dismiss it if it is another challenge. You can leave it saved and assign it after the match.</p>
  </section>;
}
function CompletionReviews({items=[],onResolve}){
  const [lastWeapon,setLastWeapon]=React.useState(rememberedWeapon);
  function remember(name){setLastWeapon(name);try{window.localStorage.setItem('review-last-weapon',name);}catch(_){} }
  return items.length>0&&<div><h3>Captured banners to review ({items.length})</h3>{items.map(item=><ReviewCard key={item.id} item={item} onResolve={onResolve} lastWeapon={lastWeapon} onWeaponChange={remember}/>)}</div>;
}
module.exports={CompletionReviews};
